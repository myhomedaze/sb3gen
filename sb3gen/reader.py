"""
sb3gen/reader.py
既存の .sb3 ファイルを読み込み、高レベルの ProjectSpec へ逆変換（デコンパイル）する層。

対応範囲について:
    このモジュールは compiler.py が生成した .sb3（=このツール自身が過去に出力したもの）を
    読み込んで継続編集することを主目的としている。Scratchエディタ本体やその他のツールが
    出力した .sb3 は、本ツールが対応していないopcode（math_number等のネイティブshadow、
    ALLOWED_OPCODESに含まれない拡張ブロック等）を含む場合があり、その場合は
    validate_project_spec の検証で明示的に失敗する。これは「壊れたプロジェクトを
    それと気づかず書き出してしまう」事故を避けるための意図的な仕様。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .assets import AssetRecord, AssetRegistry, DEFAULT_REGISTRY
from .compiler import BLOCK_DEFS
from .schema import (
    BlockSpec,
    BroadcastSpec,
    CostumeSpec,
    ListSpec,
    ProcedureArgumentSpec,
    ProcedureArgumentType,
    ProcedureDefinitionSpec,
    ProjectSpec,
    ScriptSpec,
    SoundSpec,
    SpriteSpec,
    VariableSpec,
    validate_project_spec,
)


# ---------------------------------------------------------------------------
# ブロック木の逆変換（project.json の blocks 辞書 -> BlockSpec木）
# ---------------------------------------------------------------------------

def _reconstruct_proc_name(proccode: str, num_args: int) -> str:
    """proccode（例: "ジャンプ %s 回"）から、コンパイル時に使われた元の name を復元する。

    compiler.ProcedureDefinitionSpec.proccode は
    `name` に、引数ごとの "%s"/"%b" プレースホルダを空白区切りで連結したものなので、
    末尾から引数の個数分のトークンを取り除けば name に戻る。
    name自体に空白が含まれていても、プレースホルダ部分は末尾に固定個数付くだけなので
    問題なく復元できる（name中の空白は保持される）。
    """
    if num_args <= 0:
        return proccode
    tokens = proccode.split(" ")
    if len(tokens) > num_args:
        return " ".join(tokens[:-num_args])
    return proccode


def _build_proccode_to_name(blocks: Dict[str, Any]) -> Dict[str, str]:
    """あるターゲットのblocks辞書から、procedures_definition（topLevel）を全て走査し、
    proccode -> 元のカスタムブロック名 のマップを事前構築する。

    procedures_call ブロックの本体（同一ターゲット内の他のカスタムブロックを呼ぶ場合を含む）
    をパースする前に、このマップを先に完成させておく必要がある。
    """
    mapping: Dict[str, str] = {}
    for block in blocks.values():
        if block.get("opcode") != "procedures_definition" or not block.get("topLevel"):
            continue
        custom_block_input = (block.get("inputs") or {}).get("custom_block")
        if not isinstance(custom_block_input, list) or len(custom_block_input) < 2:
            continue
        prototype = blocks.get(custom_block_input[1])
        if prototype is None:
            continue
        mutation = prototype.get("mutation") or {}
        proccode = mutation.get("proccode", "")
        try:
            argument_ids = json.loads(mutation.get("argumentids", "[]"))
        except (json.JSONDecodeError, TypeError):
            argument_ids = []
        mapping[proccode] = _reconstruct_proc_name(proccode, len(argument_ids))
    return mapping


def _walk_chain(
    start_id: Optional[str],
    blocks: Dict[str, Any],
    proccode_to_name: Dict[str, str],
) -> List[BlockSpec]:
    """"next" ポインタで連結された最上位ブロック列を、先頭ブロックIDから順にたどって
    BlockSpecのリストへ変換する（1本のスクリプト本体、または1つのsubstackの中身に対応）。
    循環参照があっても無限ループしないよう、訪問済みIDは打ち切る。
    """
    result: List[BlockSpec] = []
    cur = start_id
    seen: set = set()
    while cur is not None and cur in blocks and cur not in seen:
        seen.add(cur)
        result.append(_parse_block(cur, blocks, proccode_to_name))
        cur = blocks[cur].get("next")
    return result


def _parse_block(
    block_id: str,
    blocks: Dict[str, Any],
    proccode_to_name: Dict[str, str],
) -> BlockSpec:
    b = blocks[block_id]
    opcode = b.get("opcode", "")

    # fields: project.json では常に [値, idまたはnull] の2要素配列。
    # BlockSpec.fields は値のみを保持する（compiler側がコンパイル時にID解決するため）。
    fields: Dict[str, Any] = {}
    for key, val in (b.get("fields") or {}).items():
        if isinstance(val, (list, tuple)) and len(val) > 0:
            fields[key] = val[0]
        else:
            fields[key] = val

    block_def = BLOCK_DEFS.get(opcode, {})
    substack_keys: List[str] = list(block_def.get("substacks", []))

    raw_inputs = b.get("inputs") or {}

    substacks: List[List[BlockSpec]] = []
    for key in substack_keys:
        val = raw_inputs.get(key)
        first_id = val[1] if isinstance(val, list) and len(val) > 1 else None
        substacks.append(_walk_chain(first_id, blocks, proccode_to_name))

    inputs: Dict[str, Any] = {}
    for key, val in raw_inputs.items():
        if key in substack_keys or key == "custom_block":
            continue
        if not isinstance(val, list) or len(val) < 2:
            continue
        ref = val[1]
        if ref is None or ref not in blocks:
            continue
        ref_block = blocks[ref]

        if ref_block.get("shadow"):
            rb_fields = ref_block.get("fields") or {}
            if ref_block.get("opcode") == "text" and "TEXT" in rb_fields:
                text_val = rb_fields["TEXT"]
                inputs[key] = text_val[0] if isinstance(text_val, list) else text_val
            elif len(rb_fields) == 1:
                # MENU_INPUT_DEFS系のドロップダウンメニュー shadow（フィールド1個のみ）。
                only_val = next(iter(rb_fields.values()))
                inputs[key] = only_val[0] if isinstance(only_val, list) else only_val
            else:
                # 想定外の shadow 構造。念のため通常ブロックとして再帰的にパースしておく。
                inputs[key] = _parse_block(ref, blocks, proccode_to_name)
        else:
            # 実ブロック（レポーター/ブーリアン式）への参照。ネストしたBlockSpecとして復元する。
            inputs[key] = _parse_block(ref, blocks, proccode_to_name)

    proc_name: Optional[str] = None
    if opcode == "procedures_call":
        mutation = b.get("mutation") or {}
        proccode = mutation.get("proccode", "")
        proc_name = proccode_to_name.get(proccode, proccode)

    return BlockSpec(
        opcode=opcode,
        fields=fields,
        inputs=inputs,
        substacks=substacks,
        proc_name=proc_name,
    )


def _parse_procedures(
    blocks: Dict[str, Any],
    proccode_to_name: Dict[str, str],
) -> List[ProcedureDefinitionSpec]:
    procedures: List[ProcedureDefinitionSpec] = []

    for block in blocks.values():
        if block.get("opcode") != "procedures_definition" or not block.get("topLevel"):
            continue

        custom_block_input = (block.get("inputs") or {}).get("custom_block")
        if not isinstance(custom_block_input, list) or len(custom_block_input) < 2:
            continue
        prototype = blocks.get(custom_block_input[1])
        if prototype is None:
            continue

        mutation = prototype.get("mutation") or {}
        proccode = mutation.get("proccode", "")
        try:
            argument_ids: List[str] = json.loads(mutation.get("argumentids", "[]"))
        except (json.JSONDecodeError, TypeError):
            argument_ids = []
        try:
            argument_defaults: List[str] = json.loads(mutation.get("argumentdefaults", "[]"))
        except (json.JSONDecodeError, TypeError):
            argument_defaults = []
        warp = str(mutation.get("warp", "false")).lower() == "true"

        name = proccode_to_name.get(proccode) or _reconstruct_proc_name(proccode, len(argument_ids))

        proto_inputs = prototype.get("inputs") or {}
        arguments: List[ProcedureArgumentSpec] = []
        for idx, arg_id in enumerate(argument_ids):
            arg_type: ProcedureArgumentType = "string_number"
            ref = proto_inputs.get(arg_id)
            if isinstance(ref, list) and len(ref) > 1 and ref[1] in blocks:
                if blocks[ref[1]].get("opcode") == "argument_reporter_boolean":
                    arg_type = "boolean"

            default_raw = argument_defaults[idx] if idx < len(argument_defaults) else ""
            if default_raw == "":
                default_val: Any = None
            elif arg_type == "boolean":
                default_val = str(default_raw).lower() == "true"
            else:
                default_val = default_raw

            arguments.append(ProcedureArgumentSpec(name=arg_id, type=arg_type, default=default_val))

        body_start = block.get("next")
        body = _walk_chain(body_start, blocks, proccode_to_name)

        procedures.append(
            ProcedureDefinitionSpec(name=name, arguments=arguments, warp=warp, body=body)
        )

    return procedures


# ---------------------------------------------------------------------------
# ターゲット（スプライト/ステージ）単位の逆変換
# ---------------------------------------------------------------------------

def _parse_costume(c: Dict[str, Any]) -> CostumeSpec:
    return CostumeSpec(
        name=c.get("name", ""),
        bitmap_resolution=c.get("bitmapResolution", 1),
        data_format=c.get("dataFormat", "svg"),
        asset_id=c.get("assetId"),
        md5ext=c.get("md5ext"),
        rotation_center_x=c.get("rotationCenterX"),
        rotation_center_y=c.get("rotationCenterY"),
    )


def _parse_sound(s: Dict[str, Any]) -> SoundSpec:
    return SoundSpec(
        name=s.get("name", ""),
        data_format=s.get("dataFormat", "wav"),
        asset_id=s.get("assetId"),
        md5ext=s.get("md5ext"),
        rate=s.get("rate"),
        sample_count=s.get("sampleCount"),
    )


def _parse_variables(var_dict: Optional[Dict[str, Any]]) -> List[VariableSpec]:
    result: List[VariableSpec] = []
    for entry in (var_dict or {}).values():
        if isinstance(entry, list) and len(entry) >= 1:
            name = entry[0]
            value = entry[1] if len(entry) > 1 else 0
        else:
            name = str(entry)
            value = 0
        result.append(VariableSpec(name=name, initial_value=value))
    return result


def _parse_lists(list_dict: Optional[Dict[str, Any]]) -> List[ListSpec]:
    result: List[ListSpec] = []
    for entry in (list_dict or {}).values():
        if isinstance(entry, list) and len(entry) >= 1:
            name = entry[0]
            items = entry[1] if len(entry) > 1 else []
        else:
            name = str(entry)
            items = []
        result.append(ListSpec(name=name, items=list(items) if isinstance(items, list) else []))
    return result


def _parse_broadcasts(bcast_dict: Optional[Dict[str, Any]]) -> List[BroadcastSpec]:
    return [BroadcastSpec(name=name) for name in (bcast_dict or {}).values()]


def _parse_target(target: Dict[str, Any]) -> SpriteSpec:
    is_stage = bool(target.get("isStage", False))
    blocks: Dict[str, Any] = target.get("blocks", {}) or {}

    proccode_to_name = _build_proccode_to_name(blocks)
    procedures = _parse_procedures(blocks, proccode_to_name)

    scripts: List[ScriptSpec] = []
    for block_id, b in blocks.items():
        if b.get("topLevel") and b.get("opcode") != "procedures_definition":
            scripts.append(ScriptSpec(blocks=_walk_chain(block_id, blocks, proccode_to_name)))

    costumes = [_parse_costume(c) for c in target.get("costumes", [])]
    sounds = [_parse_sound(s) for s in target.get("sounds", [])]

    # ステージの "variables"/"lists"/"broadcasts" はグローバル定義そのものであり、
    # SpriteSpec.variables（スプライトローカル変数）としては扱わない（読み込み側で
    # 別途 ProjectSpec.variables/lists/broadcasts へ割り当てる）。
    local_variables = [] if is_stage else _parse_variables(target.get("variables"))

    return SpriteSpec(
        name=target.get("name", ""),
        is_stage=is_stage,
        x=float(target.get("x", 0.0) or 0.0),
        y=float(target.get("y", 0.0) or 0.0),
        size=float(target.get("size", 100.0) or 100.0),
        visible=target.get("visible", True),
        costumes=costumes,
        sounds=sounds,
        variables=local_variables,
        scripts=scripts,
        procedures=procedures,
    )


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def _register_embedded_assets(zf: zipfile.ZipFile, registry: AssetRegistry) -> None:
    """.sb3（ZIP）内の project.json 以外の全ファイル（コスチューム・サウンドのバイナリ）を
    そのアセットIDでレジストリへ登録する。

    これを行わないと、読み込んだプロジェクトを再度書き出す際に、writer.py の
    「未登録アセットはプレースホルダーへ自動フォールバック」が発動し、今回の指示で
    一切触っていないコスチューム/サウンドまで全てプレースホルダー画像・無音に
    差し替えられてしまう（継続編集の意味がなくなる重大な不具合になるため必須の処理）。
    """
    for info in zf.infolist():
        filename = info.filename
        if filename == "project.json" or filename.endswith("/"):
            continue
        stem, sep, ext = filename.rpartition(".")
        if not sep:
            continue
        asset_id = stem
        if registry.has(asset_id):
            continue
        content = zf.read(filename)
        registry.register(
            AssetRecord(asset_id=asset_id, data_format=ext, name=asset_id, content=content)
        )


def read_sb3(
    path: Union[str, Path],
    registry: Optional[AssetRegistry] = None,
) -> ProjectSpec:
    """既存の .sb3 ファイルを読み込み、ProjectSpec へ逆変換する。

    継続編集のエントリーポイント。返り値を generate_sb3(project=...) に渡すことで、
    次のパッチ適用（apply_patch）はこの ProjectSpec を土台に差分修正される。

    埋め込みアセット（コスチューム/サウンドの実バイナリ）は registry
    （省略時は DEFAULT_REGISTRY）へ登録される。generate_sb3 側も省略時は
    DEFAULT_REGISTRY を使うため、明示的に registry を指定しない限り、
    そのまま辻褄が合う。
    """
    reg = registry if registry is not None else DEFAULT_REGISTRY
    path = Path(path)

    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("project.json") as f:
            project_json = json.load(f)
        _register_embedded_assets(zf, reg)

    global_variables: List[VariableSpec] = []
    global_lists: List[ListSpec] = []
    global_broadcasts: List[BroadcastSpec] = []
    stage_spec: Optional[SpriteSpec] = None
    sprite_specs: List[SpriteSpec] = []

    for target in project_json.get("targets", []):
        sprite = _parse_target(target)
        if sprite.is_stage:
            stage_spec = sprite
            global_variables = _parse_variables(target.get("variables"))
            global_lists = _parse_lists(target.get("lists"))
            global_broadcasts = _parse_broadcasts(target.get("broadcasts"))
        else:
            sprite_specs.append(sprite)

    targets = ([stage_spec] if stage_spec is not None else []) + sprite_specs

    project = ProjectSpec(
        targets=targets,
        variables=global_variables,
        lists=global_lists,
        broadcasts=global_broadcasts,
    )

    # validate_project_spec に通すことで、未対応のopcode混入や procedures_call の
    # 未定義参照など、compiler.pyの前提が崩れている場合はここで明示的に失敗させる
    # （このツール以外が生成した.sb3を読み込んだ場合の主なエラー経路になる）。
    return validate_project_spec(project.model_dump())
