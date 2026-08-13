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
}


class CostumeSpec(BaseModel):
    name: str
    bitmap_resolution: Optional[int] = 1
    data_format: str = "svg"
    asset_id: Optional[str] = None
    md5ext: Optional[str] = None


class BlockSpec(BaseModel):
    opcode: str
    fields: Dict[str, Any] = Field(default_factory=dict)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    substacks: List[List[BlockSpec]] = Field(default_factory=list)


class ScriptSpec(BaseModel):
    blocks: List[BlockSpec] = Field(default_factory=list)


class SpriteSpec(BaseModel):
    name: str
    is_stage: bool = False
    x: float = 0.0
    y: float = 0.0
    size: float = 100.0
    visible: bool = True
    costumes: List[CostumeSpec] = Field(default_factory=list)
    scripts: List[ScriptSpec] = Field(default_factory=list)


class VariableSpec(BaseModel):
    name: str
    initial_value: Any = 0


class ListSpec(BaseModel):
    name: str
    items: List[Any] = Field(default_factory=list)


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


def validate_project_spec(data: Dict[str, Any]) -> ProjectSpec:
    project = ProjectSpec.model_validate(data)
    for target in project.targets:
        for script in target.scripts:
            def _check_blocks(blocks: List[BlockSpec]):
                for block in blocks:
                    if block.opcode not in ALLOWED_OPCODES:
                        raise ValueError(f"許可されていないopcodeです: {block.opcode}")
                    for substack in block.substacks:
                        _check_blocks(substack)
            _check_blocks(script.blocks)
    return project