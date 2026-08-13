"""
sb3gen/linter.py
生成されたブロックツリーを走査し、未知の変数・リスト・ブロードキャスト参照を検出する。
検出した未知の名前は、エラーにするのではなくグローバル定義へ自動登録することで、
スプライトをまたいだ参照の食い違いによる「静かに動かないロジック」を防ぐ。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .schema import BlockSpec, BroadcastSpec, ListSpec, ProjectSpec, VariableSpec

_VARIABLE_OPCODES = {
    "data_variable",
    "data_setvariableto",
    "data_changevariableby",
    "data_showvariable",
    "data_hidevariable",
}

_LIST_OPCODES = {
    "data_listcontents",
    "data_addtolist",
    "data_deleteoflist",
    "data_deletealloflist",
    "data_insertatlist",
    "data_replaceitemoflist",
    "data_itemoflist",
    "data_itemnumoflist",
    "data_lengthoflist",
    "data_listcontainsitem",
    "data_showlist",
    "data_hidelist",
}

_BROADCAST_SEND_OPCODES = {"event_broadcast", "event_broadcastandwait"}
_BROADCAST_RECEIVE_OPCODES = {"event_whenbroadcastreceived"}


def _field_name(value: object) -> Optional[str]:
    """block.fields の値から名前部分を取り出す。[name, id] 形式・生の文字列どちらにも対応。"""
    if isinstance(value, list) and value:
        return str(value[0]) if value[0] is not None else None
    if value is None:
        return None
    return str(value)


def _collect_from_blocks(blocks: List[BlockSpec], refs: Dict[str, Set[str]]) -> None:
    for block in blocks:
        if block.opcode in _VARIABLE_OPCODES:
            name = _field_name(block.fields.get("VARIABLE"))
            if name:
                refs["variable"].add(name)
        if block.opcode in _LIST_OPCODES:
            name = _field_name(block.fields.get("LIST"))
            if name:
                refs["list"].add(name)
        if block.opcode in _BROADCAST_SEND_OPCODES:
            name = _field_name(block.fields.get("BROADCAST_INPUT"))
            if name:
                refs["broadcast"].add(name)
        if block.opcode in _BROADCAST_RECEIVE_OPCODES:
            name = _field_name(block.fields.get("BROADCAST_OPTION"))
            if name:
                refs["broadcast"].add(name)
        for substack in block.substacks:
            _collect_from_blocks(substack, refs)


def _collect_refs_for_target(target) -> Dict[str, Set[str]]:
    refs: Dict[str, Set[str]] = {"variable": set(), "list": set(), "broadcast": set()}
    for script in target.scripts:
        _collect_from_blocks(script.blocks, refs)
    return refs


def collect_referenced_names(project: ProjectSpec) -> Dict[str, Set[str]]:
    """プロジェクト全体のスクリプトが参照している変数/リスト/ブロードキャスト名を集める。"""
    refs: Dict[str, Set[str]] = {"variable": set(), "list": set(), "broadcast": set()}
    for target in project.targets:
        target_refs = _collect_refs_for_target(target)
        for key in refs:
            refs[key] |= target_refs[key]
    return refs


def reconcile_globals(project: ProjectSpec) -> ProjectSpec:
    """
    スクリプトが参照しているが、そのターゲット自身のローカル変数としても
    グローバル定義としてもまだ存在しない変数/リスト/ブロードキャストを
    自動的にグローバル定義へ追加した ProjectSpec を返す。
    既に存在するもの（グローバル定義・当該ターゲットのローカル定義どちらも）には触れない
    （差分がなければ同一オブジェクトの浅いコピーを返す）。
    """
    known_vars = {v.name for v in project.variables}
    known_lists = {l.name for l in project.lists}
    known_bcasts = {b.name for b in project.broadcasts}

    missing_vars: Set[str] = set()
    missing_lists: Set[str] = set()
    missing_bcasts: Set[str] = set()

    for target in project.targets:
        # スプライト自身にローカル定義されている変数名はグローバル自動登録の対象から除外する
        local_var_names = {v.name for v in target.variables} if not target.is_stage else set()
        target_refs = _collect_refs_for_target(target)
        missing_vars |= (target_refs["variable"] - known_vars - local_var_names)
        missing_lists |= (target_refs["list"] - known_lists)
        missing_bcasts |= (target_refs["broadcast"] - known_bcasts)

    if not (missing_vars or missing_lists or missing_bcasts):
        return project

    new_vars = list(project.variables) + [VariableSpec(name=n) for n in sorted(missing_vars)]
    new_lists = list(project.lists) + [ListSpec(name=n) for n in sorted(missing_lists)]
    new_bcasts = list(project.broadcasts) + [BroadcastSpec(name=n) for n in sorted(missing_bcasts)]

    return project.model_copy(
        update={
            "variables": new_vars,
            "lists": new_lists,
            "broadcasts": new_bcasts,
        }
    )
