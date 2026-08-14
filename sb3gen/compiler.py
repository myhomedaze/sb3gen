"""
sb3gen/compiler.py
高レベル ProjectSpec から Scratch 3.0 の sb3（プロジェクトJSON）へのコンパイル層。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .assets import AssetRegistry, register_default_backdrop
from .schema import (
    ProjectSpec,
    SpriteSpec,
    BlockSpec,
    ScriptSpec,
    CostumeSpec,
    ALLOWED_OPCODES,
    ProcedureDefinitionSpec,
    extension_id_for_opcode,
)

BLOCK_DEFS: Dict[str, Dict[str, Any]] = {
    "motion_movesteps": {"inputs": ["STEPS"], "substacks": []},
    "motion_turnright": {"inputs": ["DEGREES"], "substacks": []},
    "motion_turnleft": {"inputs": ["DEGREES"], "substacks": []},
    "motion_goto": {"inputs": ["TO"], "substacks": []},
    "motion_gotoxy": {"inputs": ["X", "Y"], "substacks": []},
    "motion_glideto": {"inputs": ["SECS", "TO"], "substacks": []},
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
    "sensing_keypressed": {"inputs": ["KEY_OPTION"], "substacks": []},
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
    "data_showlist": {"fields": ["LIST"], "inputs": [], "substacks": []},
    "data_hidelist": {"fields": ["LIST"], "inputs": [], "substacks": []},
}

# 本来Scratchでドロップダウン入力（メニュー）であるべきinputの、opcodeごとの
# (専用メニューブロックのopcode, そのフィールド名) 対応表。
# これに列挙されていないinputは従来通り汎用の "text" シャドウにフォールバックする。
# VM実行上はどちらでも動くが、ここで本来のopcodeを使うことで、Scratchエディタで
# 開いた際の見た目・編集体験（ドロップダウン表示）が崩れないようにする。
MENU_INPUT_DEFS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "sensing_touchingobject": {"TOUCHINGOBJECTMENU": ("sensing_touchingobjectmenu", "TOUCHINGOBJECTMENU")},
    "sensing_distanceto": {"DISTANCETOMENU": ("sensing_distancetomenu", "DISTANCETOMENU")},
    "sensing_of": {"OBJECT": ("sensing_of_object_menu", "OBJECT")},
    "sound_play": {"SOUND_MENU": ("sound_sounds_menu", "SOUND_MENU")},
    "sound_playuntildone": {"SOUND_MENU": ("sound_sounds_menu", "SOUND_MENU")},
    "control_create_clone_of": {"CLONE_OPTION": ("control_create_clone_of_menu", "CLONE_OPTION")},
    "looks_switchcostumeto": {"COSTUME": ("looks_costume", "COSTUME")},
    "looks_switchbackdropto": {"BACKDROP": ("looks_backdrops", "BACKDROP")},
    "motion_pointtowards": {"TOWARDS": ("motion_pointtowards_menu", "TOWARDS")},
    "motion_goto": {"TO": ("motion_goto_menu", "TO")},
    "motion_glideto": {"TO": ("motion_glideto_menu", "TO")},
}


class CompileContext:
    def __init__(self, project: ProjectSpec):
        self.project = project
        self.variable_ids: Dict[str, str] = {v.name: uuid.uuid4().hex[:20] for v in project.variables}
        self.list_ids: Dict[str, str] = {l.name: uuid.uuid4().hex[:20] for l in project.lists}
        self.broadcast_ids: Dict[str, str] = {b.name: uuid.uuid4().hex[:20] for b in project.broadcasts}
        # スプライトごとのローカル変数IDテーブル（スプライト名 -> {変数名: ID}）
        self._local_variable_ids: Dict[str, Dict[str, str]] = {}
        self._active_sprite_name: Optional[str] = None
        # 現在コンパイル中のターゲットが持つカスタムブロック定義（名前 -> 定義）。
        # procedures_call の mutation を組み立てる際に proc_name から引く（1番: カスタムブロック）。
        self._active_procedures: Dict[str, ProcedureDefinitionSpec] = {}
        # プロジェクト全体を通して実際に使用された拡張機能ID（2番: 拡張機能）。
        # _compile_node でopcodeをコンパイルするたびに extension_id_for_opcode で判定し追加する。
        # 最終的に compile_project が project.json トップレベルの "extensions" 配列として書き出す。
        self.extensions: set[str] = set()

    def enter_sprite(self, sprite: "SpriteSpec") -> None:
        """これから compile_script するスプライトのスコープを設定する。
        ステージ（is_stage=True）の場合はローカルスコープなし（常にグローバル解決）。
        非ステージの場合は sprite.variables をこのスプライトのローカル変数として事前登録する。
        カスタムブロック定義（procedures）はステージ・スプライトどちらでも保持する。
        """
        self._active_procedures = {p.name: p for p in sprite.procedures}
        if sprite.is_stage:
            self._active_sprite_name = None
            return
        self._active_sprite_name = sprite.name
        if sprite.name not in self._local_variable_ids:
            self._local_variable_ids[sprite.name] = {
                v.name: uuid.uuid4().hex[:20] for v in sprite.variables
            }

    def lookup_procedure(self, proc_name: str) -> Optional[ProcedureDefinitionSpec]:
        return self._active_procedures.get(proc_name)

    def local_variables_for(self, sprite_name: str) -> Dict[str, str]:
        return self._local_variable_ids.get(sprite_name, {})

    def resolve_variable(self, name: str) -> str:
        """変数名からIDを解決する。現在アクティブなスプライトのローカル変数を優先し、
        見つからなければグローバル変数を検索（未登録ならグローバルとして新規作成）する。"""
        if self._active_sprite_name is not None:
            local_map = self._local_variable_ids.setdefault(self._active_sprite_name, {})
            if name in local_map:
                return local_map[name]
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


def _build_mutation(proc: ProcedureDefinitionSpec) -> Dict[str, Any]:
    """ProcedureDefinitionSpec から、procedures_definition/procedures_prototype/
    procedures_call が共通で持つ mutation 構造（proccode・引数id/名前/既定値・warp）を組み立てる（1番）。

    引数IDには ProcedureArgumentSpec.name をそのまま使う。schema.validate_project_spec で
    同一カスタムブロック内の引数名の重複はすでに禁止されているため、id としても一意性が保たれる。
    これにより呼び出し側（procedures_call の BlockSpec.inputs）は引数名をキーにするだけでよく、
    内部的な argument id を別途意識する必要がない。
    """
    arg_ids = [a.name for a in proc.arguments]
    arg_defaults: List[str] = []
    for a in proc.arguments:
        if a.type == "boolean":
            # ScratchのVMはargumentdefaultsの文字列をJS的な真偽判定で扱うため、
            # 空でない文字列は全てtruthyになる。str(False) は "False"（大文字・非空）
            # になってしまい、意図した既定値falseがtrue扱いされてしまうバグがあったため、
            # 必ず小文字の "true"/"false" に正規化する。
            default_bool = bool(a.default) if a.default is not None else False
            arg_defaults.append("true" if default_bool else "false")
        elif a.default is not None:
            arg_defaults.append(str(a.default))
        else:
            arg_defaults.append("")
    return {
        "tagName": "mutation",
        "children": [],
        "proccode": proc.proccode,
        "argumentids": json.dumps(arg_ids, ensure_ascii=False),
        "argumentnames": json.dumps(arg_ids, ensure_ascii=False),
        "argumentdefaults": json.dumps(arg_defaults, ensure_ascii=False),
        "warp": "true" if proc.warp else "false",
    }


def _compile_node(
    block: BlockSpec,
    blocks_out: Dict[str, Any],
    ctx: CompileContext,
    parent_id: Optional[str] = None,
    next_id: Optional[str] = None,
) -> str:
    if block.opcode not in ALLOWED_OPCODES:
        raise ValueError(f"許可されていないopcodeです: {block.opcode}")

    # BLOCK_DEFSに定義された必須inputs/fieldsが揃っているか検証する。
    # ここを通さないと、LLMが必須inputを一つ落として出力してもコンパイルはエラーにならず
    # 「動かないブロック」がそのままsb3に出力されてしまうため、procedures_callの
    # 未定義チェックと同様に、ここで明示的に失敗させる。
    block_def = BLOCK_DEFS.get(block.opcode)
    if block_def is not None:
        missing_inputs = [
            name for name in block_def.get("inputs", []) if name not in block.inputs
        ]
        missing_fields = [
            name for name in block_def.get("fields", []) if name not in block.fields
        ]
        if missing_inputs or missing_fields:
            details = []
            if missing_inputs:
                details.append(f"不足inputs={missing_inputs}")
            if missing_fields:
                details.append(f"不足fields={missing_fields}")
            raise ValueError(
                f"ブロック '{block.opcode}' の定義が不完全です（{'; '.join(details)}）"
            )

    block_id = generate_id()

    # このopcodeが拡張機能（ペン・音楽等）のブロックであれば、プロジェクト全体の
    # 使用済み拡張機能セットに登録する（2番: 拡張機能）。
    ext_id = extension_id_for_opcode(block.opcode)
    if ext_id:
        ctx.extensions.add(ext_id)

    # procedures_call ブロックの場合、対象のカスタムブロック定義から mutation
    # （proccode・argumentids・argumentnames・argumentdefaults・warp）を組み立てる（1番）。
    # schema.validate_project_spec で proc_name の存在チェック済みだが、コンパイル単体で
    # 呼ばれるケースも考慮し、ここでも未定義なら明示的にエラーにする。
    call_mutation: Optional[Dict[str, Any]] = None
    if block.opcode == "procedures_call":
        proc = ctx.lookup_procedure(block.proc_name) if block.proc_name else None
        if proc is None:
            raise ValueError(f"未定義のカスタムブロックを呼び出しています: {block.proc_name}")
        call_mutation = _build_mutation(proc)

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
    elif block.opcode in {"argument_reporter_string_number", "argument_reporter_boolean"}:
        # カスタムブロック本体内で引数を参照するレポーター（1番）。
        # LLM/呼び出し側が "VALUE": "引数名" のように素の文字列で渡してきても、
        # Scratchが期待する [引数名, null] 形式に正規化する。
        if "VALUE" in compiled_fields:
            v = compiled_fields["VALUE"]
            if isinstance(v, list):
                compiled_fields["VALUE"] = [str(v[0]) if v else "", None]
            else:
                compiled_fields["VALUE"] = [str(v), None]

    # 上記で特別扱いした以外のfields（STOP_OPTION、KEY_OPTION、EFFECT、STYLE、
    # FRONT_BACK、NUMBER_NAME、DRAG_MODE、PROPERTY、CURRENTMENU、OPERATOR、WHATEVER等）は
    # この時点でまだ素の値（例: "all"）のまま。しかし実際のScratchのsb3形式では、
    # すべてのfieldsは例外なく [値, idまたはnull] の2要素配列である必要があり、
    # 素の文字列のままなとScratchのデシリアライザが fieldJSON[0] を文字列の
    # インデックスとして解釈してしまい（例: "all"[0] == "a"）、値が壊れる重大なバグがあった。
    # ここで残り全てのfieldsを [値, null] 形式へ一律に正規化する（既に上記で
    # [値, id] 化済みのものは影響を受けない）。
    for _fkey, _fval in list(compiled_fields.items()):
        if isinstance(_fval, list):
            if len(_fval) == 0:
                compiled_fields[_fkey] = [None, None]
            elif len(_fval) == 1:
                compiled_fields[_fkey] = [_fval[0], None]
            # 2要素以上はすでに [値, id] 形式なのでそのまま
        else:
            compiled_fields[_fkey] = [_fval, None]
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
            raw_val = val[0] if isinstance(val, list) and len(val) > 0 else val
            if isinstance(raw_val, bool):
                # str(False) は "False"（大文字・非空文字列）になり、Scratch VM側の
                # JS的な真偽判定では非空文字列は全てtruthyになるため、意図したfalseが
                # true扱いされてしまう。_build_mutationの既定値と同様に小文字へ正規化する。
                val_str = "true" if raw_val else "false"
            else:
                val_str = str(raw_val)
            compiled_inputs[input_name] = [1, shadow_id]

            menu_def = MENU_INPUT_DEFS.get(block.opcode, {}).get(input_name)
            if menu_def is not None:
                # 本来ドロップダウン（メニュー）であるべきinputは、専用メニューopcodeの
                # シャドウブロックとして出力する（fieldsに値を持たせる。TEXTのinputは持たない）。
                # これによりScratchエディタで開いた際もドロップダウンとして正しく表示される。
                menu_opcode, field_name = menu_def
                blocks_out[shadow_id] = {
                    "opcode": menu_opcode,
                    "next": None,
                    "parent": block_id,
                    "inputs": {},
                    "fields": {field_name: [val_str, None]},
                    "shadow": True,
                    "topLevel": False
                }
            else:
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

    compiled_block: Dict[str, Any] = {
        "opcode": block.opcode,
        "next": next_id,
        "parent": parent_id,
        "inputs": compiled_inputs,
        "fields": compiled_fields,
        "shadow": False,
        "topLevel": (parent_id is None and next_id != "PENDING")
    }
    if call_mutation is not None:
        compiled_block["mutation"] = call_mutation
    blocks_out[block_id] = compiled_block
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


def _compile_procedure(proc: ProcedureDefinitionSpec, blocks_out: Dict[str, Any], ctx: CompileContext) -> None:
    """ProcedureDefinitionSpec（カスタムブロック宣言）を、Scratchが読み込める
    procedures_definition（hatブロック）+ procedures_prototype（隠しshadowブロック）+
    各引数の argument_reporter_* ブロック + 本体スクリプトへとコンパイルする（1番: カスタムブロック）。

    procedures_prototype の inputs は、各引数idをキーに argument_reporter ブロックを
    shadowとして参照する（Scratch側の「マイブロックの定義」パレット表示に必要）。
    本体スクリプトは procedures_definition の next として連結する。
    """
    mutation = _build_mutation(proc)

    prototype_id = generate_id()
    definition_id = generate_id()

    prototype_inputs: Dict[str, Any] = {}
    for arg in proc.arguments:
        reporter_id = generate_id()
        reporter_opcode = (
            "argument_reporter_boolean" if arg.type == "boolean" else "argument_reporter_string_number"
        )
        blocks_out[reporter_id] = {
            "opcode": reporter_opcode,
            "next": None,
            "parent": prototype_id,
            "inputs": {},
            "fields": {"VALUE": [arg.name, None]},
            "shadow": True,
            "topLevel": False,
        }
        prototype_inputs[arg.name] = [1, reporter_id]

    blocks_out[prototype_id] = {
        "opcode": "procedures_prototype",
        "next": None,
        "parent": definition_id,
        "inputs": prototype_inputs,
        "fields": {},
        "mutation": mutation,
        "shadow": True,
        "topLevel": False,
    }

    # 本体スクリプトをコンパイルし、definitionブロックの next として連結する。
    # compile_scriptは先頭ブロックをtopLevel=True・parent=Noneにするため、
    # ここで本体の先頭ブロックのparent/topLevelをdefinitionブロックの子として上書きする。
    first_body_id = compile_script(ScriptSpec(blocks=proc.body), blocks_out, ctx)
    if first_body_id is not None:
        blocks_out[first_body_id]["parent"] = definition_id
        blocks_out[first_body_id]["topLevel"] = False

    blocks_out[definition_id] = {
        "opcode": "procedures_definition",
        "next": first_body_id,
        "parent": None,
        "inputs": {"custom_block": [1, prototype_id]},
        "fields": {},
        "shadow": False,
        "topLevel": True,
    }


def compile_sprite(sprite: SpriteSpec, ctx: CompileContext, layer_order: int = 1) -> Dict[str, Any]:
    ctx.enter_sprite(sprite)

    blocks_out: Dict[str, Any] = {}
    for script in sprite.scripts:
        compile_script(script, blocks_out, ctx)

    # このターゲットが宣言しているカスタムブロック定義を、hatブロックから本体まで一括コンパイルする（1番）。
    for proc in sprite.procedures:
        _compile_procedure(proc, blocks_out, ctx)

    costumes_out = []
    for c in sprite.costumes:
        c_asset_id = c.asset_id or uuid.uuid4().hex
        costumes_out.append({
            "name": c.name,
            "bitmapResolution": c.bitmap_resolution,
            "dataFormat": c.data_format,
            "assetId": c_asset_id,
            "md5ext": c.md5ext or f"{c_asset_id}.{c.data_format}",
            "rotationCenterX": c.rotation_center_x if c.rotation_center_x is not None else 0,
            "rotationCenterY": c.rotation_center_y if c.rotation_center_y is not None else 0,
        })

    sounds_out = []
    for s in sprite.sounds:
        s_asset_id = s.asset_id or uuid.uuid4().hex
        sounds_out.append({
            "name": s.name,
            "dataFormat": s.data_format,
            "format": "",
            "assetId": s_asset_id,
            "md5ext": s.md5ext or f"{s_asset_id}.{s.data_format}",
            "rate": s.rate if s.rate is not None else 44100,
            "sampleCount": s.sample_count if s.sample_count is not None else 0,
        })

    # スプライトローカル変数を project.json の variables に書き出す（ステージは常に空。
    # グローバル変数は compile_project 側でステージターゲットに別途割り当てられる）。
    local_var_ids = ctx.local_variables_for(sprite.name) if not sprite.is_stage else {}
    local_var_defaults = {v.name: v.initial_value for v in sprite.variables}
    variables_out = {
        v_id: [name, local_var_defaults.get(name, 0)]
        for name, v_id in local_var_ids.items()
    }

    return {
        "isStage": sprite.is_stage,
        "name": sprite.name,
        "variables": variables_out,
        "lists": {},
        "broadcasts": {},
        "blocks": blocks_out,
        "comments": {},
        "currentCostume": 0,
        "costumes": costumes_out,
        "sounds": sounds_out,
        "volume": 100,
        "layerOrder": layer_order if not sprite.is_stage else 0,
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
    next_layer_order = 1
    for sprite in project.targets:
        if sprite.is_stage:
            targets_out.append(compile_sprite(sprite, ctx))
        else:
            targets_out.append(compile_sprite(sprite, ctx, layer_order=next_layer_order))
            next_layer_order += 1

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
        # 実際に使用された拡張機能IDのみを宣言する（2番: 拡張機能）。
        # これが無いと pen_*/music_* ブロックを含むプロジェクトはScratch上で
        # 拡張機能未ロードのままになり、対応ブロックが正しく表示・実行されない。
        "extensions": sorted(ctx.extensions),
        "meta": {
            "semver": "3.0.0",
            "vm": "0.2.0",
            "agent": "Mozilla/5.0"
        }
    }