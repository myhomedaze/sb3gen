"""
sb3gen/renderer.py
ProjectSpec (ツリー構造) から疑似コードへの逆変換（レンダリング）層。
"""

from __future__ import annotations

from typing import List
from .schema import SpriteSpec, BlockSpec, ScriptSpec


def render_sprite_pseudocode(sprite: SpriteSpec) -> str:
    header = f"sprite {sprite.name} (x: {sprite.x}, y: {sprite.y}, size: {sprite.size}, visible: {sprite.visible}):"
    
    body_lines: List[str] = []
    for costume in sprite.costumes:
        body_lines.append(f"  costume {costume.name} ({costume.bitmap_resolution or 1})")

    for proc in sprite.procedures:
        body_lines.extend(_render_procedure(proc, indent=2))

    for script in sprite.scripts:
        body_lines.extend(_render_script(script, indent=2))
            
    joined = "\n".join(body_lines)
    return f"{header}\n{joined}\nend"


def _render_procedure(proc, indent: int) -> List[str]:
    """カスタムブロック（マイブロック）の宣言を、procedures_call側が参照できる名前・
    引数付きで疑似コード化する。これが無いと、procedures_callがどの名前を呼べば
    良いのかLLMから見えなくなり、存在しないカスタムブロック名をでっち上げてしまう。
    """
    pad = " " * indent
    arg_str = ", ".join(f"{a.name}:{a.type}" for a in proc.arguments)
    lines = [f"{pad}custom_block {proc.name}({arg_str}) warp={proc.warp}:"]
    for block in proc.body:
        lines.extend(_render_block(block, indent + 2))
    lines.append(f"{pad}end_custom_block")
    return lines


def _render_script(script: ScriptSpec, indent: int) -> List[str]:
    lines: List[str] = []
    for block in script.blocks:
        lines.extend(_render_block(block, indent))
    return lines


def _render_block(block: BlockSpec, indent: int) -> List[str]:
    pad = " " * indent
    line = f"{pad}{block.opcode}"

    if block.proc_name:
        line += f" proc_name={block.proc_name}"

    if block.fields:
        field_parts = [f"{k}={v}" for k, v in block.fields.items()]
        line += f" fields({', '.join(field_parts)})"
        
    if block.inputs:
        input_parts = [f"{k}={v}" for k, v in block.inputs.items()]
        line += f" inputs({', '.join(input_parts)})"
        
    lines = [line]
    for substack in block.substacks:
        for sub_block in substack:
            lines.extend(_render_block(sub_block, indent + 2))
            
    return lines