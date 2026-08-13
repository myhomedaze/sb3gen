"""
sb3gen/main.py
自然言語指示から .sb3 を生成する統合エントリーポイント。
LLM 呼び出し関数と出力先を受け取る。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .assets import AssetMaterializer, AssetRegistry, DEFAULT_REGISTRY
from .compiler import compile_project
from .patcher import LLMCallable, MaterializeAssetCallable, PatchStatus, apply_patch
from .schema import ProjectSpec
from .writer import write_sb3


def generate_sb3(
    instruction: str,
    llm_call: LLMCallable,
    output_path: Union[str, Path],
    project: Optional[ProjectSpec] = None,
    materializer: Optional[MaterializeAssetCallable] = None,
    registry: Optional[AssetRegistry] = None,
) -> ProjectSpec:
    """
    指示文から .sb3 を生成する。
    """
    project = project or ProjectSpec()

    if materializer is None:
        mat = AssetMaterializer(registry=registry)
        materializer = mat
    elif registry is None and isinstance(materializer, AssetMaterializer):
        registry = materializer.registry

    registry = registry or DEFAULT_REGISTRY

    result = apply_patch(
        project,
        instruction,
        llm_call,
        materialize_asset=materializer,
    )

    if result.status != PatchStatus.SUCCESS:
        raise RuntimeError(f"パッチ適用に失敗しました: {result.message or result.status}")

    compiled = compile_project(result.project)
    write_sb3(compiled, output_path, registry=registry)
    return result.project