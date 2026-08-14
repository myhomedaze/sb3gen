"""
sb3gen/assets.py
テンプレート管理・安全なSVG機械生成・プレースホルダー生成を担うアセット層。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import hashlib
import json
import math
import re
import struct
from xml.sax.saxutils import escape as _xml_escape

from .patcher import AssetDecision, AssetSourceType
from .schema import CostumeSpec, SoundSpec

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


def _infer_svg_center(content: bytes) -> Tuple[float, float]:
    """SVGのviewBoxまたはwidth/height属性から回転中心を推定する。
    どちらも取得できない場合は (0.0, 0.0) を返す。"""
    try:
        text = content.decode("utf-8", errors="ignore")
    except Exception:
        return (0.0, 0.0)

    m = re.search(
        r'viewBox\s*=\s*"\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"',
        text,
    )
    if m:
        try:
            # viewBox="minX minY width height"。以前はminX/minYを無視しwidth/2, height/2を
            # そのまま中心としていたため、minX/minYが0でないSVG（テンプレートや
            # --reference経由で読み込む外部SVGなど）で回転中心がズレる不具合があった。
            # min_x/min_yを加算して実際の中心座標を求める。
            min_x, min_y = float(m.group(1)), float(m.group(2))
            width, height = float(m.group(3)), float(m.group(4))
            return (min_x + width / 2, min_y + height / 2)
        except ValueError:
            pass

    mw = re.search(r'\bwidth\s*=\s*"([\d.]+)', text)
    mh = re.search(r'\bheight\s*=\s*"([\d.]+)', text)
    if mw and mh:
        try:
            return (float(mw.group(1)) / 2, float(mh.group(1)) / 2)
        except ValueError:
            pass

    return (0.0, 0.0)


def _parse_wav_info(content: bytes) -> Tuple[int, int]:
    """WAV(RIFF)バイナリからサンプルレートとサンプル数を読み取る。
    解析できない場合は (44100, 0) を返す。"""
    if len(content) < 12 or content[0:4] != b"RIFF" or content[8:12] != b"WAVE":
        return (44100, 0)

    pos = 12
    channels = 1
    sample_rate = 44100
    bits_per_sample = 16
    data_size = 0

    while pos + 8 <= len(content):
        chunk_id = content[pos:pos + 4]
        chunk_size = struct.unpack("<I", content[pos + 4:pos + 8])[0]
        chunk_data_start = pos + 8

        if chunk_id == b"fmt " and chunk_data_start + 16 <= len(content):
            fmt_data = content[chunk_data_start:chunk_data_start + 16]
            _, channels, sample_rate, _, _, bits_per_sample = struct.unpack("<HHIIHH", fmt_data)
        elif chunk_id == b"data":
            data_size = chunk_size

        # チャンクはワード境界（偶数バイト）に整列される
        pos = chunk_data_start + chunk_size + (chunk_size % 2)

    bytes_per_sample = max(1, bits_per_sample // 8)
    sample_count = data_size // (bytes_per_sample * max(1, channels)) if data_size else 0
    return (sample_rate, sample_count)


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


def _clamp(value: float) -> int:
    return max(0, min(255, int(value)))


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    r, g, b = rgb
    return "#{:02x}{:02x}{:02x}".format(_clamp(r), _clamp(g), _clamp(b))


def _lighten(hex_color: str, amount: float = 0.35) -> str:
    """指定した色を白に向けて amount(0-1) だけ混ぜ、明るい色を返す（グラデーションの中心用）。"""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((
        r + (255 - r) * amount,
        g + (255 - g) * amount,
        b + (255 - b) * amount,
    ))


def _darken(hex_color: str, amount: float = 0.3) -> str:
    """指定した色を黒に向けて amount(0-1) だけ混ぜ、暗い色を返す（グラデーションの縁・輪郭線用）。"""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((
        r * (1 - amount),
        g * (1 - amount),
        b * (1 - amount),
    ))


def _detect_colors(prompt: str) -> List[str]:
    """プロンプト中に登場する色を出現順・重複なしで検出する。
    1件も見つからなければデフォルト1色を返す。"""
    p = prompt.lower()
    found: List[Tuple[int, str]] = []
    for key, color in _COLOR_MAP.items():
        idx = p.find(key)
        if idx != -1:
            found.append((idx, color))
    found.sort(key=lambda pair: pair[0])
    colors: List[str] = []
    for _, color in found:
        if color not in colors:
            colors.append(color)
    return colors or ["#4fc3f7"]


def _detect_shapes(prompt: str) -> List[str]:
    """プロンプト中に登場する図形を出現順・重複なしで検出する。
    1件も見つからなければデフォルト1種を返す。"""
    p = prompt.lower()
    shape_keywords = [
        ("triangle", ("triangle", "三角", "さんかく")),
        ("rect", ("square", "rect", "四角", "しかく")),
        ("star", ("star", "星", "ほし")),
        ("heart", ("heart", "ハート", "はーと")),
        ("circle", ("circle", "円", "丸", "まる")),
    ]
    found: List[Tuple[int, str]] = []
    for shape, tokens in shape_keywords:
        for token in tokens:
            idx = p.find(token)
            if idx != -1:
                found.append((idx, shape))
                break
    found.sort(key=lambda pair: pair[0])
    shapes: List[str] = []
    for _, shape in found:
        if shape not in shapes:
            shapes.append(shape)
    return shapes or ["circle"]


def _shape_path(shape: str, cx: float, cy: float, r: float) -> str:
    """指定した中心・サイズで図形の要素タグ（開始部分。fill/strokeは付与前）を返す。"""
    if shape == "rect":
        side = r * 1.7
        x, y = cx - side / 2, cy - side / 2
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{side:.1f}" height="{side:.1f}" rx="{side * 0.08:.1f}"'
    if shape == "triangle":
        p1 = (cx, cy - r)
        p2 = (cx + r * 0.95, cy + r * 0.8)
        p3 = (cx - r * 0.95, cy + r * 0.8)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (p1, p2, p3))
        return f'<polygon points="{points}"'
    if shape == "star":
        points = []
        for i in range(10):
            angle = math.pi / 5 * i - math.pi / 2
            radius = r if i % 2 == 0 else r * 0.42
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        return f'<polygon points="{pts}"'
    if shape == "heart":
        d = (
            f"M {cx:.1f} {cy + r * 0.7:.1f} "
            f"C {cx - r * 1.3:.1f} {cy - r * 0.3:.1f}, {cx - r * 0.5:.1f} {cy - r * 1.1:.1f}, {cx:.1f} {cy - r * 0.4:.1f} "
            f"C {cx + r * 0.5:.1f} {cy - r * 1.1:.1f}, {cx + r * 1.3:.1f} {cy - r * 0.3:.1f}, {cx:.1f} {cy + r * 0.7:.1f} Z"
        )
        return f'<path d="{d}"'
    # circle（デフォルト）
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"'


def _layout_slots(count: int) -> List[Tuple[float, float, float]]:
    """合成する図形の個数に応じて (中心x, 中心y, サイズ) のスロットを100x100キャンバス上に配置する。"""
    if count <= 1:
        return [(50.0, 52.0, 38.0)]
    if count == 2:
        return [(32.0, 55.0, 27.0), (68.0, 55.0, 27.0)]
    if count == 3:
        return [(50.0, 32.0, 22.0), (26.0, 68.0, 22.0), (74.0, 68.0, 22.0)]
    # 4個以上は2x2グリッドに均等配置（最大4個まで）
    return [(30.0, 32.0, 20.0), (70.0, 32.0, 20.0), (30.0, 70.0, 20.0), (70.0, 70.0, 20.0)]


def _build_gradient_and_shape(
    shape: str, color: str, cx: float, cy: float, r: float, grad_id: str
) -> Tuple[str, str]:
    """1図形分の (defsに入れるgradient定義, body要素群) を返す。
    明るい中心色→本来の色→暗い縁の放射グラデーションで立体感を、
    半透明のハイライト（光沢）と接地影を添えてリッチな見た目にする（5番: アセット生成の質向上）。"""
    light = _lighten(color, 0.45)
    dark = _darken(color, 0.28)
    gradient_def = (
        f'<radialGradient id="{grad_id}" cx="35%" cy="30%" r="75%">'
        f'<stop offset="0%" stop-color="{light}"/>'
        f'<stop offset="55%" stop-color="{color}"/>'
        f'<stop offset="100%" stop-color="{dark}"/>'
        f'</radialGradient>'
    )
    outline = _darken(color, 0.45)
    shape_open = _shape_path(shape, cx, cy, r)
    body = f'{shape_open} fill="url(#{grad_id})" stroke="{outline}" stroke-width="{max(1.5, r * 0.06):.1f}"/>'

    hl_cx = cx - r * 0.28
    hl_cy = cy - r * 0.32
    hl_rx = r * 0.32
    hl_ry = r * 0.2
    highlight = (
        f'<ellipse cx="{hl_cx:.1f}" cy="{hl_cy:.1f}" rx="{hl_rx:.1f}" ry="{hl_ry:.1f}" '
        f'fill="#ffffff" opacity="0.45" transform="rotate(-30 {hl_cx:.1f} {hl_cy:.1f})"/>'
    )

    shadow_cy = cy + r * 0.92
    shadow_rx = r * 0.85
    shadow_ry = r * 0.18
    shadow = (
        f'<ellipse cx="{cx:.1f}" cy="{shadow_cy:.1f}" rx="{shadow_rx:.1f}" ry="{shadow_ry:.1f}" '
        f'fill="#000000" opacity="0.15"/>'
    )

    return gradient_def, (shadow + body + highlight)


def _generate_svg_from_prompt(prompt: str) -> bytes:
    """プロンプトから検出した色・図形をもとに、グラデーション・光沢・接地影を持つ
    リッチなSVGコスチュームを生成する。複数の色/図形が読み取れた場合は、それぞれを
    スロットに配置して1枚のSVGに合成する（5番: アセット生成の質向上）。"""
    colors = _detect_colors(prompt)
    shapes = _detect_shapes(prompt)

    # 図形数は shapes/colors のうち多いほうに合わせ、足りない側は先頭から繰り返して補う。
    count = min(max(len(shapes), len(colors)), 4)
    slots = _layout_slots(count)

    defs_parts: List[str] = []
    body_parts: List[str] = []
    for i, (cx, cy, r) in enumerate(slots):
        shape = shapes[i % len(shapes)]
        color = colors[i % len(colors)]
        grad_id = f"grad{i}"
        gradient_def, body = _build_gradient_and_shape(shape, color, cx, cy, r, grad_id)
        defs_parts.append(gradient_def)
        body_parts.append(body)

    defs = "".join(defs_parts)
    body = "\n".join(body_parts)
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">\n'
        f'<defs>{defs}</defs>\n'
        f'{body}\n'
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
    center_x, center_y = _infer_svg_center(content)
    return CostumeSpec(
        name="backdrop1",
        data_format="svg",
        asset_id=asset_id,
        rotation_center_x=center_x,
        rotation_center_y=center_y,
    )


def register_wav_asset(
    source: Union[str, Path, bytes],
    name: Optional[str] = None,
    registry: Optional["AssetRegistry"] = None,
) -> SoundSpec:
    """.wav ファイル（パスまたは生バイト列）を読み込み、レジストリへ登録して SoundSpec を返す。"""
    reg = registry if registry is not None else DEFAULT_REGISTRY

    if isinstance(source, (str, Path)):
        path = Path(source)
        content = path.read_bytes()
        sound_name = name or path.stem
    else:
        content = source
        sound_name = name or "sound1"

    rate, sample_count = _parse_wav_info(content)
    asset_id = _compute_md5(content)
    if not reg.has(asset_id):
        reg.register(AssetRecord(asset_id=asset_id, data_format="wav", name=sound_name, content=content))

    return SoundSpec(
        name=sound_name,
        data_format="wav",
        asset_id=asset_id,
        md5ext=f"{asset_id}.wav",
        rate=rate,
        sample_count=sample_count,
    )


def register_wav_template(
    template_name: str,
    registry: Optional["AssetRegistry"] = None,
) -> Optional[SoundSpec]:
    """templates/manifest.json の "sounds" セクションに登録されたテンプレート音声を読み込む。
    見つからない場合は None を返す。"""
    manifest = _load_manifest()
    sounds = manifest.get("sounds", {})

    info: Optional[Dict[str, Any]] = None
    if isinstance(sounds, dict):
        info = sounds.get(template_name)
    elif isinstance(sounds, list):
        info = next((item for item in sounds if item.get("name") == template_name), None)

    if not info:
        return None

    file_name = info.get("file")
    if not file_name:
        return None

    path = Path(file_name)
    if not path.is_absolute():
        path = TEMPLATES_DIR / file_name
    if not path.exists():
        return None

    return register_wav_asset(path, name=info.get("name", template_name), registry=registry)


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
        rotation_center_x: Optional[float] = None
        rotation_center_y: Optional[float] = None
        if data_format == "svg":
            rotation_center_x, rotation_center_y = _infer_svg_center(content)
        return CostumeSpec(
            name=name,
            asset_id=asset_id,
            data_format=data_format,
            rotation_center_x=rotation_center_x,
            rotation_center_y=rotation_center_y,
        )

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