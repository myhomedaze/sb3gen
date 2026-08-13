"""
sb3gen/patcher.py
差分修正・聞き返し（Clarification）オーケストレーション層。
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Callable, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field, ValidationError

from .schema import (
    BroadcastSpec,
    ListSpec,
    ProjectSpec,
    SpriteSpec,
    VariableSpec,
    validate_project_spec,
    CostumeSpec,
)
from .renderer import render_sprite_pseudocode
from .linter import reconcile_globals

LLMCallable = Callable[[str, str], str]

MAX_CLARIFICATION_TURNS = 3
MAX_GENERATION_RETRIES = 3

CLARIFICATION_FALLBACK_MESSAGE = (
    "申し訳ありませんが、ご要望の詳細を十分に確認できませんでした。"
    "お手数ですが、変更したいスプライト名や具体的な内容を含めて、"
    "もう一度指示をお願いいたします。"
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _strip_code_fence(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
    return cleaned.strip()


def _generate_with_retry(
    system_prompt: str,
    initial_user_prompt: str,
    model_cls: Type[_ModelT],
    llm_call: LLMCallable,
    max_retries: int = MAX_GENERATION_RETRIES,
) -> _ModelT:
    schema_json = json.dumps(model_cls.model_json_schema(), ensure_ascii=False, indent=2)
    enhanced_system_prompt = (
        f"{system_prompt}\n\n"
        "【出力形式の厳守】\n"
        "必ず以下のJSONスキーマに完全に準拠したJSONオブジェクトのみを出力してください（Markdownのコードブロックを含め、余分なテキストや解説は一切含めないこと）。\n"
        f"{schema_json}"
    )

    user_prompt = initial_user_prompt
    last_error: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        raw = llm_call(enhanced_system_prompt, user_prompt)
        cleaned = _strip_code_fence(raw)

        try:
            data = json.loads(cleaned)
            return model_cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = str(e)
            user_prompt = (
                f"{initial_user_prompt}\n\n"
                f"--- 前回の出力はエラーになりました（試行 {attempt}/{max_retries}） ---\n"
                f"エラー内容:\n{last_error}\n"
                f"前回の出力:\n{cleaned}\n\n"
                "上記のエラーを修正し、指定されたJSONスキーマに厳密に従って、"
                "JSONオブジェクトのみを出力し直してください。"
            )

    raise ValueError(
        f"{max_retries}回のリトライ後もLLM出力の検証に失敗しました。最終エラー: {last_error}"
    )


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
    clarification_question: Optional[str] = Field(default=None)


class ClarificationTurn(BaseModel):
    question: str
    user_answer: str


class PendingClarification(BaseModel):
    original_instruction: str
    turns: List[ClarificationTurn] = Field(default_factory=list)
    current_question: Optional[str] = Field(default=None)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def history_as_text(self) -> str:
        if not self.turns:
            return f"最初の要望: {self.original_instruction}"
        lines = [f"最初の要望: {self.original_instruction}"]
        for i, t in enumerate(self.turns, start=1):
            lines.append(f"  Q{i}: {t.question}")
            lines.append(f"  A{i}: {t.user_answer}")
        return "\n".join(lines)

    def combined_instruction(self) -> str:
        parts = [self.original_instruction]
        for t in self.turns:
            parts.append(f"（補足質問「{t.question}」への回答: {t.user_answer}）")
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
clarification_question に質問文を設定してください（その場合 actions は空リスト）。
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


_MODIFY_SPRITE_SYSTEM_PROMPT = "対象スプライトの状態と指示に基づき、新しいSpriteSpec互換のJSONを出力してください。既存コスチュームのasset_idは可能な限り引き継いでください。"


def handle_modify_sprite(
    project: ProjectSpec, sprite_name: str, instruction: str, llm_call: LLMCallable
) -> PatchResult:
    target_sprite = next((s for s in project.sprites if s.name == sprite_name), None)
    if target_sprite is None:
        return PatchResult(status=PatchStatus.FAILED, message=f"スプライト '{sprite_name}' が見つかりません。")

    pseudocode = render_sprite_pseudocode(target_sprite)
    user_prompt = f"--- 対象スプライト ---\n{pseudocode}\n\n--- 修正指示 ---\n{instruction}\n"

    try:
        new_sprite = _generate_with_retry(
            _MODIFY_SPRITE_SYSTEM_PROMPT, user_prompt, SpriteSpec, llm_call
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


def handle_add_sprite(
    project: ProjectSpec,
    instruction: str,
    llm_call: LLMCallable,
    materialize_asset: MaterializeAssetCallable,
) -> PatchResult:
    try:
        decisions = _decide_assets(instruction, llm_call)
        costumes = [materialize_asset(d) for d in decisions]
        
        user_prompt = f"ユーザーの指示: {instruction}\n利用可能なコスチューム名: {[c.name for c in costumes]}\n"
        new_sprite = _generate_with_retry(
            "新規スプライトの定義を SpriteSpec 形式で出力してください。", user_prompt, SpriteSpec, llm_call
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

    if pending is not None and pending.current_question:
        pending.turns.append(
            ClarificationTurn(
                question=pending.current_question,
                user_answer=instruction,
            )
        )
        pending.current_question = None

    effective_instruction = pending.combined_instruction() if pending else instruction

    try:
        plan = plan_instruction(effective_instruction, project, llm_call, pending=pending)
    except ValueError as e:
        return PatchResult(status=PatchStatus.FAILED, message=str(e))

    if plan.clarification_needed or not plan.actions:
        new_pending = pending or PendingClarification(original_instruction=instruction)
        new_pending.current_question = plan.clarification_question
        return PatchResult(
            status=PatchStatus.NEEDS_CLARIFICATION,
            message=plan.clarification_question or "詳細を教えてください。",
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