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
    
    for script in sprite.scripts:
        body_lines.extend(_render_script(script, indent=2))
            
    joined = "\n".join(body_lines)
    return f"{header}\n{joined}\nend"


def _render_script(script: ScriptSpec, indent: int) -> List[str]:
    lines: List[str] = []
    for block in script.blocks:
        lines.extend(_render_block(block, indent))
    return lines


def _render_block(block: BlockSpec, indent: int) -> List[str]:
    pad = " " * indent
    line = f"{pad}{block.opcode}"
    
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