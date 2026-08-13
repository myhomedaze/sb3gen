"""
実行用スクリプト (CLI対応・環境変数チェック完備)
"""

from __future__ import annotations

import os
import sys
import openai
from sb3gen.main import generate_sb3

# 10. OpenAI APIキー未設定時のエラーハンドリング
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
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

if __name__ == "__main__":
    # 2. ターミナルから引数として指示を受け取る (CLI対応)
    if len(sys.argv) > 1:
        user_instruction = sys.argv[1]
    else:
        user_instruction = "画面中央に赤い丸の新しいスプライトを追加して、旗が押されたら10歩動かすプログラムを作って"

    print(f"指示を実行中: {user_instruction}")
    try:
        generate_sb3(
            instruction=user_instruction,
            llm_call=openai_llm_call,
            output_path="output_project.sb3"
        )
        print("生成が完了しました: output_project.sb3")
    except Exception as e:
        print(f"エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)