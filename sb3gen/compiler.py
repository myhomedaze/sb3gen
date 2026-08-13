"""
sb3gen/compiler.py
BlockSpec の入れ子構造を Scratch 3.0 のフラットなブロックマップ形式に変換し、
ランダムな ID を採番して parent/next/inputs を結線するコンパイラ層。
"""

from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    BlockSpec,
    ScriptSpec,
    SpriteSpec,
    ProjectSpec,
    VariableSpec,
    ListSpec,
    BroadcastSpec,
)


def generate_id(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))


BLOCK_DEFS: Dict[str, Dict[str, Any]] = {
    "event_whenflagclicked": {"fields": [], "inputs": [], "substacks": []},
    "control_forever": {"fields": [], "inputs": [], "substacks": ["SUBSTACK"]},
    "control_if": {"fields": [], "inputs": ["CONDITION"], "substacks": ["SUBSTACK"]},
    "control_repeat": {"fields": [], "inputs": ["TIMES"], "substacks": ["SUBSTACK"]},
    "motion_movesteps": {"fields": [], "inputs": ["STEPS"], "substacks": []},
    "motion_gotoxy": {"fields": [], "inputs": ["X", "Y"], "substacks": []},
    "looks_say": {"fields": [], "inputs": ["MESSAGE"], "substacks": []},
    "looks_switchcostume": {"fields": [], "inputs": ["COSTUME"], "substacks": []},
    "sound_play": {"fields": [], "inputs": ["SOUND_MENU"], "substacks": []},
    "data_setvariableto": {"fields": ["VARIABLE"], "inputs": ["VALUE"], "substacks": []},
    "data_changevariableby": {"fields": ["VARIABLE"], "inputs": ["VALUE"], "substacks": []},
    "operator_add": {"fields": [], "inputs": ["NUM1", "NUM2"], "substacks": []},
    "sensing_touchingobject": {"fields": [], "inputs": ["TOUCHINGOBJECTMENU"], "substacks": []},
}

BOOLEAN_LIKE_INPUTS = {"CONDITION"}


class CompileContext:
    def __init__(
        self,
        global_vars: Dict[str, str],
        global_lists: Dict[str, str],
        broadcasts: Dict[str, str],
        local_vars: Optional[Dict[str, str]] = None,
        local_lists: Optional[Dict[str, str]] = None,
    ):
        self.global_vars = global_vars
        self.global_lists = global_lists
        self.broadcasts = broadcasts
        self.local_vars = local_vars or {}
        self.local_lists = local_lists or {}

    def resolve_variable(self, name: str) -> str:
        if name in self.local_vars:
            return self.local_vars[name]
        if name in self.global_vars:
            return self.global_vars[name]
        raise ValueError(f"未定義の変数参照です: {name}")

    def resolve_list(self, name: str) -> str:
        if name in self.local_lists:
            return self.local_lists[name]
        if name in self.global_lists:
            return self.global_lists[name]
        raise ValueError(f"未定義のリスト参照です: {name}")

    def resolve_broadcast(self, name: str) -> str:
        if name in self.broadcasts:
            return self.broadcasts[name]
        raise ValueError(f"未定義のブロードキャスト参照です: {name}")


def build_name_id_maps(
    variables: List[VariableSpec], lists: List[ListSpec], broadcasts: List[BroadcastSpec]
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    var_map = {v.name: generate_id() for v in variables}
    list_map = {l.name: generate_id() for l in lists}
    bcast_map = {b.name: generate_id() for b in broadcasts}
    return var_map, list_map, bcast_map


def _make_shadow_block(value: Any, block_id: str, parent_id: str) -> Dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {
            block_id: {
                "opcode": "math_number",
                "next": None,
                "parent": parent_id,
                "inputs": {},
                "fields": {"NUM": [str(value)]},
                "shadow": True,
                "topLevel": False,
            }
        }
    return {
        block_id: {
            "opcode": "text",
            "next": None,
            "parent": parent_id,
            "inputs": {},
            "fields": {"TEXT": [str(value)]},
            "shadow": True,
            "topLevel": False,
        }
    }


def _resolve_field_value(field_key: str, raw_value: Any, context: CompileContext) -> List[Any]:
    if field_key == "VARIABLE":
        return [str(raw_value), context.resolve_variable(str(raw_value))]
    if field_key == "LIST":
        return [str(raw_value), context.resolve_list(str(raw_value))]
    if field_key == "BROADCAST_OPTION":
        return [str(raw_value), context.resolve_broadcast(str(raw_value))]
    return [str(raw_value), None]


def _compile_node(
    block: BlockSpec,
    context: CompileContext,
    blocks_out: Dict[str, Any],
    parent_id: Optional[str],
    next_sibling_id: Optional[str],
    forced_id: Optional[str] = None,
) -> str:
    block_id = forced_id or generate_id()
    block_def = BLOCK_DEFS.get(block.opcode)
    if block_def is None:
        raise ValueError(f"未定義のopcodeです: {block.opcode}")

    fields_out: Dict[str, Any] = {}
    for field_key in block_def["fields"]:
        raw_value = block.fields.get(field_key)
        if raw_value is None:
            raise ValueError(f"{block.opcode} の必須フィールド {field_key} がありません。")
        fields_out[field_key] = _resolve_field_value(field_key, raw_value, context)

    inputs_out: Dict[str, Any] = {}
    substack_keys = set(block_def["substacks"])
    for input_key in block_def["inputs"]:
        if input_key in substack_keys:
            continue
        raw_value = block.inputs.get(input_key)
        if raw_value is None:
            raise ValueError(f"{block.opcode} の必須入力 {input_key} がありません。")

        is_nested_block = isinstance(raw_value, BlockSpec) or (
            isinstance(raw_value, dict) and "opcode" in raw_value
        )
        if is_nested_block:
            nested_spec = raw_value if isinstance(raw_value, BlockSpec) else BlockSpec.model_validate(raw_value)
            nested_id = _compile_node(nested_spec, context, blocks_out, parent_id=block_id, next_sibling_id=None)
            input_type = 2 if input_key in BOOLEAN_LIKE_INPUTS else 3
            inputs_out[input_key] = [input_type, nested_id]
        else:
            shadow_id = generate_id()
            blocks_out.update(_make_shadow_block(raw_value, shadow_id, block_id))
            inputs_out[input_key] = [1, shadow_id]

    for i, substack_key in enumerate(block_def["substacks"]):
        if i >= len(block.substacks):
            continue
        sub_blocks = block.substacks[i]
        if not sub_blocks:
            continue
        first_id = compile_block_sequence(sub_blocks, context, blocks_out, parent_id=block_id)
        if first_id is not None:
            inputs_out[substack_key] = [2, first_id]

    blocks_out[block_id] = {
        "opcode": block.opcode,
        "next": next_sibling_id,
        "parent": parent_id,
        "inputs": inputs_out,
        "fields": fields_out,
        "shadow": False,
        "topLevel": parent_id is None,
    }
    if parent_id is None:
        blocks_out[block_id]["x"] = 0
        blocks_out[block_id]["y"] = 0

    return block_id


def compile_block_sequence(
    blocks: List[BlockSpec],
    context: CompileContext,
    blocks_out: Dict[str, Any],
    parent_id: Optional[str],
) -> Optional[str]:
    if not blocks:
        return None

    ids = [generate_id() for _ in blocks]
    for i, block in enumerate(blocks):
        this_parent = parent_id if i == 0 else ids[i - 1]
        next_id = ids[i + 1] if i + 1 < len(ids) else None
        _compile_node(block, context, blocks_out, this_parent, next_id, forced_id=ids[i])

    return ids[0]


def compile_script(script: ScriptSpec, context: CompileContext) -> Dict[str, Any]:
    blocks_out: Dict[str, Any] = {}
    compile_block_sequence(script.blocks, context, blocks_out, parent_id=None)
    return blocks_out


def compile_sprite(
    sprite: SpriteSpec,
    global_var_map: Dict[str, str],
    global_list_map: Dict[str, str],
    broadcast_map: Dict[str, str],
) -> Dict[str, Any]:
    local_var_map, local_list_map, _ = build_name_id_maps(sprite.variables, sprite.lists, [])
    context = CompileContext(
        global_vars=global_var_map,
        global_lists=global_list_map,
        broadcasts=broadcast_map,
        local_vars=local_var_map,
        local_lists=local_list_map,
    )

    all_blocks: Dict[str, Any] = {}
    for script in sprite.scripts:
        all_blocks.update(compile_script(script, context))

    def var_initial(name: str) -> Any:
        return next((v.initial_value for v in sprite.variables if v.name == name), 0)

    def list_items(name: str) -> List[Any]:
        return next((l.items for l in sprite.lists if l.name == name), [])

    return {
        "isStage": sprite.is_stage,
        "name": sprite.name,
        "variables": {vid: [name, var_initial(name)] for name, vid in local_var_map.items()},
        "lists": {lid: [name, list_items(name)] for name, lid in local_list_map.items()},
        "broadcasts": {},
        "blocks": all_blocks,
        "comments": {},
        "currentCostume": 0,
        "costumes": [
            {
                "name": c.name,
                "assetId": c.asset_id or "",
                "dataFormat": c.data_format,
                "md5ext": f"{c.asset_id}.{c.data_format}" if c.asset_id else "",
                "rotationCenterX": 0,
                "rotationCenterY": 0,
            }
            for c in sprite.costumes
        ],
        "sounds": [],
        "volume": 100,
        "visible": True,
        "x": sprite.x,
        "y": sprite.y,
        "size": 100,
        "direction": 90,
        "draggable": False,
        "rotationStyle": "all around",
    }


def compile_project(project: ProjectSpec) -> Dict[str, Any]:
    global_var_map, global_list_map, broadcast_map = build_name_id_maps(
        project.variables, project.lists, project.broadcasts
    )

    stage_sprite = next((s for s in project.sprites if s.is_stage), None)
    if stage_sprite is not None:
        stage_target = compile_sprite(stage_sprite, global_var_map, global_list_map, broadcast_map)
    else:
        stage_target = {
            "isStage": True,
            "name": "Stage",
            "variables": {},
            "lists": {},
            "broadcasts": {},
            "blocks": {},
            "comments": {},
            "currentCostume": 0,
            "costumes": [],
            "sounds": [],
            "volume": 100,
            "tempo": 60,
            "videoTransparency": 50,
            "videoState": "on",
            "textToSpeechLanguage": None,
        }

    stage_target["variables"] = {
        vid: [name, next((v.initial_value for v in project.variables if v.name == name), 0)]
        for name, vid in global_var_map.items()
    }
    stage_target["lists"] = {
        lid: [name, next((l.items for l in project.lists if l.name == name), [])]
        for name, lid in global_list_map.items()
    }
    stage_target["broadcasts"] = {bid: name for name, bid in broadcast_map.items()}
    stage_target["layerOrder"] = 0

    targets = [stage_target]
    layer = 1
    for sprite in project.sprites:
        if sprite.is_stage:
            continue
        target = compile_sprite(sprite, global_var_map, global_list_map, broadcast_map)
        target["layerOrder"] = layer
        layer += 1
        targets.append(target)

    return {
        "targets": targets,
        "monitors": [],
        "extensions": [],
        "meta": {
            "semver": "3.0.0",
            "vm": "0.2.0",
            "agent": "sb3gen",
        },
    }