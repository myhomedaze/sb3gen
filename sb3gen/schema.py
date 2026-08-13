"""
sb3gen/schema.py
Scratch 3.0 自動生成パイプラインの正本スキーマ定義および意味検証層。
"""

from __future__ import annotations
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

ALLOWED_OPCODES = {
    "event_whenflagclicked",
    "control_forever",
    "control_if",
    "control_repeat",
    "motion_movesteps",
    "motion_gotoxy",
    "looks_say",
    "looks_switchcostume",
    "sound_play",
    "data_setvariableto",
    "data_changevariableby",
    "operator_add",
    "sensing_touchingobject",
}


class VariableSpec(BaseModel):
    name: str = Field(description="変数名")
    initial_value: Any = Field(default=0, description="初期値")


class ListSpec(BaseModel):
    name: str = Field(description="リスト名")
    items: List[Any] = Field(default_factory=list, description="初期アイテム一覧")


class BroadcastSpec(BaseModel):
    name: str = Field(description="ブロードキャストメッセージ名")


class CostumeSpec(BaseModel):
    name: str = Field(description="コスチューム名")
    asset_id: Optional[str] = Field(default=None, description="アセットID")
    data_format: str = Field(default="svg", description="ファイル形式")


class BlockSpec(BaseModel):
    opcode: str = Field(description="Scratchのopcode")
    fields: Dict[str, Any] = Field(default_factory=dict, description="引数・フィールド")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="入力・レポーター接続")
    substacks: List[List[BlockSpec]] = Field(
        default_factory=list, description="if/foreverなどの入れ子ブロック群"
    )


class ScriptSpec(BaseModel):
    blocks: List[BlockSpec] = Field(default_factory=list, description="ブロックの直列リスト")


class SpriteSpec(BaseModel):
    name: str = Field(description="スプライト名")
    is_stage: bool = Field(default=False, description="ステージかどうか")
    x: float = Field(default=0.0, description="初期X座標")
    y: float = Field(default=0.0, description="初期Y座標")
    costumes: List[CostumeSpec] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(default_factory=list)
    lists: List[ListSpec] = Field(default_factory=list)
    scripts: List[ScriptSpec] = Field(default_factory=list)


class ProjectSpec(BaseModel):
    sprites: List[SpriteSpec] = Field(default_factory=list)
    variables: List[VariableSpec] = Field(default_factory=list)
    lists: List[ListSpec] = Field(default_factory=list)
    broadcasts: List[BroadcastSpec] = Field(default_factory=list)


def validate_project_spec(data: Dict[str, Any]) -> ProjectSpec:
    spec = ProjectSpec.model_validate(data)
    
    sprite_names = [s.name for s in spec.sprites]
    if len(sprite_names) != len(set(sprite_names)):
        raise ValueError("重複するスプライト名が存在します。")

    var_names = [v.name for v in spec.variables]
    if len(var_names) != len(set(var_names)):
        raise ValueError("重複するグローバル変数名が存在します。")

    def _validate_block(block: BlockSpec):
        if block.opcode not in ALLOWED_OPCODES:
            raise ValueError(f"未許可の opcode です: {block.opcode}")
        for sub_script in block.substacks:
            for sub_block in sub_script.blocks:
                _validate_block(sub_block)

    for sprite in spec.sprites:
        for script in sprite.scripts:
            for block in script.blocks:
                _validate_block(block)

    return spec