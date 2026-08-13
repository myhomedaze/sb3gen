"""
sb3gen/writer.py
コンパイル済み project.json とアセットバイナリを .sb3 (ZIP) に書き出す層。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .assets import AssetRegistry, DEFAULT_REGISTRY, _generate_placeholder_svg, _generate_silent_wav, _compute_md5


def _collect_assets(project_dict: Dict[str, Any], registry: AssetRegistry) -> Dict[str, bytes]:
    """project.json 内で参照されているアセットを収集する。未登録の場合は自動でプレースホルダーをフォールバック登録する。"""
    written: Dict[str, bytes] = {}

    for target in project_dict.get("targets", []):
        for costume in target.get("costumes", []):
            asset_id = costume.get("assetId")
            data_format = costume.get("dataFormat", "svg")
            md5ext = costume.get("md5ext") or (
                f"{asset_id}.{data_format}" if asset_id and data_format else None
            )
            if asset_id and md5ext:
                record = registry.get(asset_id)
                if record:
                    written[md5ext] = record.content
                else:
                    # アセット欠落時に壊れた.sb3を出力しないための強固な自動フォールバック
                    # プレースホルダーは常にSVGとして生成されるため、dataFormat/拡張子も
                    # 実際のバイト列に合わせて "svg" に統一する（元のdata_formatを引きずると
                    # 内容と拡張子が食い違い、Scratch側で読み込めなくなる）。
                    fallback_content = _generate_placeholder_svg(costume.get("name", "missing"))
                    computed_id = _compute_md5(fallback_content)
                    costume["assetId"] = computed_id
                    costume["dataFormat"] = "svg"
                    costume["md5ext"] = f"{computed_id}.svg"
                    written[costume["md5ext"]] = fallback_content

        for sound in target.get("sounds", []):
            asset_id = sound.get("assetId")
            data_format = sound.get("dataFormat", "wav")
            md5ext = sound.get("md5ext") or (
                f"{asset_id}.{data_format}" if asset_id and data_format else None
            )
            if asset_id and md5ext:
                record = registry.get(asset_id)
                if record:
                    written[md5ext] = record.content
                else:
                    # コスチュームと同様、アセット欠落でプロジェクト全体を失敗させないよう、
                    # サイレンスWAVに自動フォールバックする。
                    fallback_content = _generate_silent_wav()
                    computed_id = _compute_md5(fallback_content)
                    sound["assetId"] = computed_id
                    sound["dataFormat"] = "wav"
                    sound["md5ext"] = f"{computed_id}.wav"
                    written[sound["md5ext"]] = fallback_content

    return written


def _write_zip(
    project_dict: Dict[str, Any],
    registry: AssetRegistry,
    output_file: Union[str, Path, io.BytesIO],
) -> None:
    assets = _collect_assets(project_dict, registry)
    project_json = json.dumps(project_dict, ensure_ascii=False, indent=2)

    with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", project_json)
        for filename, content in assets.items():
            zf.writestr(filename, content)


def write_sb3(
    project: Dict[str, Any],
    output_path: Union[str, Path],
    registry: Optional[AssetRegistry] = None,
) -> Path:
    """コンパイル済みプロジェクトを .sb3 ファイルとして書き出す。"""
    registry = registry or DEFAULT_REGISTRY
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_zip(project, registry, output_path)
    return output_path


def project_to_bytes(
    project: Dict[str, Any],
    registry: Optional[AssetRegistry] = None,
) -> bytes:
    """コンパイル済みプロジェクトを .sb3 のバイト列として返す。"""
    registry = registry or DEFAULT_REGISTRY
    buffer = io.BytesIO()
    _write_zip(project, registry, buffer)
    return buffer.getvalue()