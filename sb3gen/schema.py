"""
sb3gen/schema.py
Scratch 3.0 プロジェクトの高レベルデータモデル（Pydantic）および検証・スキーマ定義。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ValidationError

TargetType = Literal["stage", "sprite"]

ALLOWED_OPCODES = {
    # 動き (Motion)
    "motion_movesteps", "motion_turnright", "motion_turnleft", "motion_goto",
    "motion_gotoxy", "motion_glideto", "motion_glidesecstoxy", "motion_pointindirection",
    "motion_pointtowards", "motion_changexby", "motion_setx", "motion_changeyby",
    "motion_sety", "motion_ifonedgebounce", "motion_setrotationstyle",
    "motion_xposition", "motion_yposition", "motion_direction",
    
    # 見た目 (Looks)
    "looks_sayforsecs", "looks_say", "looks_thinkforsecs", "looks_think",
    "looks_switchcostumeto", "looks_nextcostume", "looks_switchbackdropto",
    "looks_changesizeby", "looks_setsizeto", "looks_changeeffectby",
    "looks_seteffectto", "looks_cleargraphiceffects", "looks_show", "looks_hide",
    "looks_gotofrontback", "looks_goforwardbackwardlayers", "looks_costumenumbername",
    "looks_backdropnumbername", "looks_size",
    
    # 音 (Sound)
    "sound_play", "sound_playuntildone", "sound_stopallsounds",
    "sound_changeeffectby", "sound_seteffectto", "sound_cleareffects",
    "sound_changevolumeby", "sound_setvolumeto", "sound_volume",

    # ペン (Pen extension)
    "pen_clear", "pen_stamp", "pen_penDown", "pen_penUp",
    "pen_setPenColorToColor", "pen_changePenColorParamBy", "pen_setPenColorParamTo",
    "pen_changePenSizeBy", "pen_setPenSizeTo",

    # 音楽 (Music extension)
    "music_playDrumForBeats", "music_restForBeats", "music_playNoteForBeats",
    "music_setInstrument", "music_setTempo", "music_changeTempoBy", "music_getTempo",

    # イベント (Events)
    "event_whenflagclicked", "event_whenkeypressed", "event_whenthisspriteclicked",
    "event_whenbackdropswitchesto", "event_whengreaterthan", "event_broadcast",
    "event_broadcastandwait", "event_whenbroadcastreceived",
    
    # 制御 (Control)
    "control_wait", "control_repeat", "control_forever", "control_if",
    "control_if_else", "control_wait_until", "control_repeat_until", "control_stop",
    "control_start_as_clone", "control_create_clone_of", "control_delete_this_clone",
    
    # 調べる (Sensing)
    "sensing_touchingobject", "sensing_touchingcolor", "sensing_coloristouchingcolor",
    "sensing_distanceto", "sensing_askandwait", "sensing_answer", "sensing_keypressed",
    "sensing_mousedown", "sensing_mousex", "sensing_mousey", "sensing_setdragmode",
    "sensing_loudness", "sensing_timer", "sensing_resettimer", "sensing_of",
    "sensing_current", "sensing_dayssince2000", "sensing_username",
    
    # 演算 (Operators)
    "operator_add", "operator_subtract", "operator_multiply", "operator_divide",
    "operator_random", "operator_gt", "operator_lt", "operator_equals",
    "operator_and", "operator_or", "operator_not", "operator_join",
    "operator_letter_of", "operator_length", "operator_mod", "operator_round",
    "operator_mathop",
    
    # 変数・リスト (Variables & Lists)
    "data_variable", "data_setvariableto", "data_changevariableby",
    "data_showvariable", "data_hidevariable", "data_listcontents",
    "data_addtolist", "data_deleteoflist", "data_deletealloflist",
    "data_insertatlist", "data_replaceitemoflist", "data_itemoflist",
    "data_itemnumoflist", "data_lengthoflist", "data_listcontainsitem",
    "data_showlist", "data_hidelist",

    # カスタムブロック（マイブロック / procedures）
    "procedures_definition", "procedures_call", "procedures_prototype",
    "argument_reporter_string_number", "argument_reporter_boolean",
}

# opcodeの接頭辞と、それが属する拡張機能ID（project.json の "extensions" に
# 宣言すべきID）の対応表（2番: 拡張機能）。
EXTENSION_OPCODE_PREFIXES: Dict[str, str] = {
    "pen_": "pen",
    "music_": "music",
}


def extension_id_for_opcode(opcode: str) -> Optional[str]:
    """opcodeが拡張機能ブロックであれば、対応する extensionID を返す。組み込みブロックなら None。"""
    for prefix, extension_id in EXTENSION_OPCODE_PREFIXES.items():
        if opcode.startswith(prefix):
            return extension_id
    return None


class CostumeSpec(BaseModel):
    name: str
    bitmap_resolution: Optional[int] = 1
    data_format: str = "svg"
    asset_id: Optional[str] = None
    md5ext: Optional[str] = None
    rotation_center_x: Optional[float] = None
    rotation_center_y: Optional[float] = None


class SoundSpec(BaseModel):
    name: str
    data_format: str = "wav"
    asset_id: Optional[str] = None
    md5ext: Optional[str] = None
    rate: Optional[int] = None
    sample_count: Optional[int] = None


OpcodeLiteral = Literal[tuple(sorted(ALLOWED_OPCODES))]


class BlockSpec(BaseModel):
    opcode: OpcodeLiteral
    fields: Dict[str, Any] = Field(default_factory=dict)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    substacks: List[List[BlockSpec]] = Field(default_factory=list)
    proc_name: Optional[str] = Field(
        default=None,
        description=(
            "opcode が procedures_call の場合にのみ使う、呼び出すカスタムブロックの名前"
            "（ProcedureDefinitionSpec.name と一致させる）。"
            "inputs は、そのカスタムブロックの引数名（ProcedureArgumentSpec.name）を"
            "キーとして渡す。内部的な argument id への変換はコンパイラが行うため、"
            "呼び出し側は proccode や argument id を意識する必要はない。"
        ),
    )


class ScriptSpec(BaseModel):
    blocks: List[BlockSpec] = Field(default_factory=list)


ProcedureArgumentType = Literal["string_number", "boolean"]


class ProcedureArgumentSpec(BaseModel):
    """カスタムブロック（マイブロック）1個の引数定義。"""

    name: str
    type: ProcedureArgumentType = "string_number"
    default: Any = None


class ProcedureDefinitionSpec(BaseModel):
    """カスタムブロック（マイブロック）の宣言（1番: カスタムブロック）。

    procedures_definition / procedures_prototype / mutation構造 / 引数リポーター群は、
    この宣言（名前・引数・warpモード・本体スクリプト）からコンパイラが自動生成する。
    LLM側や呼び出し側のBlockSpecは、Scratch内部のmutation構造（proccode文字列や
    argument idのJSON文字列表現など）を直接組み立てる必要はない。
    """

    name: str
    arguments: List[ProcedureArgumentSpec] = Field(default_factory=list)
    warp: bool = False
    body: List[BlockSpec] = Field(default_factory=list)

    @property
    def proccode(self) -> str:
        """procedures系ブロックが識別に使う proccode 文字列を生成する。

        Scratch本来の proccode は「jump %s times」のようにラベル文中に引数の
        プレースホルダ（%s=文字列/数値, %b=真偽値）を混在させるが、ここでは
        name をそのままラベルとして扱い、宣言順の引数プレースホルダを末尾に
        連結する単純化した規約を採用する（LLMが組み立てやすいようにするため）。
        """
        if not self.arguments:
            return self.name
        placeholder = {"string_number": "%s", "boolean": "%b"}
        arg_part = " ".join(placeholder[a.type] for a in self.arguments)
        return f"{self.name} {arg_part}"


class SpriteSpec(BaseModel):
    name: str
    is_stage: bool = False
    x: float = 0.0
    y: float = 0.0
    size: float = 100.0
    visible: bool = True
    costumes: List[CostumeSpec] = Field(default_factory=list)
    sounds: List[SoundSpec] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(default_factory=list)
    scripts: List[ScriptSpec] = Field(default_factory=list)
    procedures: List[ProcedureDefinitionSpec] = Field(default_factory=list)


class VariableSpec(BaseModel):
    name: str
    initial_value: Any = 0


class ListSpec(BaseModel):
    name: str
    items: List[Any] = Field(default_factory=list)


class SpriteShellSpec(BaseModel):
    """SpriteSpec から scripts を除いた「入れ物」部分。

    LLM出力の巨大化・途中切れ対策（7番: LLM出力安定性）として、スプライト生成を
    「メタ情報＋スクリプト計画」と「スクリプト本体（1本ずつ）」の2段階に分割する際、
    前段の出力形式として使う中間表現。

    procedures（カスタムブロック宣言）はscriptsと同じくブロック本体を含み得るため、
    シェル段階では出力させず、SpriteGenerationPlan側で別途スクリプトと同様の
    分割生成対象として扱う想定（1番）。
    """

    name: str
    is_stage: bool = False
    x: float = 0.0
    y: float = 0.0
    size: float = 100.0
    visible: bool = True
    costumes: List[CostumeSpec] = Field(default_factory=list)
    sounds: List[SoundSpec] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(default_factory=list)

    def to_sprite_spec(
        self,
        scripts: List[ScriptSpec],
        procedures: Optional[List[ProcedureDefinitionSpec]] = None,
    ) -> SpriteSpec:
        return SpriteSpec(
            name=self.name,
            is_stage=self.is_stage,
            x=self.x,
            y=self.y,
            size=self.size,
            visible=self.visible,
            costumes=self.costumes,
            sounds=self.sounds,
            variables=self.variables,
            scripts=scripts,
            procedures=procedures or [],
        )


class BroadcastSpec(BaseModel):
    name: str


class ProjectSpec(BaseModel):
    targets: List[SpriteSpec] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(default_factory=list)
    lists: List[ListSpec] = Field(default_factory=list)
    broadcasts: List[BroadcastSpec] = Field(default_factory=list)

    @property
    def sprites(self) -> List[SpriteSpec]:
        return [t for t in self.targets if not t.is_stage]

    @property
    def stage(self) -> Optional[SpriteSpec]:
        return next((t for t in self.targets if t.is_stage), None)


def _check_blocks(blocks: List[BlockSpec], proc_names: set) -> None:
    for block in blocks:
        if block.opcode not in ALLOWED_OPCODES:
            raise ValueError(f"許可されていないopcodeです: {block.opcode}")
        if block.opcode == "procedures_call":
            if not block.proc_name:
                raise ValueError("procedures_call ブロックには proc_name の指定が必要です。")
            if block.proc_name not in proc_names:
                raise ValueError(f"未定義のカスタムブロックを呼び出しています: {block.proc_name}")
        for substack in block.substacks:
            _check_blocks(substack, proc_names)


def validate_project_spec(data: Dict[str, Any]) -> ProjectSpec:
    project = ProjectSpec.model_validate(data)
    for target in project.targets:
        proc_names = {p.name for p in target.procedures}
        # このターゲット自身が定義しているカスタムブロックの重複名チェック
        if len(proc_names) != len(target.procedures):
            raise ValueError(f"スプライト '{target.name}' でカスタムブロック名が重複しています。")
        for proc in target.procedures:
            arg_names = [a.name for a in proc.arguments]
            if len(set(arg_names)) != len(arg_names):
                raise ValueError(f"カスタムブロック '{proc.name}' の引数名が重複しています。")
            _check_blocks(proc.body, proc_names)
        for script in target.scripts:
            _check_blocks(script.blocks, proc_names)
    return project
