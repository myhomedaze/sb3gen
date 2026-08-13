"""
sb3gen/renderer.py
SpriteSpec およびスクリプト・ブロック構造をインデント付き疑似コードに変換するモジュール。
"""

from __future__ import annotations
from typing import Any
from .schema import SpriteSpec, ScriptSpec, BlockSpec


def render_value(val: Any) -> str:
    if isinstance(val, dict):
        if "opcode" in val:
            return f"[{val.get('opcode')}(...)]"
        return str(val)
    return str(val)


def render_block(block: BlockSpec, indent: int = 0) -> str:
    pad = "  " * indent
    args_parts = []
    if block.fields:
        for k, v in block.fields.items():
            args_parts.append(f"{k}={render_value(v)}")
    
    args_str = f"({', '.join(args_parts)})" if args_parts else "()"
    header = f"{pad}{block.opcode}{args_str}"

    if block.substacks:
        body_lines = []
        for sub_script in block.substacks:
            sub_rendered = render_script_as_pseudocode(sub_script, indent + 1)
            if sub_rendered:
                body_lines.append(sub_rendered)
        if body_lines:
            return f"{header}\n{'\n'.join(body_lines)}\n{pad}end"

    return header


def render_script_as_pseudocode(script: ScriptSpec, indent: int = 0) -> str:
    if not script.blocks:
        return ""
    return "\n".join(render_block(b, indent) for b in script.blocks)


def render_sprite_pseudocode(sprite: SpriteSpec) -> str:
    costume_names = [c.name for c in sprite.costumes]
    meta = (
        f"Sprite Name: {sprite.name}\n"
        f"Is Stage: {sprite.is_stage}\n"
        f"Initial Position: x={sprite.x}, y={sprite.y}\n"
        f"Costumes: {costume_names}\n"
    )
    
    rendered_scripts = []
    for i, script in enumerate(sprite.scripts):
        rendered = render_script_as_pseudocode(script, indent=0)
        if rendered:
            rendered_scripts.append(f"# Script {i+1}\n{rendered}")

    scripts_text = "\n---\n".join(rendered_scripts) if rendered_scripts else "(No scripts)"
    return f"{meta}\nScripts:\n{scripts_text}"