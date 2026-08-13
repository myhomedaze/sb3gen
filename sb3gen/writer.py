"""
sb3gen/writer.py
コンパイル済み project.json とアセットバイナリを .sb3 (ZIP) に書き出す層。
"""

from __future__ import annotations

import io
import json
import warnings
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .assets import AssetRegistry, DEFAULT_REGISTRY


def _collect_assets(project_dict: Dict[str, Any], registry: AssetRegistry) -> Dict[str, bytes]:
    """project.json 内で参照されているアセットを収集する。"""
    written: Dict[str, bytes] = {}

    for target in project_dict.get("targets", []):
        for costume in target.get("costumes", []):
            asset_id = costume.get("assetId")
            data_format = costume.get("dataFormat")
            md5ext = costume.get("md5ext") or (
                f"{asset_id}.{data_format}" if asset_id and data_format else None
            )
            if asset_id and md5ext:
                record = registry.get(asset_id)
                if record:
                    written[md5ext] = record.content
                else:
                    warnings.warn(
                        f"アセット '{asset_id}' がレジストリに見つかりません。スキップします。",
                        stacklevel=2,
                    )

        for sound in target.get("sounds", []):
            asset_id = sound.get("assetId")
            data_format = sound.get("dataFormat")
            md5ext = sound.get("md5ext") or (
                f"{asset_id}.{data_format}" if asset_id and data_format else None
            )
            if asset_id and md5ext:
                record = registry.get(asset_id)
                if record:
                    written[md5ext] = record.content
                else:
                    warnings.warn(
                        f"サウンドアセット '{asset_id}' がレジストリに見つかりません。",
                        stacklevel=2,
                    )

    return written


def _write_zip(
    project_dict: Dict[str, Any],
    registry: AssetRegistry,
    output_file: Union[str, Path, io.BytesIO],
) -> None:
    project_json = json.dumps(project_dict, ensure_ascii=False, indent=2)
    assets = _collect_assets(project_dict, registry)

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