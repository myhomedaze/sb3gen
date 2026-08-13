import openai
from sb3gen.main import generate_sb3

# OpenAI クライアントの初期化（環境変数 OPENAI_API_KEY が必要です）
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
    # 自然言語の指示から Scratch プロジェクト(.sb3)を生成
    generate_sb3(
        instruction="画面中央に赤い丸の新しいスプライトを追加して、旗が押されたら10歩動かすプログラムを作って",
        llm_call=openai_llm_call,
        output_path="output_project.sb3"
    )
    print("生成が完了しました: output_project.sb3")