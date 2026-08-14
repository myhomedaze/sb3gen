"""
sb3gen/patcher.py
差分修正・聞き返し（Clarification）オーケストレーション層。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, List, Optional

from pydantic import BaseModel, Field, ValidationError

from .schema import (
    BroadcastSpec,
    ListSpec,
    ProcedureArgumentSpec,
    ProcedureArgumentType,
    ProcedureDefinitionSpec,
    ProjectSpec,
    ScriptSpec,
    SpriteShellSpec,
    SpriteSpec,
    VariableSpec,
    validate_project_spec,
    CostumeSpec,
)
from .renderer import render_sprite_pseudocode
from .linter import reconcile_globals
from .llm_io import (
    LLMCallable,
    MAX_GENERATION_RETRIES,
    generate_items_individually,
    generate_json_with_retry,
)

# 7番（LLM出力安定性）: JSONの整形/検証/リトライの実体は sb3gen.llm_io に集約してある。
# ここでは以前のローカル名と互換を保つためのエイリアスを保持する。
_generate_with_retry = generate_json_with_retry

MAX_CLARIFICATION_TURNS = 3

CLARIFICATION_FALLBACK_MESSAGE = (
    "申し訳ありませんが、ご要望の詳細を十分に確認できませんでした。"
    "お手数ですが、変更したいスプライト名や具体的な内容を含めて、"
    "もう一度指示をお願いいたします。"
)


_PROCEDURE_BODY_SYSTEM_PROMPT = (
    "対象のカスタムブロック（マイブロック）の本体を1個分、ScriptSpec（blocksのリスト）形式の"
    "JSONのみで出力してください。他のカスタムブロックやスクリプトの内容はここに含めないでください。"
    "本体内でこのカスタムブロックの引数の値を参照する場合は、"
    "argument_reporter_string_number または argument_reporter_boolean ブロックを使い、"
    "fields.VALUE にその引数名をそのまま指定してください。"
)


class ScriptPlanItem(BaseModel):
    """スプライト生成の第1段階で出力される、スクリプト一本分の軸となる要約。

    blocksの詳細（ブロック木）はこの段階では出力させず、後続の段階で
    この要約を手がかりにスクリプトを、1本ずつ個別にLLM呼び出しして生成する（7番）。
    """

    summary: str = Field(
        description="このスクリプトが行うことの簡潔な要約（例: 「旗クリックで10歩動く」）"
    )


class ProcedureArgumentPlanItem(BaseModel):
    """カスタムブロック引数1個分のシグネチャ（名前・型・既定値）。"""

    name: str
    type: ProcedureArgumentType = "string_number"
    default: Any = None


class ProcedurePlanItem(BaseModel):
    """スプライト生成の第1段階で出力される、カスタムブロック（マイブロック）1個分の
    シグネチャ（名前・引数・warp）と、本体の簡潔な要約（1番: カスタムブロック）。

    ScriptPlanItemと同様、本体のブロック木はこの段階では出力させず、このシグネチャを
    手がかりに後続の段階でカスタムブロックごとに個別にLLM呼び出しして生成する（7番の分割方針を
    カスタムブロックにも適用）。
    """

    name: str
    arguments: List[ProcedureArgumentPlanItem] = Field(default_factory=list)
    warp: bool = False
    summary: str = Field(
        description="このカスタムブロック（マイブロック）が行うことの簡潔な要約"
    )


class SpriteGenerationPlan(BaseModel):
    """スプライト生成の第1段階の出力形式。

    shellには名前・位置・コスチューム・ローカル変数など、scriptsを除くスプライトの
    状態を、script_planには必要なスクリプトの要約一覧だけを、procedure_planにはこのスプライトが
    定義すべきカスタムブロックのシグネチャと要約一覧だけを保持する（1番）。
    いずれもブロック木を含まないため、この段階の出力は小さく保たれる。
    """

    shell: SpriteShellSpec
    script_plan: List[ScriptPlanItem] = Field(default_factory=list)
    procedure_plan: List[ProcedurePlanItem] = Field(default_factory=list)


def _generate_sprite_chunked(
    shell_system_prompt: str,
    shell_user_prompt: str,
    script_system_prompt: str,
    llm_call: LLMCallable,
    existing_scripts_context: str = "",
    procedure_system_prompt: str = _PROCEDURE_BODY_SYSTEM_PROMPT,
) -> SpriteSpec:
    """スプライトを「入れ物（shell）＋スクリプト計画＋カスタムブロック計画」→
    「スクリプト／カスタムブロック本体を1本ずつ生成」の2段階で生成する（7番: LLM出力安定性）。

    以前の実装は SpriteSpec 全体（全スクリプトのブロック木を含む）を、1回のLLM呼び出しで
    一気に出力させていたため、スクリプトが多い・複雑なスプライトでは出力が途中で切れやすかった。
    今後カスタムブロックや拡張機能でスクリプト一本あたりのサイズがさらに増えても、
    この分割方式なら、1回の呼び出しあたりの出力サイズはスクリプト・カスタムブロック単位に抑えられる。

    plan.procedure_plan（カスタムブロックのシグネチャ＋要約）は、以前はここで無視されており、
    SpriteGenerationPlanで計画されたカスタムブロックが実際には一切生成されない不具合が
    あったため、scriptsと同様に1個ずつ本体を個別生成してSpriteSpec.proceduresへ反映する。
    """
    plan = generate_json_with_retry(
        shell_system_prompt, shell_user_prompt, SpriteGenerationPlan, llm_call
    )

    def _script_system_prompt(idx: int, total: int) -> str:
        return (
            f"{script_system_prompt}\n\n"
            f"これは全{total}本中 {idx + 1}本目のスクリプトです。このスクリプト1本分の"
            "ScriptSpec（blocksのリスト）のみを出力し、他のスクリプトの内容は含めないでください。"
        )

    def _script_user_prompt(idx: int, plan_item: ScriptPlanItem) -> str:
        other_summaries = [p.summary for i, p in enumerate(plan.script_plan) if i != idx]
        prompt = (
            f"スプライト: {plan.shell.name}\n"
            f"このスプライトの他のスクリプトの要約（矛盾やブロードキャストの整合性の参考）: {other_summaries}\n"
        )
        if existing_scripts_context:
            prompt += f"参考（既存のスクリプト文脈）:\n{existing_scripts_context}\n"
        prompt += f"このスクリプトで実装すべき内容: {plan_item.summary}\n"
        return prompt

    scripts = (
        generate_items_individually(
            plan.script_plan,
            _script_system_prompt,
            _script_user_prompt,
            ScriptSpec,
            llm_call,
        )
        if plan.script_plan
        else []
    )

    def _procedure_system_prompt(idx: int, total: int) -> str:
        return (
            f"{procedure_system_prompt}\n\n"
            f"これは全{total}個中 {idx + 1}個目のカスタムブロック（マイブロック）です。"
            "この本体1個分のScriptSpec（blocksのリスト）のみを出力し、他のカスタムブロックや"
            "スクリプトの内容は含めないでください。"
        )

    def _procedure_user_prompt(idx: int, plan_item: ProcedurePlanItem) -> str:
        other_summaries = [p.summary for i, p in enumerate(plan.procedure_plan) if i != idx]
        prompt = (
            f"スプライト: {plan.shell.name}\n"
            f"このカスタムブロックの名前: {plan_item.name}\n"
            "引数（本体内では argument_reporter_string_number / argument_reporter_boolean の"
            f"fields.VALUEにこの名前を指定して参照する）: {[(a.name, a.type) for a in plan_item.arguments]}\n"
            f"warp（画面更新をスキップして高速実行するか）: {plan_item.warp}\n"
            f"このスプライトの他のカスタムブロックの要約: {other_summaries}\n"
        )
        if existing_scripts_context:
            prompt += f"参考（既存のスクリプト・カスタムブロック文脈）:\n{existing_scripts_context}\n"
        prompt += f"このカスタムブロックの本体で実装すべき内容: {plan_item.summary}\n"
        return prompt

    procedure_bodies = (
        generate_items_individually(
            plan.procedure_plan,
            _procedure_system_prompt,
            _procedure_user_prompt,
            ScriptSpec,
            llm_call,
        )
        if plan.procedure_plan
        else []
    )

    procedures = [
        ProcedureDefinitionSpec(
            name=plan_item.name,
            arguments=[
                ProcedureArgumentSpec(name=a.name, type=a.type, default=a.default)
                for a in plan_item.arguments
            ],
            warp=plan_item.warp,
            body=body.blocks,
        )
        for plan_item, body in zip(plan.procedure_plan, procedure_bodies)
    ]

    return plan.shell.to_sprite_spec(scripts=scripts, procedures=procedures)


class ActionType(str, Enum):
    MODIFY_SPRITE = "modify_sprite"
    ADD_SPRITE = "add_sprite"
    REMOVE_SPRITE = "remove_sprite"
    MODIFY_GLOBALS = "modify_globals"


class ActionSpec(BaseModel):
    """計画フェーズが出力する、単一の編集操作単位。"""

    type: ActionType
    target: Optional[str] = Field(
        default=None, description="modify_sprite / remove_sprite の対象スプライト名"
    )
    instruction: str = Field(description="このアクション固有の具体的な指示文")


class ActionPlan(BaseModel):
    """ユーザーの自然言語指示を分解した実行計画。"""

    actions: List[ActionSpec] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_questions: List[str] = Field(default_factory=list)


class ClarificationTurn(BaseModel):
    questions: List[str] = Field(default_factory=list)
    user_answer: str


class PendingClarification(BaseModel):
    original_instruction: str
    turns: List[ClarificationTurn] = Field(default_factory=list)
    current_questions: List[str] = Field(default_factory=list)
    # ユーザーが追加の質問に回答せず、妥当なデフォルト値での進行を希望した場合に立てる
    # フラグ。combined_instruction() を通じて plan_instruction のプロンプトに反映され、
    # LLMへ「これ以上質問せずactionsを生成すること」を明示的に指示する。
    allow_defaults: bool = False

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def history_as_text(self) -> str:
        if not self.turns:
            return f"最初の要望: {self.original_instruction}"
        lines = [f"最初の要望: {self.original_instruction}"]
        for i, t in enumerate(self.turns, start=1):
            for j, q in enumerate(t.questions, start=1):
                lines.append(f"  Q{i}-{j}: {q}")
            lines.append(f"  A{i}: {t.user_answer}")
        return "\n".join(lines)

    def combined_instruction(self) -> str:
        parts = [self.original_instruction]
        for t in self.turns:
            joined_questions = " / ".join(t.questions) if t.questions else "(質問なし)"
            parts.append(f"（補足質問「{joined_questions}」への回答: {t.user_answer}）")
        if self.allow_defaults:
            parts.append(
                "（ユーザーはこれ以上の質問に回答しない意向です。不明な点は妥当なデフォルト値で"
                "補ったうえで、これ以上質問せず必ずactionsを生成してください。）"
            )
        return " ".join(parts)


_PLANNING_SYSTEM_PROMPT = """あなたはScratch 3.0プロジェクト編集システムの計画立案者です。
ユーザーの自然言語指示を解析し、実行すべき一連のアクションに分解してください。

各アクションは以下のいずれかのtypeを持ちます:
- add_sprite: 新しいスプライトを追加する
- modify_sprite: 既存の特定スプライトを変更する（targetに対象スプライト名を指定）
- remove_sprite: 既存のスプライトを削除する（targetに対象スプライト名を指定）
- modify_globals: グローバル変数・リスト・ブロードキャストの変更

指示が複数の要素を含む場合は、それぞれを独立したアクションに分解し、
実行すべき順序で並べてください。後続のアクションが前のアクションで
作られる要素（スプライト名など）を参照する場合は、instructionに明記してください。

指示全体が曖昧な場合のみ clarification_needed を true にし、
clarification_questions に、ユーザーへ確認したい質問を最大3件までのリストとして
設定してください（その場合 actions は空リスト）。質問は生成結果を大きく左右する
重要な点に絞り、些末な確認で質問数を無駄に増やさないこと。

指示文中に「これ以上質問せずactionsを生成してください」といった、デフォルト値での
進行を許可する旨の記述が含まれている場合は、以後 clarification_needed を true にせず、
不明点は妥当なデフォルト値で補ったうえで必ず actions を生成してください。
"""


def plan_instruction(
    instruction: str,
    project: ProjectSpec,
    llm_call: LLMCallable,
    pending: Optional[PendingClarification] = None,
) -> ActionPlan:
    sprite_names = [s.name for s in project.sprites]
    history_text = pending.history_as_text() if pending else ""

    user_prompt = (
        f"現在のスプライト一覧: {sprite_names}\n"
        + (f"これまでの聞き返し履歴:\n{history_text}\n" if history_text else "")
        + f"ユーザーの指示: {instruction}\n"
    )

    return _generate_with_retry(_PLANNING_SYSTEM_PROMPT, user_prompt, ActionPlan, llm_call)


class PatchStatus(str, Enum):
    SUCCESS = "success"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class ActionResult(BaseModel):
    action: ActionSpec
    status: PatchStatus
    message: Optional[str] = None


class PatchResult(BaseModel):
    status: PatchStatus
    project: Optional[ProjectSpec] = None
    message: Optional[str] = None
    pending_clarification: Optional[PendingClarification] = None
    action_results: List[ActionResult] = Field(default_factory=list)


_MODIFY_SPRITE_SHELL_SYSTEM_PROMPT = (
    "対象スプライトの状態と指示に基づき、新しいSpriteGenerationPlan形式のJSONを出力してください。"
    "shellフィールドには名前・位置・コスチューム・ローカル変数などscriptsを除く情報のみを、"
    "script_planフィールドには修正後に必要なスクリプトそれぞれの簡潔な要約(summary)のみを出力してください。"
    "blocksの詳細（ブロック木）はこの段階では出力しないでください。"
    "既存コスチュームのasset_idは可能な限り引き継いでください。"
    "このスプライトだけが使う値（例: このキャラクターのHPや状態など）は、"
    "shell.variablesにローカル変数として定義してください（他のスプライトからは見えません）。"
    "他のスプライトやステージと共有すべき値はここにvariablesとして含めず、"
    "グローバル変数として別途指示（modify_globals）に任せてください。"
    "このスプライトが定義すべきカスタムブロック（マイブロック）がある場合は、"
    "procedure_planフィールドに、それぞれの名前・引数（arguments）・warp・本体の簡潔な要約(summary)"
    "のみを出力してください（本体のブロック木はこの段階では出力しないでください）。"
)

_MODIFY_SPRITE_SCRIPT_SYSTEM_PROMPT = (
    "対象スプライトのスクリプトを1本分、ScriptSpec（blocksのリスト）形式のJSONのみで出力してください。"
    "他のスクリプトの内容はここに含めないでください。"
)


def handle_modify_sprite(
    project: ProjectSpec, sprite_name: str, instruction: str, llm_call: LLMCallable
) -> PatchResult:
    target_sprite = next((s for s in project.sprites if s.name == sprite_name), None)
    if target_sprite is None:
        return PatchResult(status=PatchStatus.FAILED, message=f"スプライト '{sprite_name}' が見つかりません。")

    pseudocode = render_sprite_pseudocode(target_sprite)
    shell_user_prompt = f"--- 対象スプライト ---\n{pseudocode}\n\n--- 修正指示 ---\n{instruction}\n"

    # 7番（LLM出力安定性）: SpriteSpec全体を1回で出力させず、shell（入れ物）＋
    # スクリプト計画 → スクリプトを1本ずつ生成、の2段階に分割する。既存のスクリプト
    # 文脈（pseudocode）を各スクリプト生成呼び出しに渡し、矛盾を防ぐ。
    try:
        new_sprite = _generate_sprite_chunked(
            _MODIFY_SPRITE_SHELL_SYSTEM_PROMPT,
            shell_user_prompt,
            _MODIFY_SPRITE_SCRIPT_SYSTEM_PROMPT,
            llm_call,
            existing_scripts_context=pseudocode,
        )
    except ValueError as e:
        return PatchResult(status=PatchStatus.FAILED, message=str(e))

    existing_costume_map = {c.name: c.asset_id for c in target_sprite.costumes}
    merged_costumes = []
    for c in new_sprite.costumes:
        aid = c.asset_id or existing_costume_map.get(c.name)
        merged_costumes.append(c.model_copy(update={"asset_id": aid}))
    new_sprite = new_sprite.model_copy(update={"costumes": merged_costumes})

    stage = project.stage
    new_sprites = [new_sprite if s.name == sprite_name else s for s in project.sprites]
    new_targets = ([stage] if stage else []) + new_sprites
    candidate = project.model_copy(update={"targets": new_targets})

    try:
        validated = validate_project_spec(candidate.model_dump())
    except (ValidationError, ValueError) as e:
        return PatchResult(status=PatchStatus.FAILED, message=f"検証失敗: {e}")

    return PatchResult(status=PatchStatus.SUCCESS, project=validated)


class AssetSourceType(str, Enum):
    TEMPLATE = "template"
    SVG_GENERATE = "svg_generate"
    PLACEHOLDER = "placeholder"


class AssetDecision(BaseModel):
    costume_name: str
    source_type: AssetSourceType
    template_name: Optional[str] = None
    svg_generation_prompt: Optional[str] = None


class AssetDecisionList(BaseModel):
    decisions: List[AssetDecision] = Field(default_factory=list)


MaterializeAssetCallable = Callable[[AssetDecision], CostumeSpec]


def _decide_assets(instruction: str, llm_call: LLMCallable) -> List[AssetDecision]:
    result = _generate_with_retry(
        "新規スプライトに必要なコスチュームの取得方法を決定してください。",
        f"指示: {instruction}",
        AssetDecisionList,
        llm_call,
    )
    return result.decisions


_ADD_SPRITE_SHELL_SYSTEM_PROMPT = (
    "新規スプライトの定義を SpriteGenerationPlan 形式で出力してください。"
    "shellフィールドには名前・位置・コスチューム名・ローカル変数などscriptsを除く情報のみを、"
    "script_planフィールドには実装すべきスクリプトそれぞれの簡潔な要約(summary)のみを出力してください。"
    "blocksの詳細（ブロック木）はこの段階では出力しないでください。"
    "このスプライト固有の状態（例: HP、スコア、タイマーなど）は shell.variables に"
    "ローカル変数として定義してください（他のスプライトからは見えません）。"
    "他と共有すべき値はここに含めず、別のglobals指示に任せてください。"
    "このスプライトが定義すべきカスタムブロック（マイブロック）がある場合は、"
    "procedure_planフィールドに、それぞれの名前・引数（arguments）・warp・本体の簡潔な要約(summary)"
    "のみを出力してください（本体のブロック木はこの段階では出力しないでください）。"
)

_ADD_SPRITE_SCRIPT_SYSTEM_PROMPT = (
    "新規スプライトのスクリプトを1本分、ScriptSpec（blocksのリスト）形式のJSONのみで出力してください。"
    "他のスクリプトの内容はここに含めないでください。"
)


def handle_add_sprite(
    project: ProjectSpec,
    instruction: str,
    llm_call: LLMCallable,
    materialize_asset: MaterializeAssetCallable,
) -> PatchResult:
    try:
        decisions = _decide_assets(instruction, llm_call)
        costumes = [materialize_asset(d) for d in decisions]

        shell_user_prompt = f"ユーザーの指示: {instruction}\n利用可能なコスチューム名: {[c.name for c in costumes]}\n"
        # 7番（LLM出力安定性）: こちらも SpriteSpec 全体を一括出力させず、
        # shell（入れ物）＋スクリプト計画 → スクリプトを1本ずつ生成、の2段階に分割する。
        new_sprite = _generate_sprite_chunked(
            _ADD_SPRITE_SHELL_SYSTEM_PROMPT,
            shell_user_prompt,
            _ADD_SPRITE_SCRIPT_SYSTEM_PROMPT,
            llm_call,
        )
        new_sprite = new_sprite.model_copy(update={"costumes": costumes})
    except (ValueError, ValidationError) as e:
        return PatchResult(status=PatchStatus.FAILED, message=str(e))

    if any(s.name == new_sprite.name for s in project.sprites):
        return PatchResult(status=PatchStatus.FAILED, message=f"スプライト名 '{new_sprite.name}' は既に存在します。")

    candidate = project.model_copy(update={"targets": [*project.targets, new_sprite]})

    try:
        validated = validate_project_spec(candidate.model_dump())
    except (ValidationError, ValueError) as e:
        return PatchResult(status=PatchStatus.FAILED, message=f"検証失敗: {e}")

    return PatchResult(status=PatchStatus.SUCCESS, project=validated)


def handle_remove_sprite(project: ProjectSpec, sprite_name: str) -> PatchResult:
    if not any(s.name == sprite_name for s in project.sprites):
        return PatchResult(status=PatchStatus.FAILED, message=f"スプライト '{sprite_name}' が見つかりません。")

    new_targets = [t for t in project.targets if t.name != sprite_name]
    candidate = project.model_copy(update={"targets": new_targets})

    try:
        validated = validate_project_spec(candidate.model_dump())
    except (ValidationError, ValueError) as e:
        return PatchResult(status=PatchStatus.FAILED, message=f"検証失敗: {e}")

    return PatchResult(status=PatchStatus.SUCCESS, project=validated)


class GlobalsPatch(BaseModel):
    add_variables: List[VariableSpec] = Field(default_factory=list)
    remove_variable_names: List[str] = Field(default_factory=list)
    add_lists: List[ListSpec] = Field(default_factory=list)
    remove_list_names: List[str] = Field(default_factory=list)
    add_broadcasts: List[BroadcastSpec] = Field(default_factory=list)
    remove_broadcast_names: List[str] = Field(default_factory=list)


def handle_modify_globals(
    project: ProjectSpec, instruction: str, llm_call: LLMCallable
) -> PatchResult:
    user_prompt = (
        f"変数: {[v.name for v in project.variables]}\n"
        f"リスト: {[l.name for l in project.lists]}\n"
        f"ブロードキャスト: {[b.name for b in project.broadcasts]}\n"
        f"指示: {instruction}\n"
    )
    try:
        patch = _generate_with_retry(
            "グローバル定義の変更点を GlobalsPatch 形式で出力してください。", user_prompt, GlobalsPatch, llm_call
        )
    except ValueError as e:
        return PatchResult(status=PatchStatus.FAILED, message=str(e))

    remove_var_names = set(patch.remove_variable_names)
    remove_list_names = set(patch.remove_list_names)
    remove_broadcast_names = set(patch.remove_broadcast_names)

    new_vars = [v for v in project.variables if v.name not in remove_var_names] + patch.add_variables
    new_lists = [l for l in project.lists if l.name not in remove_list_names] + patch.add_lists
    new_bcasts = [b for b in project.broadcasts if b.name not in remove_broadcast_names] + patch.add_broadcasts

    candidate = project.model_copy(update={"variables": new_vars, "lists": new_lists, "broadcasts": new_bcasts})

    try:
        validated = validate_project_spec(candidate.model_dump())
    except (ValidationError, ValueError) as e:
        return PatchResult(status=PatchStatus.FAILED, message=f"検証失敗: {e}")

    return PatchResult(status=PatchStatus.SUCCESS, project=validated)


def _execute_action(
    project: ProjectSpec,
    action: ActionSpec,
    llm_call: LLMCallable,
    materialize_asset: Optional[MaterializeAssetCallable],
) -> PatchResult:
    if action.type == ActionType.MODIFY_SPRITE:
        if not action.target:
            return PatchResult(status=PatchStatus.FAILED, message="スプライト名が特定できません。")
        return handle_modify_sprite(project, action.target, action.instruction, llm_call)

    if action.type == ActionType.ADD_SPRITE:
        if materialize_asset is None:
            return PatchResult(status=PatchStatus.FAILED, message="materialize_asset が未注入です。")
        return handle_add_sprite(project, action.instruction, llm_call, materialize_asset)

    if action.type == ActionType.REMOVE_SPRITE:
        if not action.target:
            return PatchResult(status=PatchStatus.FAILED, message="削除対象スプライト名が特定できません。")
        return handle_remove_sprite(project, action.target)

    if action.type == ActionType.MODIFY_GLOBALS:
        return handle_modify_globals(project, action.instruction, llm_call)

    return PatchResult(status=PatchStatus.FAILED, message=f"未対応の action type: {action.type}")


def apply_patch(
    project: ProjectSpec,
    instruction: str,
    llm_call: LLMCallable,
    materialize_asset: Optional[MaterializeAssetCallable] = None,
    pending: Optional[PendingClarification] = None,
) -> PatchResult:
    if pending is not None and pending.turn_count >= MAX_CLARIFICATION_TURNS:
        return PatchResult(status=PatchStatus.FAILED, message=CLARIFICATION_FALLBACK_MESSAGE)

    if pending is not None and pending.current_questions:
        pending.turns.append(
            ClarificationTurn(
                questions=list(pending.current_questions),
                user_answer=instruction,
            )
        )
        pending.current_questions = []

    effective_instruction = pending.combined_instruction() if pending else instruction

    try:
        plan = plan_instruction(effective_instruction, project, llm_call, pending=pending)
    except ValueError as e:
        return PatchResult(status=PatchStatus.FAILED, message=str(e))

    if plan.clarification_needed or not plan.actions:
        new_pending = pending or PendingClarification(original_instruction=instruction)
        new_pending.current_questions = plan.clarification_questions[:3]
        message_text = (
            "\n".join(f"{i}. {q}" for i, q in enumerate(new_pending.current_questions, start=1))
            if new_pending.current_questions
            else "詳細を教えてください。"
        )
        return PatchResult(
            status=PatchStatus.NEEDS_CLARIFICATION,
            message=message_text,
            pending_clarification=new_pending,
        )

    current_project = project
    action_results: List[ActionResult] = []

    for action in plan.actions:
        result = _execute_action(current_project, action, llm_call, materialize_asset)
        action_results.append(
            ActionResult(action=action, status=result.status, message=result.message)
        )

        if result.status == PatchStatus.SUCCESS and result.project is not None:
            current_project = reconcile_globals(result.project)
            continue

        # 途中失敗: それまでの成功分（current_project）は保持したまま報告して中断する。
        return PatchResult(
            status=PatchStatus.FAILED,
            project=current_project,
            message=(
                f"アクション {len(action_results)}/{len(plan.actions)} 番目"
                f"（{action.type.value}）で失敗しました: {result.message}\n"
                f"それまでの変更（{len(action_results) - 1}件）は保持されています。"
            ),
            action_results=action_results,
        )

    return PatchResult(status=PatchStatus.SUCCESS, project=current_project, action_results=action_results)