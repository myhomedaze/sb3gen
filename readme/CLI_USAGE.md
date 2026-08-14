`run.py` の全コマンドライン引数を、実行例つきで整理します。

## 基本の使い方

```
python run.py [指示文] [オプション...]
```

指示文（自然言語）は省略可能な位置引数で、省略するとデフォルトの指示（「赤い丸のスプライトを追加して10歩動かす」）が使われます。

---

## 1. `instruction`（位置引数・省略可）

生成・編集内容を自然言語で指定します。オプションではなく、コマンドの最初に書く引数です。

```bash
# 指示あり
python run.py "旗が押されたら猫が10歩動くようにして"

# 指示を省略（デフォルト指示が実行される）
python run.py
```

スペースを含む場合は必ず引用符で囲んでください。

---

## 2. `--provider`（LLMプロバイダの選択）

`openai` か `gemini` のどちらを使うかを指定します。省略時は環境変数`LLM_PROVIDER`、それも無ければ設定済みのAPIキー（`OPENAI_API_KEY`優先）から自動判定されます。

```bash
# OpenAIを明示的に使う
python run.py --provider openai "猫を追加して"

# Geminiを明示的に使う
python run.py --provider gemini "猫を追加して"

# 省略（自動判定に任せる）
python run.py "猫を追加して"
```

---

## 3. `--output`（出力先ファイル）

生成結果を保存する`.sb3`のパスを指定します。

```bash
# 明示的にファイル名を指定（新規作成 or 上書き）
python run.py --output my_game.sb3 "猫を追加して"

# 省略した場合の挙動:
#  - --input も未指定 → output_20260814_153000.sb3 のようなタイムスタンプ付きファイルを自動生成
#  - --input のみ指定 → --input と同じファイルへ上書き保存
python run.py "猫を追加して"                          # → output_..._.sb3 が新規生成される
python run.py --input my_game.sb3 "猫を大きくして"     # → my_game.sb3 に上書き保存
```

---

## 4. `--input`（継続編集する既存ファイル）

読み込んで編集を継続したい既存の`.sb3`ファイルを指定します。**このファイルは実在している必要があります。**

```bash
# my_game.sb3 を読み込み、指示を適用して同じファイルに上書き
python run.py --input my_game.sb3 "猫のサイズを2倍にして"

# 読み込み元とは別名で保存したい場合は --output と組み合わせる
python run.py --input my_game.sb3 --output my_game_v2.sb3 "猫のサイズを2倍にして"
# → my_game.sb3 はそのまま残り、新しく my_game_v2.sb3 が作られる
```

**注意**：このツール自身が生成した`.sb3`専用です。Scratchエディターで直接保存したファイル等は未対応opcodeを含む場合があり、読み込み時にエラーになることがあります。

---

## 5. `--reference`（参考情報ファイル、複数指定可）

**編集対象にはせず**、LLMに参考文脈として渡したいファイルを指定します。`--input`と違い、このファイルの中身が書き換わることはありません。何度でも繰り返し指定できます。

```bash
# 1つだけ参考にする
python run.py --input my_game.sb3 --reference style_notes.txt "スタイルノートに沿って背景を変更して"

# 複数のファイルを参考にする（--reference を繰り返す）
python run.py --input my_game.sb3 \
  --reference style_notes.txt \
  --reference another_project.sb3 \
  "another_project.sb3のジャンプの実装を参考に、このプロジェクトにもジャンプを追加して"
```

ファイルの種類ごとの扱い：

| 拡張子 | 扱い |
|---|---|
| `.sb3` | 内容を疑似コード化してLLMに渡す（アセットのバイナリは編集対象にならない） |
| `.txt` `.md` `.json` `.csv` `.yaml` `.py` `.html` など | テキストとしてそのまま渡す（最大20,000文字、超過分は省略） |
| それ以外（画像・バイナリ等） | 中身は読み込まず、ファイル名のみを参考情報として伝える |

存在しないファイルを指定した場合は警告を出して無視し、処理自体は止まりません。

---

## 全部組み合わせた実践例

```bash
python run.py \
  --provider gemini \
  --input my_game.sb3 \
  --reference style_guide.md \
  --reference sample_project.sb3 \
  --output my_game_v2.sb3 \
  "sample_project.sb3のアニメーション表現とstyle_guide.mdの色使いを参考にして、my_game.sb3のキャラクターを改良して"
```

この場合の動作は：
1. `my_game.sb3`（既存プロジェクト）を読み込む
2. `style_guide.md`と`sample_project.sb3`の内容を「参考情報」としてLLMに渡す（これら自体は変更されない）
3. Geminiで指示を実行
4. 結果を`my_game_v2.sb3`として新規保存（元の`my_game.sb3`は変更されない）

---

## クイックリファレンス表

| オプション | 必須/省略可 | 役割 | 省略時の挙動 |
|---|---|---|---|
| `instruction`（位置引数） | 省略可 | やりたいことの自然言語指示 | デフォルト指示を使用 |
| `--provider` | 省略可 | 使用するLLM（`openai`/`gemini`） | 環境変数/APIキーから自動判定 |
| `--output` | 省略可 | 保存先ファイルパス | `--input`があればそこに上書き、無ければ新規タイムスタンプ生成 |
| `--input` | 省略可 | 継続編集したい既存`.sb3` | 空の新規プロジェクトから生成 |
| `--reference` | 省略可（複数可） | LLMへの参考情報ファイル | 参考情報なしで実行 |
