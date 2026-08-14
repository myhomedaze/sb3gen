# sb3gen 完全攻略ガイド（日本語版）

自然言語の指示だけで Scratch 3.0 プロジェクト（`.sb3`）を生成・継続編集できる CLI ツール、
**sb3gen** の仕組みと使い方を、実装の中身まで含めて解説します。

---

## 目次

1. [これは何か](#1-これは何か)
2. [必要環境・セットアップ](#2-必要環境セットアップ)
3. [クイックスタート](#3-クイックスタート)
4. [CLIリファレンス](#4-cliリファレンス)
5. [全体アーキテクチャ](#5-全体アーキテクチャ)
6. [指示がプロジェクトに変わるまで（内部の流れ）](#6-指示がプロジェクトに変わるまで内部の流れ)
7. [聞き返し（Clarification）の仕組み](#7-聞き返しclarificationの仕組み)
8. [データモデル（ProjectSpec）](#8-データモデルprojectspec)
9. [対応しているブロック・拡張機能](#9-対応しているブロック拡張機能)
10. [カスタムブロック（マイブロック）](#10-カスタムブロックマイブロック)
11. [アセット（絵・音）の扱い](#11-アセット絵音の扱い)
12. [既存プロジェクトの継続編集（--input）](#12-既存プロジェクトの継続編集--input)
13. [LLM出力の安定化の仕組み](#13-llm出力の安定化の仕組み)
14. [既知の制約・今後の課題](#14-既知の制約今後の課題)
15. [トラブルシューティング](#15-トラブルシューティング)

---

## 1. これは何か

sb3genは、「猫のスプライトを追加してジャンプさせて」のような日本語（または英語）の指示文を
LLM（OpenAIまたはGemini）に解釈させ、Scratch 3.0が読み込める`.sb3`ファイルを直接生成する
Pythonツールです。

特徴：
- **ゼロから新規作成**も、**既存の`.sb3`を読み込んで継続編集**もできる
- 指示が曖昧なときは、エラーで落ちずに**ターミナルで聞き返す**
- スプライトの追加・変更・削除、グローバル変数/リスト/ブロードキャストの変更、
  カスタムブロック（マイブロック）、ペン拡張・音楽拡張のブロックにも対応
- 1回のLLM呼び出しに頼らず、**計画→個別生成**の多段階方式でJSON出力の破損を防ぐ設計

---

## 2. 必要環境・セットアップ

- Python 3.8以上（3.11未満でも動作するよう`typing.Literal`の使い方に配慮済み）
- 依存パッケージ：`pydantic`、および使用するプロバイダに応じて`openai`または`google-genai`

```bash
pip install pydantic openai google-genai
```

APIキーは環境変数で設定します（どちらか使う方だけでよい）：

```bash
# OpenAIを使う場合
export OPENAI_API_KEY="sk-..."

# Geminiを使う場合
export GEMINI_API_KEY="..."
# または
export GOOGLE_API_KEY="..."

# モデル名を変えたい場合（Gemini、省略時は環境変数 GEMINI_MODEL のデフォルト値を使用）
export GEMINI_MODEL="gemini-2.0-flash"
```

両方設定されている場合、明示的に`--provider`を指定しなければ**OpenAIが優先**されます。

---

## 3. クイックスタート

```bash
# 新規プロジェクトをデフォルト指示で作る（引数省略可）
python run.py

# 具体的な指示で新規作成
python run.py "旗が押されたら猫が10歩動くようにして"

# 既存プロジェクトを読み込んで継続編集（同じファイルに上書き保存される）
python run.py --input my_game.sb3 "猫のサイズを2倍にして"
```

生成が完了すると、Scratch（https://scratch.mit.edu/ または Scratch Desktop）で
そのまま`.sb3`ファイルを開いて確認できます。

---

## 4. CLIリファレンス

`run.py`は以下の引数に対応しています。

| 引数 | 種別 | 役割 | 省略時の挙動 |
|---|---|---|---|
| `instruction` | 位置引数（省略可） | やりたいことの自然言語指示 | デフォルト指示（赤い丸のスプライト追加＋10歩移動）を使用 |
| `--provider` | オプション | 使用するLLM（`openai`/`gemini`） | `LLM_PROVIDER`環境変数、無ければ設定済みAPIキーから自動判定（OpenAI優先） |
| `--output` | オプション | 保存先の`.sb3`パス | `--input`があればそこへ上書き、無ければタイムスタンプ付きファイル名を新規生成 |
| `--input` | オプション | 継続編集したい既存の`.sb3` | 空の新規プロジェクトから生成 |
| `--reference` | オプション（複数指定可） | LLMに参考情報として渡すファイル（編集対象にはならない） | 参考情報なしで実行 |

### 使用例

```bash
# プロバイダを明示
python run.py --provider gemini "猫を追加して"

# 出力先を指定
python run.py --output my_game.sb3 "猫を追加して"

# 既存ファイルを読み込み、別名で保存（元ファイルは変更されない）
python run.py --input my_game.sb3 --output my_game_v2.sb3 "猫のサイズを2倍にして"

# 参考ファイルを複数指定（.sb3は疑似コード化、.txt/.md/.json等はそのまま渡される）
python run.py --input my_game.sb3 \
  --reference style_guide.md \
  --reference sample_project.sb3 \
  "sample_project.sb3のジャンプの実装を参考に、このプロジェクトにもジャンプを追加して"
```

`--reference`で渡したファイルの内容自体は書き換わりません。`.sb3`はブロックを疑似コードへ
変換して渡され（最大20,000文字、超過分は省略）、テキスト系拡張子（`.txt` `.md` `.json`
`.csv` `.yaml` `.py` `.html`等）はそのままの内容が渡されます。それ以外の拡張子は
ファイル名のみが伝えられます。存在しないファイルを指定した場合は警告のみで処理は継続します。

---

## 5. 全体アーキテクチャ

```
run.py（CLI・APIキー確認・リトライ制御・--input/--reference読込）
   ↓
sb3gen.main.generate_sb3（全体オーケストレーション・聞き返しループ）
   ↓
sb3gen.patcher.apply_patch
   ├─ plan_instruction … 指示を複数のActionSpecに分解（add/modify/remove_sprite, modify_globals）
   ├─ 各ActionSpecごとに handle_add_sprite / handle_modify_sprite /
   │  handle_remove_sprite / handle_modify_globals を実行
   └─ 成功した操作ごとに linter.reconcile_globals で変数/リスト/
      ブロードキャストの参照漏れをグローバル定義へ自動反映
   ↓
sb3gen.compiler.compile_project（高レベルProjectSpec → Scratchのproject.json）
   ↓
sb3gen.writer.write_sb3（project.json + アセットバイナリを.sb3=ZIPへ）
```

継続編集時（`--input`）は、上記の前段として`sb3gen.reader.read_sb3`が既存の`.sb3`を
`ProjectSpec`へ逆変換し、埋め込みアセット（コスチューム・サウンドのバイナリ）を
アセットレジストリへ再登録します。

---

## 6. 指示がプロジェクトに変わるまで（内部の流れ）

1. **計画立案（`plan_instruction`）**：ユーザーの指示文を、LLMが`ActionPlan`
   （`add_sprite`/`modify_sprite`/`remove_sprite`/`modify_globals`のリスト）に分解します。
   「猫を追加してジャンプさせて、スコア変数も作って」のような複合指示は、
   複数のActionSpecに分解されて順番に実行されます。
2. **各アクションの実行**：
   - `add_sprite`：まずコスチュームの取得方法（テンプレート／SVG機械生成／プレースホルダー）
     をLLMに決めさせ（`AssetDecision`）、実体化。次に「入れ物（shell）＋スクリプト計画＋
     カスタムブロック計画」を1回のLLM呼び出しで決め、スクリプト・カスタムブロック本体は
     **1本ずつ個別に**LLM呼び出しして生成します（詳細は13章）。
   - `modify_sprite`：対象スプライトの現在の状態を疑似コード化してLLMに見せ、
     同様に「shell → スクリプトを1本ずつ再生成」の手順で更新します。
   - `remove_sprite`：対象スプライトをターゲット一覧から除外するだけです。
   - `modify_globals`：現在のグローバル変数/リスト/ブロードキャスト一覧を見せた上で、
     追加・削除の差分（`GlobalsPatch`）をLLMに出力させます。
3. **整合性の自動修復**：各アクションが成功するたびに`reconcile_globals`が走り、
   スクリプトが参照しているのにグローバル定義にもローカル定義にも存在しない
   変数/リスト/ブロードキャストがあれば、自動でグローバル定義へ追加します。
4. **検証**：各アクションの結果は`validate_project_spec`でスキーマ・opcode許可リスト・
   カスタムブロック参照の整合性をチェックされます。
5. **コンパイル・書き出し**：全アクションが成功したら、最終的な`ProjectSpec`を
   `compile_project`でScratchのproject.json形式に変換し、`write_sb3`で`.sb3`として保存します。

途中のアクションが失敗した場合、**それまでに成功した分の変更は保持したまま**エラーを返します
（全部やり直しにはなりません）。

---

## 7. 聞き返し（Clarification）の仕組み

指示が曖昧で`plan_instruction`が判断に迷った場合、LLMは`clarification_needed=true`と
質問リスト（最大3件）を返します。その場合：

1. `generate_sb3`はターミナルに質問を表示し、`input()`で追加回答を受け取ります。
2. 回答は`PendingClarification`に履歴として蓄積され、次回の計画立案時に
   「最初の要望＋これまでの質問と回答」としてLLMに渡されます。
3. これを**最大3ターン**まで繰り返せます（`MAX_CLARIFICATION_TURNS`）。
4. 3ターンを超えても解決しない場合は、定型の案内メッセージを返して処理を打ち切ります。

---

## 8. データモデル（ProjectSpec）

sb3genはScratchのproject.json（低レベルなJSON形式）を直接LLMに書かせるのではなく、
Pydanticで定義した**高レベルなモデル**（`sb3gen/schema.py`）をLLMに生成させ、
それを`compiler.py`が正しいJSON構造へ変換します。主な型は次の通りです。

```
ProjectSpec
├── targets: List[SpriteSpec]        # スプライト＋ステージ（is_stage=True）
├── variables: List[VariableSpec]    # グローバル変数
├── lists: List[ListSpec]            # グローバルリスト
└── broadcasts: List[BroadcastSpec]  # グローバルブロードキャスト

SpriteSpec
├── name, x, y, size, visible
├── costumes: List[CostumeSpec]
├── sounds: List[SoundSpec]
├── variables: List[VariableSpec]    # このスプライト専用のローカル変数
├── scripts: List[ScriptSpec]
└── procedures: List[ProcedureDefinitionSpec]  # このスプライトのカスタムブロック

ScriptSpec
└── blocks: List[BlockSpec]

BlockSpec
├── opcode: str（ALLOWED_OPCODESに含まれるものだけ許可）
├── fields / inputs: Dict[str, Any]
├── substacks: List[List[BlockSpec]]  # if/repeat等の中身
└── proc_name: Optional[str]          # procedures_call専用
```

この中間表現があることで、「LLMにScratch内部のブロックID採番やmutation構造を
一切意識させない」設計になっています（IDの割り振りやmutation組み立ては
`compiler.py`が担当）。

---

## 9. 対応しているブロック・拡張機能

`ALLOWED_OPCODES`（`schema.py`）に列挙されたopcodeのみ使用できます。カテゴリ別に：

- 動き（motion_*）、見た目（looks_*）、音（sound_*）
- イベント（event_*）、制御（control_*、クローン含む）
- 調べる（sensing_*）、演算（operator_*）
- 変数・リスト（data_*）
- **ペン拡張**（`pen_*`）、**音楽拡張**（`music_*`）
- カスタムブロック関連（`procedures_*`、`argument_reporter_*`）

拡張機能ブロック（pen/music）を1つでも使うと、`compile_project`が自動的に
project.jsonの`extensions`配列へ該当IDを追加します。これが無いと、Scratch側で
拡張機能が読み込まれずブロックが正しく動作しないため、重要な自動処理です。

上記以外のopcode（例：`math_number`などのネイティブshadowブロックや、
このツールが対応していない拡張ブロック）はLLMが出力しても`validate_project_spec`で
拒否され、パッチはFAILED扱いになります。

---

## 10. カスタムブロック（マイブロック）

`ProcedureDefinitionSpec`で「名前・引数（文字列/数値 or 真偽値）・warpモード・本体」
を定義できます。呼び出し側は`procedures_call`ブロックの`proc_name`に名前を指定し、
`inputs`には引数名をキーにした値を渡すだけで、Scratch内部の`proccode`文字列や
引数IDへの変換は`compiler.py`が自動的に行います。

生成時も、スクリプトと同様に「シグネチャ（名前・引数・要約）をまず決め、
本体は1個ずつ個別のLLM呼び出しで生成する」という分割方式が取られています。

---

## 11. アセット（絵・音）の扱い

### コスチューム（絵）

新規スプライト追加時、LLMは以下のいずれかの取得方法（`AssetSourceType`）を選びます：

- `template`：`templates/manifest.json`に登録済みのテンプレート（現状は猫`cat.svg`のみ）
- `svg_generate`：プロンプト中の色・図形キーワード（例：「赤い丸」「青い三角」）を検出し、
  放射グラデーション・光沢・接地影付きのSVGを機械生成（複数の色/図形があれば
  1枚に合成、最大4個まで）
- `placeholder`：どちらにも該当しない場合の、名前入りグレーボックス

### サウンド

`register_wav_asset`/`register_wav_template`でWAVファイルを登録できますが、
現状`templates/manifest.json`に`sounds`セクションが未登録のため、
テンプレート音源（効果音等）は同梱されていません（自分で登録するか、
manifestに追加する必要があります）。

### アセット欠落時のフォールバック

コンパイル後に参照先アセットIDがレジストリに見つからない場合、
`writer.py`は**プロジェクト全体を失敗させず**、以下へ自動フォールバックします：

- コスチューム → 名前入りのグレープレースホルダーSVG
- サウンド → 無音の最小限WAV

### Stageの背景

Stage（ステージ）ターゲットが指示に含まれない場合、`compile_project`が
自動的に白背景（480×360、`register_default_backdrop`で正しくレジストリ登録済み）
を持つStageを先頭に追加します。

---

## 12. 既存プロジェクトの継続編集（--input）

`--input`で`.sb3`を指定すると、`reader.read_sb3`が以下を行います：

1. project.json全体を`ProjectSpec`へ逆変換（ブロック木・カスタムブロック定義・
   変数/リスト/ブロードキャストを含む）
2. ZIP内の**全アセットバイナリ**（project.json以外の全ファイル）をレジストリへ再登録

2番目の処理は非常に重要です。これを行わないと、今回の指示で一切触れていない
既存のコスチューム/サウンドまで「アセット欠落」と誤判定され、writerのフォールバックで
全てプレースホルダー・無音に差し替えられてしまいます。

**注意**：このツール自身が過去に生成した`.sb3`の読み込みを主眼にしています。
Scratchエディターで直接保存されたファイルなど、他ツール由来の`.sb3`は
未対応のopcodeを含むことが多く、読み込み時に検証エラーとなる場合があります。

---

## 13. LLM出力の安定化の仕組み（`llm_io.py`）

1回のLLM呼び出しで巨大なJSON（スプライト全体のブロック木など）を出力させると、
トークン上限などで**出力が途中で切れて壊れる**リスクが高くなります。これに対処するため：

- **JSON検証・リトライ**（`generate_json_with_retry`）：パース/検証エラー時、
  「途中で切れた」ケースと「スキーマ違反」ケースを判別し、それぞれに適した
  再試行プロンプトを組み立てて再送します（最大3回）。
- **個別生成**（`generate_items_individually`）：スプライト生成時は、まず
  「スクリプト一覧の要約（何をするか一言ずつ）」と「カスタムブロックのシグネチャ」
  だけを1回で決め、スクリプト・カスタムブロック本体は**1本ずつ独立して**
  LLM呼び出しします。これにより1回あたりの出力サイズが安定して小さく保たれ、
  1本の失敗が他に波及しません。

さらに`run.py`側では、APIのレート制限や一時的な過負荷（503/429等）に対する
**指数バックオフ付き自動リトライ**も別途実装されています（クォータ枯渇のように
待っても解決しないエラーは即座に失敗させ、無駄な待機はしません）。

---

## 14. 既知の制約・今後の課題

- サウンドのテンプレート素材（効果音等）は`manifest.json`に未登録で、同梱されていません。
- 複数背景（レベル切り替えのようなStageの複数コスチューム）は、データモデル上は
  `SpriteSpec.costumes`に複数登録可能ですが、専用の生成ロジック・UIはまだありません。
- ペン拡張・音楽拡張のopcodeは許可リストに載っていますが、`AssetDecision`のような
  「意思決定を助ける中間ステップ」は今のところ用意されておらず、LLMの出力品質に
  そのまま依存します。
- `--input`はこのツール自身が生成した`.sb3`専用です。他ツール製のプロジェクトは
  未対応opcodeの混入により読み込みエラーになることがあります。

---

## 15. トラブルシューティング

| 症状 | 原因・対処 |
|---|---|
| `SyntaxError: invalid syntax`（`schema.py`付近） | Python 3.11未満で`Literal[*tuple(...)]`のようなアンパック構文を使うと発生。現在の実装は`Literal[tuple(...)]`（`*`なし）で3.8以上に対応済み。 |
| `OPENAI_API_KEY`/`GEMINI_API_KEY`が無いと言われる | 使用するプロバイダに応じた環境変数を設定するか、`--provider`で明示指定してください。 |
| 指示がループのように何度も聞き返される | 曖昧な指示だとLLMが`clarification_needed`を返し続けます。具体的なスプライト名や数値を含めて回答してください（3ターンで自動的に打ち切られます）。 |
| 生成された`.sb3`の背景・画像が灰色のプレースホルダーになっている | 参照しているアセットがレジストリに見つからず、自動フォールバックが発動しています。`--input`で読み込んだファイルであれば、埋め込みアセットの再登録処理に問題がないか確認してください。 |
| 既存の`.sb3`（このツール製以外）の読み込みでエラーになる | Scratchエディター等、他ツールが生成した`.sb3`は未対応opcodeを含むことがあり、想定された挙動です。 |
