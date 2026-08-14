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
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

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

# 日次クォータ枯渇など、待っても解消しない種類のエラーを示すキーワード。
# 429/RESOURCE_EXHAUSTED であっても、これらが含まれる場合はリトライしても無駄なので
# 即座に失敗させる（例: Gemini無料枠の1日あたりのリクエスト上限超過）。
_NON_RETRYABLE_QUOTA_MARKERS = (
    "perday",
    "per-day",
    "per day",
)


def _is_retryable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if any(marker in message for marker in _NON_RETRYABLE_QUOTA_MARKERS):
        return False
    return any(marker.lower() in message for marker in _RETRYABLE_MARKERS)


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
        default=None,
        help="出力先の .sb3 ファイルパス（未指定の場合、--inputも未指定なら実行のたびに"
        "タイムスタンプ付きのファイル名を自動生成し、既存ファイルを上書きしません。"
        "--inputのみ指定した場合はそのファイルへ上書き保存します）",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="継続編集したい既存の .sb3 ファイルパス。指定すると、このファイルを読み込んでから"
        "指示を適用します（未指定の場合は空の新規プロジェクトから生成します）。",
    )
    parser.add_argument(
        "--reference",
        action="append",
        default=None,
        metavar="PATH",
        help="生成/編集の際にLLMに参考情報として渡すファイル。何度でも指定可能"
        "（例: --reference notes.txt --reference other.sb3）。--inputとは異なり、"
        "こちらは編集対象にはならず、あくまで参考文脈としてLLMに渡されます。"
        ".sb3ファイルなら擬似コード化して、テキストファイル（.txt/.md/.json等）ならそのままの内容を含めます。",
    )
    return parser.parse_args()


def generate_output_path(directory: Union[str, Path] = ".") -> Path:
    """タイムスタンプ付きの出力先パスを生成する。同名ファイルが既にあれば連番を付ける。"""
    base_dir = Path(directory)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = base_dir / f"output_{timestamp}.sb3"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"output_{timestamp}_{counter}.sb3"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# 参考ファイル（--reference）の読み込み
# ---------------------------------------------------------------------------
# LLMへ渡す文脈が肥大化しすぎないよう、参考ファイル1件あたりの読み込み文字数の上限。
_REFERENCE_MAX_CHARS = 20000

# テキストとしてそのまま読み込んで問題ない拡張子（このリスト以外は原則バイナリ扱いとし、
# 内容は読み込まずファイル名のみを伝える）。
_TEXT_LIKE_SUFFIXES = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".yaml", ".yml",
    ".py", ".js", ".html", ".htm", ".xml", ".log",
}


def _render_sb3_reference(path: Path) -> str:
    """.sb3 ファイルを読み込み、各ターゲットを擬似コードへレンダリングして返す。"""
    from sb3gen.reader import read_sb3
    from sb3gen.renderer import render_sprite_pseudocode

    project = read_sb3(path)
    parts = [render_sprite_pseudocode(t) for t in project.targets]
    text = "\n\n".join(parts)
    if len(text) > _REFERENCE_MAX_CHARS:
        text = text[:_REFERENCE_MAX_CHARS] + "\n...(以降省略)"
    return text


def _render_text_reference(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > _REFERENCE_MAX_CHARS:
        text = text[:_REFERENCE_MAX_CHARS] + "\n...(以降省略)"
    return text


def build_reference_context(paths: Optional[List[str]]) -> str:
    """--reference で指定された各ファイルを読み込み、LLMのuser_promptに前置する
    参考情報ブロックへまとめる。読み込みに失敗したファイルは警告を出して読み飛ばす
    （参考情報の欠落程度で処理全体を止める必要はないため）。
    """
    if not paths:
        return ""

    blocks: List[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            print(f"警告: 参考ファイルが見つかりません（無視します）: {path}", file=sys.stderr)
            continue

        try:
            if path.suffix.lower() == ".sb3":
                content = _render_sb3_reference(path)
                label = f"{path.name}（Scratchプロジェクトの擬似コード）"
            elif path.suffix.lower() in _TEXT_LIKE_SUFFIXES:
                content = _render_text_reference(path)
                label = path.name
            else:
                print(
                    f"警告: 参考ファイル '{path}' はテキストとして解釈できない拡張子のため、"
                    "ファイル名のみを参考情報として伝えます。",
                    file=sys.stderr,
                )
                blocks.append(f"=== 参考: {path.name}（内容は読み込まれていません） ===")
                continue
        except Exception as e:
            print(f"警告: 参考ファイル '{path}' の読み込みに失敗しました（無視します）: {e}", file=sys.stderr)
            continue

        blocks.append(f"=== 参考: {label} ===\n{content}")

    if not blocks:
        return ""

    return "【参考情報（この内容自体は編集対象ではありません）】\n" + "\n\n".join(blocks)


if __name__ == "__main__":
    args = parse_args()

    provider = resolve_provider(args.provider)
    llm_call = with_retry(PROVIDER_BUILDERS[provider]())

    project = None
    if args.input:
        from sb3gen.reader import read_sb3

        input_path = Path(args.input)
        if not input_path.exists():
            print(f"エラー: 指定された入力ファイルが見つかりません: {input_path}", file=sys.stderr)
            sys.exit(1)
        print(f"既存プロジェクトを読み込んでいます: {input_path}")
        try:
            project = read_sb3(input_path)
        except Exception as e:
            print(f"エラー: 既存プロジェクトの読み込みに失敗しました: {e}", file=sys.stderr)
            print(
                "（このツール自身が生成した .sb3 以外（Scratchエディターで直接保存したもの等）は未対応です）",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    elif args.input:
        # 継続編集時はデフォルトで入力ファイルへそのまま上書き保存する（新規生成と違い、
        # 何度指示してもファイルが増え続けないことを期待されると想定されるため）。
        output_path = Path(args.input)
    else:
        output_path = generate_output_path()

    user_instruction = (
        args.instruction
        or "画面中央に赤い丸の新しいスプライトを追加して、旗が押されたら10歩動かすプログラムを作って"
    )

    reference_context = build_reference_context(args.reference)
    if reference_context:
        user_instruction = f"{reference_context}\n\n---\n\n{user_instruction}"

    print(f"使用プロバイダ: {provider}")
    print(f"指示を実行中: {user_instruction}")
    try:
        generate_sb3(
            instruction=user_instruction,
            llm_call=llm_call,
            output_path=output_path,
            project=project,
        )
        print(f"生成が完了しました: {output_path}")
    except Exception as e:
        print(f"エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
