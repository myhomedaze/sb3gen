"""
sb3gen/llm_io.py
LLM呼び出しまわりの出力安定化ユーティリティ（7番: LLM出力安定性）。

現在の設計は「1回のLLM呼び出しで比較的大きなJSONを一気に出力させる」ことに
起因するリスク（出力が途中で切れてJSONパースに失敗する）を持っている。
特に今後カスタムブロック（procedures_definition/mutation）や拡張機能が
加わると、1スプライトあたりの出力量がさらに増える見込みのため、ここで
土台を先に固める。

このモジュールが提供するもの:
  1. 出力の破損を「途中で切れた（トークン上限などによる打ち切り）」ケースと
     「スキーマに違反している」ケースに分類し、それぞれに適したリトライ
     プロンプトを組み立てる（generate_json_with_retry）。
  2. 大きくなりがちな構造（スプライトのスクリプト群など）を、あらかじめ
     小さな単位に分割して個別にLLM呼び出しする仕組み
     （generate_items_individually）。1回あたりの出力サイズを一定に抑える
     ことで、将来スキーマが肥大化しても個々の呼び出しは小さく保てる。
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel, ValidationError

LLMCallable = Callable[[str, str], str]

MAX_GENERATION_RETRIES = 3

# リトライ時に前回出力のどこまでをプロンプトへ再掲するか（トークン浪費を防ぐための上限）
_TRUNCATION_TAIL_PREVIEW_CHARS = 1500

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_ItemT = TypeVar("_ItemT")


def strip_code_fence(raw: str) -> str:
    """LLM出力からMarkdownのコードフェンス（```json ... ```）を取り除く。
    閉じフェンスが無い（＝途中で切れた）場合も可能な範囲でそのまま返す。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
    return cleaned.strip()


def _is_likely_truncated(cleaned: str, exc: json.JSONDecodeError) -> bool:
    """JSONDecodeErrorが「出力が途中で切れたこと」に起因するかどうかを推定する。

    厳密な判定はできない（LLMが単純に壊れたJSONを書いた可能性もあるため）が、
    以下のいずれかに該当すれば「途中切れ」の可能性が高いとみなす:
      - エラー位置が出力の末尾付近である
      - 出力の末尾が閉じ括弧（'}' や ']'）で終わっていない
      - エラーメッセージが「値/文字列が終わらないまま終端した」ことを示している
    """
    if not cleaned:
        return True
    tail = cleaned.rstrip()
    near_end = exc.pos >= max(0, len(cleaned) - 3)
    ends_unclosed = not tail.endswith(("}", "]"))
    msg = exc.msg.lower()
    looks_unterminated = ("unterminated" in msg) or ("expecting" in msg and near_end)
    return near_end or ends_unclosed or looks_unterminated


def _build_retry_prompt_for_truncation(
    initial_user_prompt: str, cleaned: str, attempt: int, max_retries: int
) -> str:
    tail_preview = cleaned[-_TRUNCATION_TAIL_PREVIEW_CHARS:]
    return (
        f"{initial_user_prompt}\n\n"
        f"--- 前回の出力は途中で切れてJSONとして完結しませんでした（試行 {attempt}/{max_retries}） ---\n"
        "前回の出力の末尾（切れた部分）:\n"
        f"{tail_preview}\n\n"
        "出力が長すぎて途中で切れないよう、次を必ず守って出力し直してください:\n"
        "1. 説明文・前置き・Markdownのコードブロックは一切含めない。\n"
        "2. 不要な改行や空白を増やさず、コンパクトなJSONにする。\n"
        "3. 内容を簡略化してでも、必ずJSON全体を最後（閉じ括弧）まで出力し切る。\n"
    )


def _build_retry_prompt_for_validation_error(
    initial_user_prompt: str, cleaned: str, last_error: str, attempt: int, max_retries: int
) -> str:
    return (
        f"{initial_user_prompt}\n\n"
        f"--- 前回の出力はエラーになりました（試行 {attempt}/{max_retries}） ---\n"
        f"エラー内容:\n{last_error}\n"
        f"前回の出力:\n{cleaned}\n\n"
        "上記のエラーを修正し、指定されたJSONスキーマに厳密に従って、"
        "JSONオブジェクトのみを出力し直してください。"
    )


def generate_json_with_retry(
    system_prompt: str,
    initial_user_prompt: str,
    model_cls: Type[_ModelT],
    llm_call: LLMCallable,
    max_retries: int = MAX_GENERATION_RETRIES,
) -> _ModelT:
    """LLMにJSONを出力させ、指定したPydanticモデルとして検証する。

    JSONパース失敗時は「途中切れ」か「スキーマ違反」かを判定し、それぞれに
    応じたリトライプロンプトで再試行する（7番: LLM出力安定性の基盤）。
    """
    schema_json = json.dumps(model_cls.model_json_schema(), ensure_ascii=False, indent=2)
    enhanced_system_prompt = (
        f"{system_prompt}\n\n"
        "【出力形式の厳守】\n"
        "必ず以下のJSONスキーマに完全に準拠したJSONオブジェクトのみを出力してください"
        "（Markdownのコードブロックを含め、余分なテキストや解説は一切含めないこと）。\n"
        f"{schema_json}"
    )

    user_prompt = initial_user_prompt
    last_error: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        raw = llm_call(enhanced_system_prompt, user_prompt)
        cleaned = strip_code_fence(raw)

        try:
            data = json.loads(cleaned)
            return model_cls.model_validate(data)
        except json.JSONDecodeError as e:
            last_error = str(e)
            if _is_likely_truncated(cleaned, e):
                user_prompt = _build_retry_prompt_for_truncation(
                    initial_user_prompt, cleaned, attempt, max_retries
                )
            else:
                user_prompt = _build_retry_prompt_for_validation_error(
                    initial_user_prompt, cleaned, last_error, attempt, max_retries
                )
        except ValidationError as e:
            last_error = str(e)
            user_prompt = _build_retry_prompt_for_validation_error(
                initial_user_prompt, cleaned, last_error, attempt, max_retries
            )

    raise ValueError(
        f"{max_retries}回のリトライ後もLLM出力の検証に失敗しました。最終エラー: {last_error}"
    )


def generate_items_individually(
    plan_items: Sequence[_ItemT],
    system_prompt_fn: Callable[[int, int], str],
    user_prompt_fn: Callable[[int, _ItemT], str],
    model_cls: Type[_ModelT],
    llm_call: LLMCallable,
    max_retries: int = MAX_GENERATION_RETRIES,
) -> List[_ModelT]:
    """計画済みの項目（plan_items）を1件ずつ、個別のLLM呼び出しで生成する。

    スプライトのスクリプト群のような「まとめて出力させると巨大になりがちな
    リスト」を、要約だけの軽量な計画（plan_items）に基づいて1件ずつ生成する
    ことで、1回あたりの出力サイズを一定範囲に抑える（7番）。
    1件の生成に失敗しても、その項目だけをリトライすればよく、他の項目の
    再生成は不要。
    """
    results: List[_ModelT] = []
    total = len(plan_items)
    for idx, item in enumerate(plan_items):
        system_prompt = system_prompt_fn(idx, total)
        user_prompt = user_prompt_fn(idx, item)
        results.append(
            generate_json_with_retry(
                system_prompt, user_prompt, model_cls, llm_call, max_retries=max_retries
            )
        )
    return results
