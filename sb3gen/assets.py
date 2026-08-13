"""
sb3gen/assets.py
テンプレート管理・安全なSVG機械生成・プレースホルダー生成を担うアセット層。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import hashlib
import json
import struct
from xml.sax.saxutils import escape as _xml_escape

from .patcher import AssetDecision, AssetSourceType
from .schema import CostumeSpec

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_DEFAULT_MANIFEST: Dict[str, Any] = {
    "version": 1,
    "templates": {
        "cat": {
            "file": "cat.svg",
            "name": "Cat",
            "data_format": "svg",
        }
    },
}

_COLOR_MAP = {
    "赤": "#e53935",
    "red": "#e53935",
    "青": "#1e88e5",
    "blue": "#1e88e5",
    "緑": "#43a047",
    "green": "#43a047",
    "黄": "#fdd835",
    "yellow": "#fdd835",
    "オレンジ": "#fb8c00",
    "orange": "#fb8c00",
    "紫": "#8e24aa",
    "purple": "#8e24aa",
    "ピンク": "#f06292",
    "pink": "#f06292",
    "黒": "#000000",
    "black": "#000000",
    "白": "#ffffff",
    "white": "#ffffff",
    "グレー": "#9e9e9e",
    "gray": "#9e9e9e",
    "grey": "#9e9e9e",
    "茶": "#795548",
    "brown": "#795548",
}


def _compute_md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    data_format: str
    name: str
    content: bytes

    @property
    def md5ext(self) -> str:
        return f"{self.asset_id}.{self.data_format}"


class AssetRegistry:
    """生成・読込したアセットのバイナリを asset_id で保持する。"""

    def __init__(self) -> None:
        self._records: Dict[str, AssetRecord] = {}

    def register(self, record: AssetRecord) -> None:
        self._records[record.asset_id] = record

    def get(self, asset_id: str) -> Optional[AssetRecord]:
        return self._records.get(asset_id)

    def has(self, asset_id: str) -> bool:
        return asset_id in self._records


DEFAULT_REGISTRY = AssetRegistry()


def _load_manifest() -> Dict[str, Any]:
    manifest_path = TEMPLATES_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            with manifest_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return _DEFAULT_MANIFEST


def _detect_color(prompt: str) -> str:
    p = prompt.lower()
    for key, color in _COLOR_MAP.items():
        if key in p:
            return color
    return "#cccccc"


def _detect_shape(prompt: str) -> str:
    p = prompt.lower()
    if any(token in p for token in ("triangle", "三角", "さんかく")):
        return "triangle"
    if any(token in p for token in ("square", "rect", "四角", "しかく")):
        return "rect"
    if any(token in p for token in ("star", "星", "ほし")):
        return "star"
    if any(token in p for token in ("circle", "円", "丸", "まる")):
        return "circle"
    return "circle"


def _shape_element(shape: str, color: str) -> str:
    if shape == "circle":
        return f'<circle cx="50" cy="50" r="40" fill="{color}" stroke="#333333" stroke-width="3"/>'
    if shape == "rect":
        return f'<rect x="15" y="15" width="70" height="70" rx="4" fill="{color}" stroke="#333333" stroke-width="3"/>'
    if shape == "triangle":
        return f'<polygon points="50,10 90,90 10,90" fill="{color}" stroke="#333333" stroke-width="3"/>'
    if shape == "star":
        return f'<polygon points="50,10 61,35 90,35 65,50 75,80 50,62 25,80 35,50 10,35 39,35" fill="{color}" stroke="#333333" stroke-width="3"/>'
    return f'<circle cx="50" cy="50" r="40" fill="{color}" stroke="#333333" stroke-width="3"/>'


def _generate_svg_from_prompt(prompt: str) -> bytes:
    color = _detect_color(prompt)
    shape = _detect_shape(prompt)
    shape_svg = _shape_element(shape, color)
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">\n'
        f'{shape_svg}\n'
        '</svg>'
    )
    return svg.encode("utf-8")


def _generate_blank_backdrop_svg() -> bytes:
    """Stageの自動生成時のデフォルト背景（白地、480x360）。"""
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360">\n'
        '<rect x="0" y="0" width="480" height="360" fill="#ffffff"/>\n'
        '</svg>'
    )
    return svg.encode("utf-8")


def register_default_backdrop(registry: Optional["AssetRegistry"] = None) -> CostumeSpec:
    """白地の背景をレジストリに登録し、対応するCostumeSpecを返す。

    compile_projectがStageを自動生成する際に、レジストリに登録されていない
    固定assetIdを使い回していた問題（writer側で意図しないプレースホルダーに
    フォールバックしてしまう）を回避するためのヘルパー。
    """
    reg = registry if registry is not None else DEFAULT_REGISTRY
    content = _generate_blank_backdrop_svg()
    asset_id = _compute_md5(content)
    if not reg.has(asset_id):
        reg.register(AssetRecord(asset_id=asset_id, data_format="svg", name="backdrop1", content=content))
    return CostumeSpec(name="backdrop1", data_format="svg", asset_id=asset_id)


def _generate_silent_wav(duration_seconds: float = 0.2, sample_rate: int = 44100) -> bytes:
    """サイレンスのWAVを生成する（サウンドアセット欠落時のフォールバックに使う）。"""
    num_samples = max(1, int(duration_seconds * sample_rate))
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data = b"\x00\x00" * num_samples
    data_size = len(data)
    header = (
        b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample)
        + b"data" + struct.pack("<I", data_size)
    )
    return header + data


def _generate_placeholder_svg(name: str = "placeholder") -> bytes:
    safe_name = _xml_escape(name)
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">\n'
        '<rect x="5" y="5" width="90" height="90" rx="10" fill="#cccccc" stroke="#666666" stroke-width="2"/>\n'
        f'<text x="50" y="55" font-family="sans-serif" font-size="12" text-anchor="middle" fill="#333333">{safe_name}</text>\n'
        '</svg>'
    )
    return svg.encode("utf-8")


class AssetMaterializer:
    """AssetDecision を CostumeSpec と実バイナリに変換する callable。"""

    def __init__(self, registry: Optional[AssetRegistry] = None):
        self.registry = registry if registry is not None else DEFAULT_REGISTRY
        self.manifest = _load_manifest()

    def __call__(self, decision: AssetDecision) -> CostumeSpec:
        if decision.source_type == AssetSourceType.TEMPLATE:
            return self._from_template(decision)
        if decision.source_type == AssetSourceType.SVG_GENERATE:
            return self._from_svg_generation(decision)
        if decision.source_type == AssetSourceType.PLACEHOLDER:
            return self._from_placeholder(decision)
        raise ValueError(f"未知の AssetSourceType: {decision.source_type}")

    def _register_record(self, name: str, data_format: str, content: bytes) -> CostumeSpec:
        asset_id = _compute_md5(content)
        record = AssetRecord(
            asset_id=asset_id,
            data_format=data_format,
            name=name,
            content=content,
        )
        self.registry.register(record)
        return CostumeSpec(name=name, asset_id=asset_id, data_format=data_format)

    def _resolve_template_info(self, template_name: str) -> Optional[Dict[str, Any]]:
        templates = self.manifest.get("templates", {})
        if isinstance(templates, list):
            for item in templates:
                if item.get("name") == template_name:
                    return item
            return None
        if isinstance(templates, dict):
            return templates.get(template_name)
        return None

    def _from_template(self, decision: AssetDecision) -> CostumeSpec:
        template_name = decision.template_name or "cat"
        info = self._resolve_template_info(template_name)
        if not info:
            return self._from_placeholder(decision)

        file_name = info.get("file")
        if not file_name:
            return self._from_placeholder(decision)

        path = Path(file_name)
        if not path.is_absolute():
            path = TEMPLATES_DIR / file_name

        if not path.exists():
            return self._from_placeholder(decision)

        content = path.read_bytes()
        data_format = info.get("data_format", "svg")
        name = decision.costume_name or info.get("name", template_name)
        return self._register_record(name, data_format, content)

    def _from_svg_generation(self, decision: AssetDecision) -> CostumeSpec:
        prompt = decision.svg_generation_prompt or decision.costume_name or "circle"
        name = decision.costume_name or "generated"
        content = _generate_svg_from_prompt(prompt)
        return self._register_record(name, "svg", content)

    def _from_placeholder(self, decision: AssetDecision) -> CostumeSpec:
        name = decision.costume_name or "placeholder"
        content = _generate_placeholder_svg(name)
        return self._register_record(name, "svg", content)