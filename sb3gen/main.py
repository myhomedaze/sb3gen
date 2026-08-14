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
from .patcher import (
    LLMCallable,
    MaterializeAssetCallable,
    PatchStatus,
    PendingClarification,
    apply_patch,
)
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
    指示が曖昧な場合（NEEDS_CLARIFICATION）は、ターミナルから追加の回答を
    受け取りながら最大MAX_CLARIFICATION_TURNS回まで聞き返しを繰り返す。
    """
    project = project or ProjectSpec()

    if materializer is None:
        mat = AssetMaterializer(registry=registry)
        materializer = mat
    elif isinstance(materializer, AssetMaterializer):
        if registry is None:
            registry = materializer.registry
    elif registry is None:
        # materializerがAssetMaterializerのインスタンスでない場合、そのmaterializerが
        # 実際にアセットを登録しているレジストリをここから読み取ることはできない。
        # このままDEFAULT_REGISTRYへ黙ってフォールバックすると、compile_project/write_sb3が
        # materializerの登録先とは別のレジストリを参照することになり、writer側の
        # 「アセット欠落時プレースホルダー自動フォールバック」が全コスチューム/サウンドに対して
        # 静かに発動してしまう（見た目上は成功するが、中身が全部プレースホルダーになる）。
        # 原因が分かりにくい形で壊れるより、ここで早期に明示的なエラーにする。
        raise ValueError(
            "materializerにAssetMaterializer以外のcallableを渡す場合、"
            "そのmaterializerが実際に使用しているregistryをregistry引数として"
            "明示的に渡してください（省略するとアセットが正しく解決できません）。"
        )

    registry = registry or DEFAULT_REGISTRY

    pending: Optional[PendingClarification] = None
    current_instruction = instruction

    while True:
        result = apply_patch(
            project,
            current_instruction,
            llm_call,
            materialize_asset=materializer,
            pending=pending,
        )

        if result.status == PatchStatus.SUCCESS:
            break

        if result.status == PatchStatus.NEEDS_CLARIFICATION:
            print(result.message)
            current_instruction = input("> ")
            pending = result.pending_clarification
            continue

        raise RuntimeError(f"パッチ適用に失敗しました: {result.message or result.status}")

    compiled = compile_project(result.project, registry=registry)
    write_sb3(compiled, output_path, registry=registry)
    return result.project
