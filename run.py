"""
実行用スクリプト (CLI対応・環境変数チェック完備)
OpenAI / Gemini の両方に対応。--provider または LLM_PROVIDER で切り替え可能。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from sb3gen.main import generate_sb3


# ---------------------------------------------------------------------------
# 一時的なエラー時の自動リトライ（指数バックオフ）
# ---------------------------------------------------------------------------
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
BACKOFF_MULTIPLIER = 2.0

# リトライ対象とみなすエラーメッセージ中のキーワード（プロバイダ横断で緩めに判定）
_RETRYABLE_MARKERS = (
    "503",
    "UNAVAILABLE",
    "429",
    "RESOURCE_EXHAUSTED",
    "rate limit",
    "overloaded",
    "timeout",
    "timed out",
)


def _is_retryable_error(exc: Exception) -> bool:
    message = str(exc)
    return any(marker.lower() in message.lower() for marker in _RETRYABLE_MARKERS)


def with_retry(func):
    """LLM呼び出し関数をラップし、一時的なエラー時は指数バックオフで自動リトライする。"""

    def wrapped(system_prompt: str, user_prompt: str) -> str:
        backoff = INITIAL_BACKOFF_SECONDS
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(system_prompt, user_prompt)
            except Exception as e:
                last_exc = e
                if not _is_retryable_error(e) or attempt == MAX_RETRIES:
                    raise
                print(
                    f"一時的なエラーが発生しました（試行 {attempt}/{MAX_RETRIES}）: {e}\n"
                    f"{backoff:.0f}秒待って再試行します...",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
        raise last_exc  # pragma: no cover

    return wrapped


# ---------------------------------------------------------------------------
# OpenAI 実装
# ---------------------------------------------------------------------------
def build_openai_llm_call():
    import openai

    if not os.environ.get("OPENAI_API_KEY"):
        print("エラー: 環境変数 'OPENAI_API_KEY' が設定されていません。", file=sys.stderr)
        print("実行前にターミナルで以下を設定してください:", file=sys.stderr)
        print("  export OPENAI_API_KEY=\"your_api_key_here\"", file=sys.stderr)
        sys.exit(1)

    client = openai.OpenAI()

    def openai_llm_call(system_prompt: str, user_prompt: str) -> str:
        """OpenAI API を呼び出して JSON 文字列を返すラッパー関数"""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    return openai_llm_call


# ---------------------------------------------------------------------------
# Gemini 実装
# ---------------------------------------------------------------------------
def build_gemini_llm_call():
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print(
            "エラー: 'google-genai' パッケージがインストールされていません。",
            file=sys.stderr,
        )
        print("  pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。", file=sys.stderr)
        print("実行前にターミナルで以下を設定してください:", file=sys.stderr)
        print("  export GEMINI_API_KEY=\"your_api_key_here\"", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    def gemini_llm_call(system_prompt: str, user_prompt: str) -> str:
        """Gemini API を呼び出して JSON 文字列を返すラッパー関数"""
        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        text = response.text
        if text is None:
            raise RuntimeError("Gemini API から空の応答が返されました。")
        return text

    return gemini_llm_call


# ---------------------------------------------------------------------------
# プロバイダ選択
# ---------------------------------------------------------------------------
PROVIDER_BUILDERS = {
    "openai": build_openai_llm_call,
    "gemini": build_gemini_llm_call,
}


def resolve_provider(cli_provider: str | None) -> str:
    if cli_provider:
        return cli_provider

    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        env_provider = env_provider.lower()
        if env_provider not in PROVIDER_BUILDERS:
            print(f"エラー: 未知の LLM_PROVIDER '{env_provider}' です。", file=sys.stderr)
            print(f"  指定可能な値: {', '.join(PROVIDER_BUILDERS)}", file=sys.stderr)
            sys.exit(1)
        return env_provider

    # 環境変数のAPIキーからの自動判定（両方ある場合は openai を優先）
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"

    print("エラー: 使用する LLM プロバイダを判定できませんでした。", file=sys.stderr)
    print("以下のいずれかを設定してください:", file=sys.stderr)
    print("  --provider openai または --provider gemini", file=sys.stderr)
    print("  環境変数 LLM_PROVIDER=openai / gemini", file=sys.stderr)
    print("  OPENAI_API_KEY または GEMINI_API_KEY", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自然言語指示から .sb3 プロジェクトを生成します。")
    parser.add_argument("instruction", nargs="?", help="生成指示（未指定の場合はデフォルト指示を使用）")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDER_BUILDERS),
        default=None,
        help="使用するLLMプロバイダ (openai / gemini)。未指定時は LLM_PROVIDER 環境変数、"
        "またはAPIキーの設定状況から自動判定します。",
    )
    parser.add_argument(
        "--output",
        default="output_project.sb3",
        help="出力先の .sb3 ファイルパス（デフォルト: output_project.sb3）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    provider = resolve_provider(args.provider)
    llm_call = with_retry(PROVIDER_BUILDERS[provider]())

    user_instruction = (
        args.instruction
        or "画面中央に赤い丸の新しいスプライトを追加して、旗が押されたら10歩動かすプログラムを作って"
    )

    print(f"使用プロバイダ: {provider}")
    print(f"指示を実行中: {user_instruction}")
    try:
        generate_sb3(
            instruction=user_instruction,
            llm_call=llm_call,
            output_path=args.output,
        )
        print(f"生成が完了しました: {args.output}")
    except Exception as e:
        print(f"エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
