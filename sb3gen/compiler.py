"""
sb3gen/compiler.py
高レベル ProjectSpec から Scratch 3.0 の sb3（プロジェクトJSON）へのコンパイル層。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .assets import AssetRegistry, register_default_backdrop
from .schema import ProjectSpec, SpriteSpec, BlockSpec, ScriptSpec, CostumeSpec, ALLOWED_OPCODES

BLOCK_DEFS: Dict[str, Dict[str, Any]] = {
    "motion_movesteps": {"inputs": ["STEPS"], "substacks": []},
    "motion_turnright": {"inputs": ["DEGREES"], "substacks": []},
    "motion_turnleft": {"inputs": ["DEGREES"], "substacks": []},
    "motion_goto": {"inputs": ["TO"], "substacks": []},
    "motion_gotoxy": {"inputs": ["X", "Y"], "substacks": []},
    "motion_glideto": {"fields": ["SECS"], "inputs": ["SECS", "TO"], "substacks": []},
    "motion_glidesecstoxy": {"inputs": ["SECS", "X", "Y"], "substacks": []},
    "motion_pointindirection": {"inputs": ["DIRECTION"], "substacks": []},
    "motion_pointtowards": {"inputs": ["TOWARDS"], "substacks": []},
    "motion_changexby": {"inputs": ["DX"], "substacks": []},
    "motion_setx": {"inputs": ["X"], "substacks": []},
    "motion_changeyby": {"inputs": ["DY"], "substacks": []},
    "motion_sety": {"inputs": ["Y"], "substacks": []},
    "motion_ifonedgebounce": {"inputs": [], "substacks": []},
    "motion_setrotationstyle": {"fields": ["STYLE"], "inputs": [], "substacks": []},
    "motion_xposition": {"inputs": [], "substacks": []},
    "motion_yposition": {"inputs": [], "substacks": []},
    "motion_direction": {"inputs": [], "substacks": []},

    "looks_sayforsecs": {"inputs": ["MESSAGE", "SECS"], "substacks": []},
    "looks_say": {"inputs": ["MESSAGE"], "substacks": []},
    "looks_thinkforsecs": {"inputs": ["MESSAGE", "SECS"], "substacks": []},
    "looks_think": {"inputs": ["MESSAGE"], "substacks": []},
    "looks_switchcostumeto": {"inputs": ["COSTUME"], "substacks": []},
    "looks_nextcostume": {"inputs": [], "substacks": []},
    "looks_switchbackdropto": {"inputs": ["BACKDROP"], "substacks": []},
    "looks_changesizeby": {"inputs": ["CHANGE"], "substacks": []},
    "looks_setsizeto": {"inputs": ["SIZE"], "substacks": []},
    "looks_changeeffectby": {"fields": ["EFFECT"], "inputs": ["CHANGE"], "substacks": []},
    "looks_seteffectto": {"fields": ["EFFECT"], "inputs": ["VALUE"], "substacks": []},
    "looks_cleargraphiceffects": {"inputs": [], "substacks": []},
    "looks_show": {"inputs": [], "substacks": []},
    "looks_hide": {"inputs": [], "substacks": []},
    "looks_gotofrontback": {"fields": ["FRONT_BACK"], "inputs": [], "substacks": []},
    "looks_goforwardbackwardlayers": {"fields": ["FORWARD_BACKWARD"], "inputs": ["NUM"], "substacks": []},
    "looks_costumenumbername": {"fields": ["NUMBER_NAME"], "inputs": [], "substacks": []},
    "looks_backdropnumbername": {"fields": ["NUMBER_NAME"], "inputs": [], "substacks": []},
    "looks_size": {"inputs": [], "substacks": []},

    "sound_play": {"inputs": ["SOUND_MENU"], "substacks": []},
    "sound_playuntildone": {"inputs": ["SOUND_MENU"], "substacks": []},
    "sound_stopallsounds": {"inputs": [], "substacks": []},
    "sound_changeeffectby": {"fields": ["EFFECT"], "inputs": ["VALUE"], "substacks": []},
    "sound_seteffectto": {"fields": ["EFFECT"], "inputs": ["VALUE"], "substacks": []},
    "sound_cleareffects": {"inputs": [], "substacks": []},
    "sound_changevolumeby": {"inputs": ["VOLUME"], "substacks": []},
    "sound_setvolumeto": {"inputs": ["VOLUME"], "substacks": []},
    "sound_volume": {"inputs": [], "substacks": []},

    "event_whenflagclicked": {"inputs": [], "substacks": []},
    "event_whenkeypressed": {"fields": ["KEY_OPTION"], "inputs": [], "substacks": []},
    "event_whenthisspriteclicked": {"inputs": [], "substacks": []},
    "event_whenbackdropswitchesto": {"fields": ["BACKDROP"], "inputs": [], "substacks": []},
    "event_whengreaterthan": {"fields": ["WHATEVER"], "inputs": ["VALUE"], "substacks": []},
    "event_broadcast": {"inputs": ["BROADCAST_INPUT"], "substacks": []},
    "event_broadcastandwait": {"inputs": ["BROADCAST_INPUT"], "substacks": []},
    "event_whenbroadcastreceived": {"fields": ["BROADCAST_OPTION"], "inputs": [], "substacks": []},

    "control_wait": {"inputs": ["DURATION"], "substacks": []},
    "control_repeat": {"inputs": ["TIMES"], "substacks": ["SUBSTACK"]},
    "control_forever": {"inputs": [], "substacks": ["SUBSTACK"]},
    "control_if": {"inputs": ["CONDITION"], "substacks": ["SUBSTACK"]},
    "control_if_else": {"inputs": ["CONDITION"], "substacks": ["SUBSTACK", "SUBSTACK2"]},
    "control_wait_until": {"inputs": ["CONDITION"], "substacks": []},
    "control_repeat_until": {"inputs": ["CONDITION"], "substacks": ["SUBSTACK"]},
    "control_stop": {"fields": ["STOP_OPTION"], "inputs": [], "substacks": []},
    "control_start_as_clone": {"inputs": [], "substacks": []},
    "control_create_clone_of": {"inputs": ["CLONE_OPTION"], "substacks": []},
    "control_delete_this_clone": {"inputs": [], "substacks": []},

    "sensing_touchingobject": {"inputs": ["TOUCHINGOBJECTMENU"], "substacks": []},
    "sensing_touchingcolor": {"inputs": ["COLOR"], "substacks": []},
    "sensing_coloristouchingcolor": {"inputs": ["COLOR", "COLOR2"], "substacks": []},
    "sensing_distanceto": {"inputs": ["DISTANCETOMENU"], "substacks": []},
    "sensing_askandwait": {"inputs": ["QUESTION"], "substacks": []},
    "sensing_answer": {"inputs": [], "substacks": []},
    "sensing_keypressed": {"inputs": ["KEY_OPTION"], "inputs": [], "substacks": []},
    "sensing_mousedown": {"inputs": [], "substacks": []},
    "sensing_mousex": {"inputs": [], "substacks": []},
    "sensing_mousey": {"inputs": [], "substacks": []},
    "sensing_setdragmode": {"fields": ["DRAG_MODE"], "inputs": [], "substacks": []},
    "sensing_loudness": {"inputs": [], "substacks": []},
    "sensing_timer": {"inputs": [], "substacks": []},
    "sensing_resettimer": {"inputs": [], "substacks": []},
    "sensing_of": {"fields": ["PROPERTY"], "inputs": ["OBJECT"], "substacks": []},
    "sensing_current": {"fields": ["CURRENTMENU"], "inputs": [], "substacks": []},
    "sensing_dayssince2000": {"inputs": [], "substacks": []},
    "sensing_username": {"inputs": [], "substacks": []},

    "operator_add": {"inputs": ["NUM1", "NUM2"], "substacks": []},
    "operator_subtract": {"inputs": ["NUM1", "NUM2"], "substacks": []},
    "operator_multiply": {"inputs": ["NUM1", "NUM2"], "substacks": []},
    "operator_divide": {"inputs": ["NUM1", "NUM2"], "substacks": []},
    "operator_random": {"inputs": ["FROM", "TO"], "substacks": []},
    "operator_gt": {"inputs": ["OPERAND1", "OPERAND2"], "substacks": []},
    "operator_lt": {"inputs": ["OPERAND1", "OPERAND2"], "substacks": []},
    "operator_equals": {"inputs": ["OPERAND1", "OPERAND2"], "substacks": []},
    "operator_and": {"inputs": ["OPERAND1", "OPERAND2"], "substacks": []},
    "operator_or": {"inputs": ["OPERAND1", "OPERAND2"], "substacks": []},
    "operator_not": {"inputs": ["OPERAND1"], "substacks": []},
    "operator_join": {"inputs": ["STRING1", "STRING2"], "substacks": []},
    "operator_letter_of": {"inputs": ["LETTER", "STRING"], "substacks": []},
    "operator_length": {"inputs": ["STRING"], "substacks": []},
    "operator_mod": {"inputs": ["NUM1", "NUM2"], "substacks": []},
    "operator_round": {"inputs": ["NUM1"], "substacks": []},
    "operator_mathop": {"fields": ["OPERATOR"], "inputs": ["NUM"], "substacks": []},

    "data_variable": {"fields": ["VARIABLE"], "inputs": [], "substacks": []},
    "data_setvariableto": {"fields": ["VARIABLE"], "inputs": ["VALUE"], "substacks": []},
    "data_changevariableby": {"fields": ["VARIABLE"], "inputs": ["VALUE"], "substacks": []},
    "data_showvariable": {"fields": ["VARIABLE"], "inputs": [], "substacks": []},
    "data_hidevariable": {"fields": ["VARIABLE"], "inputs": [], "substacks": []},
    "data_listcontents": {"fields": ["LIST"], "inputs": [], "substacks": []},
    "data_addtolist": {"fields": ["LIST"], "inputs": ["ITEM"], "substacks": []},
    "data_deleteoflist": {"fields": ["LIST"], "inputs": ["INDEX"], "substacks": []},
    "data_deletealloflist": {"fields": ["LIST"], "inputs": [], "substacks": []},
    "data_insertatlist": {"fields": ["LIST"], "inputs": ["ITEM", "INDEX"], "substacks": []},
    "data_replaceitemoflist": {"fields": ["LIST"], "inputs": ["ITEM", "INDEX"], "substacks": []},
    "data_itemoflist": {"fields": ["LIST"], "inputs": ["INDEX"], "substacks": []},
    "data_itemnumoflist": {"fields": ["LIST"], "inputs": ["ITEM"], "substacks": []},
    "data_lengthoflist": {"fields": ["LIST"], "inputs": [], "substacks": []},
    "data_listcontainsitem": {"fields": ["LIST"], "inputs": ["ITEM"], "substacks": []},
    "data_showlist": {"fields": ["LIST"], "inputs": ["VALUE"], "substacks": []},
    "data_hidelist": {"fields": ["LIST"], "inputs": [], "substacks": []},
}


class CompileContext:
    def __init__(self, project: ProjectSpec):
        self.project = project
        self.variable_ids: Dict[str, str] = {v.name: uuid.uuid4().hex[:20] for v in project.variables}
        self.list_ids: Dict[str, str] = {l.name: uuid.uuid4().hex[:20] for l in project.lists}
        self.broadcast_ids: Dict[str, str] = {b.name: uuid.uuid4().hex[:20] for b in project.broadcasts}

    def resolve_variable(self, name: str) -> str:
        if name not in self.variable_ids:
            self.variable_ids[name] = uuid.uuid4().hex[:20]
        return self.variable_ids[name]

    def resolve_list(self, name: str) -> str:
        if name not in self.list_ids:
            self.list_ids[name] = uuid.uuid4().hex[:20]
        return self.list_ids[name]

    def resolve_broadcast(self, name: str) -> str:
        if name not in self.broadcast_ids:
            self.broadcast_ids[name] = uuid.uuid4().hex[:20]
        return self.broadcast_ids[name]


def generate_id() -> str:
    return uuid.uuid4().hex[:20]


def _compile_node(
    block: BlockSpec,
    blocks_out: Dict[str, Any],
    ctx: CompileContext,
    parent_id: Optional[str] = None,
    next_id: Optional[str] = None,
) -> str:
    if block.opcode not in ALLOWED_OPCODES:
        raise ValueError(f"許可されていないopcodeです: {block.opcode}")

    block_id = generate_id()
    
    # fieldsの解決（変数、リスト、ブロードキャストのID紐付け）
    compiled_fields = dict(block.fields)
    if block.opcode in {"data_variable", "data_setvariableto", "data_changevariableby", "data_showvariable", "data_hidevariable"}:
        if "VARIABLE" in compiled_fields:
            var_name = compiled_fields["VARIABLE"]
            if isinstance(var_name, list):
                var_name = var_name[0]
            var_id = ctx.resolve_variable(str(var_name))
            compiled_fields["VARIABLE"] = [str(var_name), var_id]
    elif block.opcode in {"data_listcontents", "data_addtolist", "data_deleteoflist", "data_deletealloflist", "data_insertatlist", "data_replaceitemoflist", "data_itemoflist", "data_itemnumoflist", "data_lengthoflist", "data_listcontainsitem", "data_showlist", "data_hidelist"}:
        if "LIST" in compiled_fields:
            list_name = compiled_fields["LIST"]
            if isinstance(list_name, list):
                list_name = list_name[0]
            list_id = ctx.resolve_list(str(list_name))
            compiled_fields["LIST"] = [str(list_name), list_id]
    elif block.opcode in {"event_broadcast", "event_broadcastandwait"}:
        if "BROADCAST_INPUT" in compiled_fields:
            b_name = compiled_fields["BROADCAST_INPUT"]
            if isinstance(b_name, list):
                b_name = b_name[0]
            b_id = ctx.resolve_broadcast(str(b_name))
            compiled_fields["BROADCAST_INPUT"] = [str(b_name), b_id]
    elif block.opcode == "event_whenbroadcastreceived":
        if "BROADCAST_OPTION" in compiled_fields:
            b_name = compiled_fields["BROADCAST_OPTION"]
            if isinstance(b_name, list):
                b_name = b_name[0]
            b_id = ctx.resolve_broadcast(str(b_name))
            compiled_fields["BROADCAST_OPTION"] = [str(b_name), b_id]

    # inputsのコンパイル（ネストしたBlockSpecや辞書、プリミティブ値の処理）
    compiled_inputs: Dict[str, Any] = {}
    for input_name, val in block.inputs.items():
        sub_block_spec = None
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], BlockSpec):
            sub_block_spec = val[0]
        elif isinstance(val, BlockSpec):
            sub_block_spec = val
        elif isinstance(val, dict) and "opcode" in val:
            try:
                sub_block_spec = BlockSpec.model_validate(val)
            except Exception:
                pass

        if sub_block_spec is not None:
            sub_id = _compile_node(sub_block_spec, blocks_out, ctx, parent_id=block_id)
            compiled_inputs[input_name] = [1, sub_id]
        else:
            shadow_id = generate_id()
            val_str = str(val[0] if isinstance(val, list) and len(val) > 0 else val)
            compiled_inputs[input_name] = [1, shadow_id]
            blocks_out[shadow_id] = {
                "opcode": "text",
                "next": None,
                "parent": block_id,
                "inputs": {},
                "fields": {"TEXT": [val_str, None]},
                "shadow": True,
                "topLevel": False
            }

    # substacksの処理
    for i, substack in enumerate(block.substacks):
        substack_key = f"SUBSTACK{i+1}" if i > 0 else "SUBSTACK"
        if substack:
            first_sub_id = None
            prev_sub_id = None
            for idx, sub_block in enumerate(substack):
                is_last_sub = (idx == len(substack) - 1)
                sub_next_id = None if is_last_sub else "PENDING"
                s_id = _compile_node(sub_block, blocks_out, ctx, parent_id=(prev_sub_id or block_id), next_id=sub_next_id)
                if first_sub_id is None:
                    first_sub_id = s_id
                if prev_sub_id is not None:
                    blocks_out[prev_sub_id]["next"] = s_id
                prev_sub_id = s_id
            if first_sub_id:
                compiled_inputs[substack_key] = [2, first_sub_id]
        else:
            compiled_inputs[substack_key] = [2, None]

    blocks_out[block_id] = {
        "opcode": block.opcode,
        "next": next_id,
        "parent": parent_id,
        "inputs": compiled_inputs,
        "fields": compiled_fields,
        "shadow": False,
        "topLevel": (parent_id is None and next_id != "PENDING")
    }
    return block_id


def compile_script(script: ScriptSpec, blocks_out: Dict[str, Any], ctx: CompileContext) -> Optional[str]:
    if not script.blocks:
        return None
    
    first_id = None
    prev_id = None
    for idx, block in enumerate(script.blocks):
        is_last = (idx == len(script.blocks) - 1)
        b_id = _compile_node(block, blocks_out, ctx, parent_id=prev_id, next_id=None)
        if first_id is None:
            first_id = b_id
        if prev_id is not None:
            blocks_out[prev_id]["next"] = b_id
        prev_id = b_id
        
    if first_id:
        blocks_out[first_id]["topLevel"] = True
        blocks_out[first_id]["parent"] = None
    return first_id


def compile_sprite(sprite: SpriteSpec, ctx: CompileContext) -> Dict[str, Any]:
    blocks_out: Dict[str, Any] = {}
    for script in sprite.scripts:
        compile_script(script, blocks_out, ctx)

    costumes_out = []
    for c in sprite.costumes:
        costumes_out.append({
            "name": c.name,
            "bitmapResolution": c.bitmap_resolution,
            "dataFormat": c.data_format,
            "assetId": c.asset_id or uuid.uuid4().hex,
            "md5ext": c.md5ext or f"{uuid.uuid4().hex}.{c.data_format}"
        })

    return {
        "isStage": sprite.is_stage,
        "name": sprite.name,
        "variables": {},
        "lists": {},
        "broadcasts": {},
        "blocks": blocks_out,
        "comments": {},
        "currentCostume": 0,
        "costumes": costumes_out,
        "sounds": [],
        "volume": 100,
        "layerOrder": 1 if not sprite.is_stage else 0,
        "visible": sprite.visible,
        "x": sprite.x,
        "y": sprite.y,
        "size": sprite.size,
        "direction": 90,
        "draggable": False,
        "rotationStyle": "all around"
    }


def compile_project(project: ProjectSpec, registry: Optional[AssetRegistry] = None) -> Dict[str, Any]:
    # Stageターゲットがなければ先頭に自動生成する。
    # 背景はregister_default_backdropで実際にレジストリに登録してからassetIdを得る
    # （以前は未登録の固定assetIdを使い回していたため、writerで常に
    # プレースホルダーにフォールバックしていた）。
    targets = list(project.targets)
    if not any(t.is_stage for t in targets):
        backdrop = register_default_backdrop(registry)
        stage_spec = SpriteSpec(name="Stage", is_stage=True, costumes=[backdrop])
        targets.insert(0, stage_spec)
        project = project.model_copy(update={"targets": targets})

    ctx = CompileContext(project)
    targets_out = []
    for sprite in project.targets:
        targets_out.append(compile_sprite(sprite, ctx))

    variable_defaults = {v.name: v.initial_value for v in project.variables}
    list_defaults = {l.name: l.items for l in project.lists}

    variables_out = {
        v_id: [name, variable_defaults.get(name, 0)]
        for name, v_id in ctx.variable_ids.items()
    }
    lists_out = {
        l_id: [name, list_defaults.get(name, [])]
        for name, l_id in ctx.list_ids.items()
    }
    broadcasts_out = {b_id: name for name, b_id in ctx.broadcast_ids.items()}

    # ステージターゲット（isStage=True）にグローバル変数、リスト、ブロードキャストを割り当てる
    for target in targets_out:
        if target["isStage"]:
            target["variables"] = variables_out
            target["lists"] = lists_out
            target["broadcasts"] = broadcasts_out
            break

    return {
        "targets": targets_out,
        "meta": {
            "semver": "3.0.0",
            "vm": "0.2.0",
            "agent": "Mozilla/5.0"
        }
    }