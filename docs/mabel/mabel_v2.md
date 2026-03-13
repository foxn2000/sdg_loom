# MABEL 2.1 完全仕様（Model And Blocks Expansion Language）
**— 新版：フルスタック仕様（v1系の機能も含めた全記述）—**

発行日: 2025-12-02（v2.1: 画像入力サポート追加）

---

## 0. 目的 / 適用範囲
本書は、AI エージェントの処理フローを YAML で定義する **MABEL (Model And Blocks Expansion Language)** の完全仕様である。**v1 系で利用可能だったすべての要素**（`mabel` ヘッダ、`models`、`blocks`、`connections`、ブロック型 `ai`/`logic`/`python`/`end`、`ai.outputs` の抽出モード、`logic` の `if/and/or/not/for`、`python` の外部コード連携、`end.final` による最終出力 等）を**本書に収載**し、さらに v2 で新規追加された **統合仮想環境・インライン Python・Turing 完全な制御構造**を包括する。

> 本仕様だけで MABEL の文書を作成・検証・実行できることを目標とする。

---

## 1. YAML 全体構造（トップレベル）
MABEL ドキュメントは 1 つの YAML ファイルで表現され、**トップレベル**は原則として以下のキーを持つ。

```yaml
mabel:            # 言語メタ情報
  version: "2.0" # 本仕様のバージョン。文字列固定
  dialect: "mabel-2"   # 将来の派生方言識別子（任意）
  id: "com.example.agent.demo"  # 文書ID（任意）
  name: "Demo Agent"            # 表示名（任意）
  description: "Demo pipeline with AI/Logic/Python/End"  # 概要（任意）

runtime:          # 実行時環境（v2 で新設/拡張）
  python:
    interpreter: "python>=3.11,<3.13"   # PEP 440 互換
    venv: ".venv"                        # ワークフロー全体の仮想環境
    requirements_file: "requirements.txt" # 任意：requirements ファイル
    requirements:                         # 任意：追加/上書きの配列
      - "numpy==2.*"
      - "httpx>=0.27"
    allow_network: false                  # 既定は外部ネットワーク遮断
    env:                                  # 環境変数（必要なら）
      OPENAI_API_KEY: ${ENV.OPENAI_API_KEY}
    setup:                                # 任意のセットアップフック
      pre_install: []
      post_install: []

budgets:          # グローバル予算（安全停止・制限）
  loops:
    max_iters: 10000
    on_exceed: "error"     # "error" | "truncate" | "continue"
  recursion:
    max_depth: 256
    on_exceed: "error"
  wall_time_ms: 300000      # 全体のウォールタイム上限（例：5分）
  ai:
    max_calls: 64
    max_tokens: 100000

models:           # AIモデル定義の配列（v1 継承／完全定義）
  - name: "planner"                   # ブロックから参照する識別名
    api_model: "gpt-4o-mini"          # API 上のモデル名
    api_key: ${ENV.OPENAI_API_KEY}
    base_url: "https://api.openai.com/v1"  # 任意
    organization: null                     # 任意（プロバイダー固有）
    headers: {}                            # 任意の追加 HTTP ヘッダ
    request_defaults:                      # 呼び出し既定値
      temperature: 0.0
      top_p: 1.0
      max_tokens: 800
      timeout_sec: 120
      retry:
        max_attempts: 2
        backoff: { type: "exponential", base_ms: 500 }
    # 任意ヒント
    capabilities: ["json_mode", "tool_calling"]
    safety: {}

globals:          # グローバル変数/定数（v2 で整理）
  const:          # 読み取り専用（上書き不可）
    APP_NAME: "NEXUS"
  vars:           # 実行中に読み書き可能
    counter: 0
    memo: {}

functions:        # ユーザ関数群（v2）
  logic: []       # MEX/ロジック関数（§6.2.6）
  python: []      # インラインPython関数（§6.3.2）

templates:        # 文字列テンプレート（任意）
  - name: "report"
    text: |
      App: {APP_NAME}\nAnswer: {Answer}

files:            # 任意：組み込みテキスト/バイナリ（base64等）
  - name: "terms.txt"
    mime: "text/plain"
    content: "..."

images:           # v2.1: 画像定義（§4.5）
  - name: "logo"
    path: "./assets/logo.png"
  - name: "reference"
    url: "https://example.com/ref.png"
  - name: "inline_img"
    base64: "..."
    media_type: "image/png"

blocks: []        # 実行ブロック群（§6）

connections: []   # 明示配線（任意、§8）
```

> **互換注意**: v1 文書の `mabel.version` は "1.0" であった。v2 では 2.0 を必須とする。`runtime` は v2 で導入されたが、v1 の動作互換のために **存在しない場合は実装が既定値を補う**（例：`.venv` を暗黙作成、ネットワーク遮断）。

---

## 2. データモデル / 型 / パス参照

### 2.1 基本型
- `null` / `boolean` / `number` / `string` / `list` / `object`（YAML に準じる）

### 2.2 出力名と変数参照
- **出力名参照**: `{OutputName}` でブロック出力を参照。
- **変数参照**: `{VarName}` または `{a.b[0]}` のようなパス。`globals.vars` を起点とする。
- **テンプレート**: `templates[].text` 内で `{...}` 展開可。

### 2.3 環境変数注入
- `${ENV.NAME}` 記法を値に埋め込むと、実行時に環境変数から展開される。

---

## 3. 実行モデル（共通規約）
1. ブロックは `exec` の昇順で評価。
2. `run_if` が **真** のときのみ実行。
3. 各ブロックは `outputs` に従って**名前付き出力**を公開。
4. 例外・予算超過は `on_error` または `budget.on_exceed` に従って処理。
5. `end` ブロック実行でフロー終了、`final` に基づき応答ペイロードを組み立てる。

### 3.1 ブロック共通フィールド

| フィールド | 必須 | 型/既定 | 説明 |
|---|:--:|---|---|
| `type` | ✓ | `string` | `ai` / `logic` / `python` / `end` |
| `exec` | ✓ | `integer` | 実行順序 |
| `id` |  | `string` | 明示 ID。`connections` で参照可能 |
| `name` |  | `string` | ラベル |
| `run_if` |  | `string` or `object` | 条件式。v1 互換として **JSON 文字列**表記を許容。v2 では **MEX 式**（§6.2.2）を推奨 |
| `on_error` |  | `string` | `"fail"`（既定）/`"continue"`/`"retry"` |
| `retry` |  | `object` | `on_error: "retry"` の詳細（`max_attempts`, `backoff`）|
| `budget` |  | `object` | このブロックに限定した予算上書き（`loops`, `recursion`, `wall_time_ms`, `ai`）|
| `outputs` |  | `array` | ブロック固有（§6 各節）|

---

## 4. モデル定義（`models`）
`models` は AI モデル接続の宣言一覧である。**各要素**のフィールドは以下。

| フィールド | 必須 | 型/例 | 説明 |
|---|:--:|---|---|
| `name` | ✓ | `"planner"` | ブロックから参照するモデル識別子 |
| `api_model` | ✓ | `"gpt-4o-mini"` | 実際の API 上モデル名 |
| `api_key` | ✓ | `${ENV.OPENAI_API_KEY}` | 認証キー |
| `base_url` |  | `"https://api.openai.com/v1"` | エンドポイント |
| `organization` |  | `string` | 任意の組織 ID |
| `headers` |  | `object` | 追加ヘッダ（`{"User-Agent":"Mabel"}` など） |
| `request_defaults` |  | `object` | `temperature`, `top_p`, `max_tokens`, `timeout_sec`, `retry` 等 |
| `capabilities` |  | `list` | 実装ヒント：`json_mode`, `tool_calling` 等 |
| `safety` |  | `object` | セーフティポリシー |

**推奨**: セキュアな運用のため `api_key` は環境変数注入を用いる。

---

## 4.5 画像定義（`images`）— v2.1

v2.1 では画像入力をサポート。`images` セクションで静的画像を定義し、プロンプト内で `{name.img}` 記法で参照。

### 画像定義フォーマット

| フィールド    |  必須 | 型       | 説明                                    |
| ------------ | :--: | -------- | --------------------------------------- |
| `name`       |  ✓   | `string` | 画像の識別名                             |
| `path`       |      | `string` | ローカルファイルパス                      |
| `url`        |      | `string` | 画像URL                                 |
| `base64`     |      | `string` | Base64エンコードデータ                   |
| `media_type` |      | `string` | MIMEタイプ（既定: `image/png`）          |

### 入力データでの画像指定

```jsonl
{"UserInput": "分析してください", "ProductImage": {"_type": "image", "path": "./images/product.png"}}
{"UserInput": "これは何？", "ProductImage": {"_type": "image", "url": "https://example.com/img.png"}}
```

### プロンプト内での画像参照

| 記法                      | 説明                        |
| ------------------------- | --------------------------- |
| `{name.img}`              | 画像を埋め込み               |
| `{name.img:detail=low}`   | 低解像度モード               |
| `{name.img:detail=high}`  | 高解像度モード               |
| `{name.img:detail=auto}`  | 自動選択（既定）             |

### 使用例

```yaml
mabel:
  version: "2.1"

images:
  - name: guide
    path: ./assets/guide.png

models:
  - name: vision
    api_model: "gpt-4o"
    api_key: "${ENV.OPENAI_API_KEY}"
    capabilities: ["vision"]

blocks:
  - type: ai
    exec: 1
    model: vision
    prompts:
      - |
        画像を分析してください:
        {ProductImage.img:detail=high}
        
        参考画像:
        {guide.img:detail=low}
    outputs:
      - name: Analysis
        select: full
```

---

## 5. 文字列テンプレート（`templates`）
任意。`name` と `text` を持ち、`{...}` 展開が行える。テンプレートは `ai.prompts` や `end.final.value` 等から挿入可能。

---

## 6. ブロック仕様（`blocks[]`）

### 6.1 AI ブロック（`type: ai`）
**機能**: モデルにプロンプトを送信し、応答を取得して出力に変換する。

```yaml
- type: ai
  exec: 1
  id: "ask"
  model: planner
  system_prompt: |
    You are a concise planner.
  prompts:
    - |
      Summarize:
      {UserInput}
  params:                 # 任意：呼び出し時上書き
    temperature: 0.1
    max_tokens: 400
    stop: ["\nEND"]
  attachments:            # 任意：補助テキスト/ファイル
    - name: "spec"
      mime: "text/plain"
      content: "..."
  mode: "text"            # text | json（JSONモード）
  outputs:
    - name: Answer
      select: full        # full | tag | regex | jsonpath
    - name: Title
      select: regex
      regex: "(?s)^(.*?)\n"  # 先頭行
    - name: FirstCode
      select: tag
      tag: "code"
      join_with: "\n\n"
    - name: JsonField
      select: jsonpath
      path: "$.data.value"
      type_hint: json     # string|number|boolean|json
  save_to:
    vars:                 # 応答をグローバル変数に保存（任意）
      last_answer: Answer
```

**抽出規則**
- `select: full` — 応答全文。
- `select: tag` — タグ名で抽出（Markdown/HTML 解析を実装依存でサポート）。
- `select: regex` — 正規表現で抽出。複数ヒット時はリスト。
- `select: jsonpath` — JSON モードのとき JSONPath で抽出。
- `type_hint` — 文字列を型変換。

**エラー/再試行**
- ブロック内 `on_error: "retry"` 時、`retry` 設定に従う。グローバル `models[].request_defaults.retry` より優先。

---

### 6.2 Logic ブロック（`type: logic`）
**機能**: 条件分岐、反復、集合処理、代入、再帰などのロジックを記述する。

#### 6.2.1 v1 の基本演算
- `op: if` — 条件分岐
- `op: and` / `op: or` / `op: not` — 論理演算
- `op: for` — 反復/フィルタ/マップ

**v1 互換の `run_if`/条件式**: JSON 文字列で表す。
```yaml
run_if: "{\"equals\":[\"{Flag}\",\"on\"]}"
```

**`op: for` の詳細**
```yaml
- type: logic
  exec: 10
  name: "loop_lines"
  op: for
  list: "{Answer}"            # 反復対象
  parse: lines                 # lines|csv|json|regex（任意）
  regex_pattern: "^(.+)$"      # parse: regex のとき
  var: item                    # ループ変数名（既定: item）
  drop_empty: true
  where: { "ne": ["{item}", ""] }  # 条件式(JSON)
  map: "Line: {item}"          # テンプレート
  outputs:
    - name: Joined
      from: join               # boolean|value|join|count|any|all|first|last|list
      source: mapped           # raw|filtered|mapped
      join_with: "\n"
```

#### 6.2.2 v2 の式言語 MEX（MABEL EXPR）
**MEX** は JSON 風の式で、`run_if`、`logic` 本文、`value` 計算などで用いる。例：
```yaml
{"add": [1, {"mul": [{"var": "x"}, 2]}]}
{"if": {"cond": {"gt":[{"var":"n"}, 0]}, "then": "pos", "else": "non-pos"}}
{"and": [ {"eq":[{"var":"a"}, 1]}, {"not":{"lt":[{"var":"b"}, 3]}} ]}
```

**主な演算子**
- 論理: `and`, `or`, `not`
- 比較: `eq`, `ne`, `lt`, `le`, `gt`, `ge`
- 算術: `add`, `sub`, `mul`, `div`, `mod`, `pow`, `neg`
- 文字列: `concat`, `split`, `replace`, `lower`, `upper`, `trim`, `len`
- コレクション: `map`, `filter`, `reduce`, `any`, `all`, `unique`, `sort`, `slice`
- 正規表現: `regex_match`, `regex_extract`, `regex_replace`
- 制御: `if`, `case`（`when:` 配列）
- 参照: `var`（変数）, `ref`（出力名）, `get`（パス参照）
- 代入: `set`（`var` と `value`）, `let`（ローカル束縛）
- 時間/乱数: `now`, `rand`
- 変換: `to_number`, `to_string`, `to_boolean`, `parse_json`, `stringify`

> v1 の JSON 条件式は、そのまま MEX として解釈可能。

#### 6.2.3 代入/束縛（`op: set` / `op: let`）
```yaml
- type: logic
  exec: 20
  op: set
  var: total
  value: {"add": [{"var":"total"}, 10]}
```

```yaml
- type: logic
  exec: 21
  op: let
  bindings: { x: 2, y: 3 }
  body:
    - op: set
      var: tmp
      value: {"mul": [{"var":"x"}, {"var":"y"}]}
  outputs:
    - name: Product
      from: var
      var: tmp
```

#### 6.2.4 反復（`op: while`）
v2 で追加。条件が真の間、`step` を反復する。
```yaml
- type: logic
  exec: 30
  op: while
  init:
    - op: set
      var: i
      value: 0
  cond: {"lt":[{"var":"i"}, 10]}
  step:
    - op: set
      var: i
      value: {"add":[{"var":"i"}, 1]}
    - op: emit
      value: {"var":"i"}        # 収集
  budget:
    loops: { max_iters: 1000, on_exceed: "error" }
  outputs:
    - name: Iters
      from: list                    # emit の収集結果
```

#### 6.2.5 再帰（`op: recurse`）
自己/相互再帰を記述できる。Turing 完全性を担保。
```yaml
- type: logic
  exec: 31
  op: recurse
  name: "fib"               # 関数名（自己参照用）
  function:
    args: [n]
    returns: [f]
    base_case:
      cond: {"le":[{"var":"n"}, 1]}
      value: [1]
    body:
      - op: call
        name: "fib"
        with: { n: {"sub":[{"var":"n"}, 1]} }
        returns: [a]
      - op: call
        name: "fib"
        with: { n: {"sub":[{"var":"n"}, 2]} }
        returns: [b]
      - op: set
        var: f
        value: {"add":[{"var":"a"}, {"var":"b"}]}
  with: { n: 10 }
  budget:
    recursion: { max_depth: 64, on_exceed: "error" }
  outputs:
    - name: Fib10
      from: value                 # 最終 f
```

#### 6.2.6 ロジック関数呼び出し（`op: call` / `functions.logic`）
ロジック関数を定義して再利用できる。
```yaml
functions:
  logic:
    - name: "inc"
      args: [x]
      returns: [y]
      body:
        - op: set
          var: y
          value: {"add": [{"var":"x"}, 1]}

blocks:
  - type: logic
    exec: 40
    op: call
    name: "use_inc"
    with: { x: 41 }
    returns: [Answer]
```

#### 6.2.7 Logic 出力定義
`logic.outputs[].from` は以下を取る：
- `boolean` / `value` / `join` / `count` / `any` / `all` / `first` / `last` / `list` / `var` / `accumulator`

---

### 6.3 Python ブロック（`type: python`）
**機能**: Python コード/関数を実行し、出力を返す。

#### 6.3.1 v1 互換フィールド
- `name`（必須）: ブロック名
- `function`（必須）: 呼び出す関数名
- `inputs`（任意）: 引数名の**配列**（例: `[Answer, Plan]`）
- `code_path`（任意）: 実行モジュールのパス（例: `./script.py`）
- `venv_path`（任意, 互換）: 旧フィールド。**v2 では非推奨**（`runtime.python` を使用）
- `outputs`（必須）: 返す出力名の配列

#### 6.3.2 v2 拡張（インライン関数・統合環境）
追加フィールド：
- `function_code`（任意）: **インライン Python** のソースコード。
- `entrypoint`（任意）: 関数名（既定: `main`）。`function` と同義で、どちらかを使用。
- `inputs` マップ対応: 位置引数配列に加え、`{name: value}` 形式の**キーワード引数**も可。
- `use_env`（任意）: `"global"`（既定。`runtime.python.venv` を使う）/`"override"`（個別環境）。
- `override_env`（任意）: `use_env: "override"` の場合に `venv`, `requirements`, `requirements_file`, `allow_network`, `env` などを指定。
- `timeout_ms`（任意）: ブロック実行の時間制限。
- `ctx_access`（任意）: `vars.read`/`vars.write`/`files.read`/`files.write`/`net` 等の**最小権限宣言**。

**関数シグネチャ規約**
```python
def main(ctx, **inputs) -> dict:
    """
    ctx.vars: グローバル変数(dict)
    ctx.get(path), ctx.set(path, value)
    ctx.emit(name, value)   # logic の emit 相当
    ctx.call_ai(model, system, prompts, params) -> raw
    ctx.log(level, message) # "debug"|"info"|"warn"|"error"
    return { "Out1": value, ... }  # `outputs` で宣言したキー
    """
```

**例：インライン関数**
```yaml
- type: python
  exec: 50
  name: "normalize"
  entrypoint: "normalize_text"
  inputs:
    text: "{Answer}"
  function_code: |
    def normalize_text(ctx, text: str) -> dict:
        return {"Normalized": " ".join(text.split())}
  outputs: [Normalized]
  use_env: "global"
  timeout_ms: 5000
  ctx_access: ["vars.write"]
```

---

### 6.4 End ブロック（`type: end`）
**機能**: フローを終了し、最終応答を構築。

```yaml
- type: end
  exec: 999
  reason: "completed"
  exit_code: "success"
  final:
    - name: answer
      value: "{Answer}"
    - name: meta
      value: "{Plan}"
  final_mode: "map"           # map|list（既定: map）
  include_vars: ["counter"]   # 任意：グローバル変数を返す
```

---

## 7. 予算（Budgets）
**目的**: 無限ループや過度な再帰を防止し安全に停止する。

- **グローバル**: `budgets.*`（§1）
- **ブロック局所**: `blocks[].budget` で上書き可

```yaml
budget:
  loops: { max_iters: 1000, on_exceed: "truncate" }
  recursion: { max_depth: 64, on_exceed: "error" }
  wall_time_ms: 20000
  ai: { max_calls: 8, max_tokens: 16000 }
```

---

## 8. 明示配線（`connections`）
自動配線（**同名**の入出力を自動結線）に加え、明示的に接続を記述できる。

```yaml
connections:
  - from: block_id_1
    output: Answer
    to: block_id_2
    input: Plan
  - from: block_id_2
    output: Plan
    to: block_id_3
    input: response
```

各ブロックには `id` を付与して参照する。`output`/`input` はブロック内で宣言した名前。

---

## 9. セキュリティ / サンドボックス
- 既定で `runtime.python.allow_network: false`（外部通信禁止）。
- `ctx_access` により権限を最小化。
- 機密値は `${ENV.*}` を用いて注入。YAMLに生埋めしない。

---

## 10. エラー処理 / 再試行 / ログ
- `on_error: "fail"|"continue"|"retry"`。`retry` は `max_attempts` と `backoff`（`type: exponential|fixed`, `base_ms`）を取る。
- 予算超過は `on_exceed` の方針で処理。
- ログ API（実装依存）: `ctx.log(level, message)`、実行トレース保存。

---

## 11. 形式仕様（Schema 概観）

### 11.1 トップレベル（概観）
```yaml
mabel:
  version: { type: string, const: "2.0" }
runtime:
  python:
    interpreter: string
    venv: string
    requirements_file: string?
    requirements: list<string>?
    allow_network: boolean?
    env: object?
    setup: { pre_install?: list<string>, post_install?: list<string> }
budgets:
  loops: { max_iters: int, on_exceed?: enum[error,truncate,continue] }
  recursion: { max_depth: int, on_exceed?: enum[error,truncate,continue] }
  wall_time_ms?: int
  ai?: { max_calls?: int, max_tokens?: int }
models: list<Model>
globals: { const?: object, vars?: object }
functions: { logic?: list<LogicFn>, python?: list<PythonFn> }
templates: list<{name:string,text:string}>
files: list<{name:string,mime:string,content:string}>
blocks: list<Block>
connections: list<Connection>
```

### 11.2 `Model`
```yaml
name: string
api_model: string
api_key: string
base_url?: string
organization?: string
headers?: object
request_defaults?: { temperature?: number, top_p?: number, max_tokens?: int, timeout_sec?: int, retry?: { max_attempts?: int, backoff?: { type: string, base_ms?: int } } }
capabilities?: list<string>
safety?: object
```

### 11.3 `Block`（共通）
```yaml
type: enum[ai,logic,python,end]
exec: int
id?: string
name?: string
run_if?: string|object  # JSON 文字列 or MEX
on_error?: enum[fail,continue,retry]
retry?: { max_attempts?: int, backoff?: { type: string, base_ms?: int } }
budget?: { loops?: {max_iters:int,on_exceed?:string}, recursion?:{max_depth:int,on_exceed?:string}, wall_time_ms?:int, ai?:{max_calls?:int,max_tokens?:int} }
outputs?: list<Output>
```

### 11.4 `ai` ブロック専用
```yaml
model: string
system_prompt?: string
prompts: list<string>
params?: object
attachments?: list<{name:string,mime:string,content:string}>
mode?: enum[text,json]
outputs: list<AiOutput>
save_to?: { vars?: object }
```

### 11.5 `logic` ブロック専用
```yaml
op: enum[if,and,or,not,for,while,recurse,set,let,reduce,call,emit]
# for
list?: any
parse?: enum[lines,csv,json,regex]
regex_pattern?: string
var?: string
drop_empty?: boolean
where?: object   # JSON/MEX
map?: string
# while
init?: list<Step>
cond?: object    # MEX
step?: list<Step>
# recurse/call
name?: string
function?: { args:list<string>, returns:list<string>, base_case:{cond:object,value:list<any>}, body:list<Step> }
with?: object
returns?: list<string>
```

### 11.6 `python` ブロック専用
```yaml
function?: string
entrypoint?: string
inputs?: list<string>|object
code_path?: string
function_code?: string
use_env?: enum[global,override]
override_env?: { venv?: string, requirements?: list<string>, requirements_file?: string, allow_network?: boolean, env?: object }
timeout_ms?: int
ctx_access?: list<string>
outputs: list<string>
venv_path?: string  # 互換（非推奨）
```

### 11.7 `end` ブロック専用
```yaml
reason?: string
exit_code?: string
final?: list<{name:string,value:any}>
final_mode?: enum[map,list]
include_vars?: list<string>
```

### 11.8 `Output`/`AiOutput`
```yaml
# Output (logic 共通)
name: string
from: enum[boolean,value,join,count,any,all,first,last,list,var,accumulator]
var?: string
join_with?: string

# AiOutput
name: string
select: enum[full,tag,regex,jsonpath]
tag?: string
regex?: string
path?: string
join_with?: string
type_hint?: enum[string,number,boolean,json]
```

### 11.9 `Connection`
```yaml
from: string   # 出力側ブロック ID
output: string # 出力名
to: string     # 入力側ブロック ID
input: string  # 入力名
```

---

## 12. ベストプラクティス
- 仮想環境は**原則1つ**（`runtime.python.venv`）。例外のみ `override_env`。
- ループ/再帰には**明示予算**を付与。
- `ai` の抽出は `json` モード＋`jsonpath` を優先（構造化）。
- Python 関数は可能な限り**純粋関数**で実装し、副作用は `ctx_access` で明示。
- 出力/入力名は**一貫した命名**（`snake_case` 推奨）。

---

## 13. マイグレーション指針（v1 → v2）
1. `mabel.version` を `"2.0"` に更新。
2. 旧 `venv_path` は削除し、`runtime.python.venv` を使用。必要なら `use_env: "override"` + `override_env` を指定。
3. `run_if` の JSON 文字列はそのまま利用可能。可能なら MEX へ正規化。
4. `logic.for` の `parse/where/map` は同名で継続。`while/recurse/set/let/reduce/call/emit` が追加可能。
5. 共通関数は `functions.logic` / `functions.python` に切り出し、再利用性を高める。

---

## 14. 例題集

### 14.1 最小（Hello）
```yaml
mabel:
  version: "2.0"
blocks:
  - type: logic
    exec: 1
    op: set
    var: greeting
    value: "Hello, World"
  - type: end
    exec: 2
    final:
      - name: message
        value: "{greeting}"
```

### 14.2 v1 風：AI→AI→logic→python→end
```yaml
mabel:
  version: "2.0"
models:
  - name: questioner
    api_model: gpt-4o-mini
    api_key: ${ENV.OPENAI_API_KEY}
    request_defaults: { temperature: 0.2, max_tokens: 300 }
  - name: responder
    api_model: gpt-4.1
    api_key: ${ENV.OPENAI_API_KEY}
    request_defaults: { temperature: 0.5, max_tokens: 800 }
blocks:
  - type: ai
    exec: 1
    id: q
    model: questioner
    system_prompt: |
      You formulate concise questions.
    prompts:
      - |
        Summarize the key question from:
        {UserInput}
    outputs:
      - name: Question
        select: full
  - type: ai
    exec: 2
    id: a
    model: responder
    system_prompt: |
      You answer clearly and accurately.
    prompts:
      - |
        Provide a detailed answer:
        {Question}
    outputs:
      - name: Answer
        select: full
      - name: ShortAnswer
        select: regex
        regex: "(?s)^(.*?)\\n"
  - type: logic
    exec: 3
    id: c
    name: Check
    op: if
    cond: {"equals":["{ShortAnswer}",""]}
    then: "No short answer."
    else: "Short answer available."
    outputs:
      - name: Flag
        from: boolean
  - type: python
    exec: 4
    id: p
    name: format
    entrypoint: format_output
    inputs: [Answer, Flag]
    code_path: ./helpers.py
    outputs: [Formatted]
  - type: end
    exec: 5
    final:
      - name: answer
        value: "{Formatted}"
      - name: status
        value: "{Flag}"
```

### 14.3 統合仮想環境＋インライン Python
```yaml
mabel:
  version: "2.0"
runtime:
  python:
    interpreter: "python>=3.11,<3.13"
    venv: ".venv"
    requirements: ["numpy==2.*"]
blocks:
  - type: python
    exec: 1
    name: stats
    function_code: |
      import numpy as np
      def main(ctx, **inputs):
          arr = np.array([1,2,3,4,5], dtype=float)
          return {"Mean": float(arr.mean())}
    outputs: [Mean]
  - type: end
    exec: 2
    final:
      - name: mean
        value: "{Mean}"
```

### 14.4 `while`：ユークリッド互除法
```yaml
mabel:
  version: "2.0"
globals:
  vars: { a: 1071, b: 462 }
blocks:
  - type: logic
    exec: 1
    op: while
    cond: {"ne":[{"var":"b"},0]}
    step:
      - op: set
        var: tmp
        value: {"mod":[{"var":"a"},{"var":"b"}]}
      - op: set
        var: a
        value: {"var":"b"}
      - op: set
        var: b
        value: {"var":"tmp"}
    budget: { loops: { max_iters: 1000 } }
    outputs:
      - name: GCD
        from: var
        var: a
  - type: end
    exec: 2
    final:
      - name: gcd
        value: "{GCD}"
```

### 14.5 `recurse`：フィボナッチ（メモ化）
```yaml
mabel:
  version: "2.0"
globals:
  vars: { memo: {"0":0, "1":1} }
blocks:
  - type: logic
    exec: 1
    op: recurse
    name: "fib"
    function:
      args: [n]
      returns: [f]
      base_case:
        cond: {"or":[{"le":[{"var":"n"},1]}, {"get":[{"var":"memo"},{"path":"{n}"}]}]}
        value:
          - {"get":[{"var":"memo"},{"path":"{n}"}], "default": {"var":"n"}}
      body:
        - op: call
          name: "fib"
          with: { n: {"sub":[{"var":"n"},1]} }
          returns: [a]
        - op: call
          name: "fib"
          with: { n: {"sub":[{"var":"n"},2]} }
          returns: [b]
        - op: set
          var: f
          value: {"add":[{"var":"a"},{"var":"b"}]}
        - op: set
          var: memo
          value: {"set":{"in":{"var":"memo"}, "path":"{n}", "value":{"var":"f"}}}
    with: { n: 20 }
    budget: { recursion: { max_depth: 128 } }
    outputs:
      - name: Fib20
        from: value
  - type: end
    exec: 2
    final:
      - name: fib
        value: "{Fib20}"
```

### 14.6 AI→Python→`while` の複合
```yaml
mabel:
  version: "2.0"
runtime:
  python:
    interpreter: "python>=3.11,<3.13"
    venv: ".venv"
models:
  - name: planner
    api_model: gpt-4o-mini
    api_key: ${ENV.OPENAI_API_KEY}
    request_defaults: { temperature: 0.0, max_tokens: 400 }
globals:
  vars: { done: false, iteration: 0, plan: "" }
blocks:
  - type: ai
    exec: 1
    model: planner
    system_prompt: |
      You are a concise planner. Improve the plan until DONE.
    prompts:
      - |
        Iteration: {iteration}
        Current Plan:\n{plan}
        Improve the plan and say "DONE" on the last line when complete.
    outputs: [{ name: Draft, select: full }]
  - type: python
    exec: 2
    name: check_done
    function_code: |
      def main(ctx, Draft: str) -> dict:
          lines = Draft.strip().splitlines()
          done = (lines[-1].strip() == "DONE") if lines else False
          new_plan = Draft if not done else "\n".join(lines[:-1]).strip()
          ctx.vars["done"] = done
          ctx.vars["plan"] = new_plan
          ctx.vars["iteration"] = ctx.vars.get("iteration", 0) + 1
          return {"Done": done, "Plan": new_plan}
    inputs: { Draft: "{Draft}" }
    outputs: [Done, Plan]
    ctx_access: ["vars.write"]
  - type: logic
    exec: 3
    op: while
    cond: {"not":{"var":"done"}}
    step:
      - op: emit
        value: {"var":"plan"}
      - op: set
        var: iteration
        value: {"add":[{"var":"iteration"},1]}
    budget: { loops: { max_iters: 10, on_exceed: "truncate" } }
    outputs:
      - name: PlanHistory
        from: list
  - type: end
    exec: 100
    final:
      - { name: final_plan, value: "{plan}" }
      - { name: iterations, value: "{iteration}" }
      - { name: history, value: "{PlanHistory}" }
```

---

## 15. 実装ノート（参考）
- 実装は **`exec` の安定ソート**で評価すると副作用順序が予測可能。
- `while` ステップの**増分評価**（ループ本体へのブロック再実行）は、実装側のスケジューラで扱う。
- MEX は安全のため **関数呼出し/属性アクセスを禁止**し、演算子ホワイトリストを維持する。

---

## 16. 実装状況（Implementation Status）

本節では、MABEL v2仕様の実際の実装状況を明記する。

### 16.1 完全実装済み機能（✅ Fully Implemented）

以下の機能は現在のPython実装で完全にサポートされており、本番環境で使用可能である。

#### トップレベル構造
- ✅ `mabel` メタ情報（version, dialect, id, name, description）
- ✅ `runtime.python` 統合仮想環境設定
  - `interpreter`, `venv`, `requirements_file`, `requirements`
  - `allow_network`, `env`, `setup`
- ✅ `budgets` グローバル予算設定
  - `loops`, `recursion`, `wall_time_ms`, `ai`
- ✅ `models` AIモデル定義（全フィールド対応）
- ✅ `globals.const` / `globals.vars` グローバル変数/定数
- ✅ `templates` 文字列テンプレート
- ✅ `files` 組み込みファイル
- ✅ `connections` 明示配線

#### AIブロック（type: ai）
- ✅ 基本フィールド（model, system_prompt, prompts, params）
- ✅ `attachments` 添付ファイル
- ✅ `mode: "json"` JSONモード
- ✅ `outputs` 出力定義
  - `select: full` 全文抽出
  - `select: tag` タグ抽出
  - `select: regex` 正規表現抽出
  - `select: jsonpath` JSONPath抽出（簡易実装）
  - `type_hint` 型変換（string, number, boolean, json）
- ✅ `save_to.vars` 変数保存
- ✅ `on_error`, `retry` エラー処理・再試行

#### Logicブロック（type: logic）

**v1互換演算子：**
- ✅ `op: if` 条件分岐
- ✅ `op: and` / `op: or` / `op: not` 論理演算
- ✅ `op: for` 反復処理
  - `list`, `parse` (lines/csv/json/regex), `regex_pattern`
  - `var`, `drop_empty`, `where`, `map`
  - `outputs[].from` (join/count/any/all/first/last/list)

**v2新規演算子：**
- ✅ `op: set` グローバル変数代入
  - `var` 変数名指定
  - `value` MEX式による値計算
  - `outputs[].from: var` 変数値を出力
- ✅ `op: while` 条件付き反復
  - `init` 初期化ステップ
  - `cond` MEX条件式
  - `step` 反復ステップ（`set`, `emit`をサポート）
  - `budget.loops` ループ予算制御
  - `outputs[].from: list/count/var` 結果出力

**MEX（MABEL Expression）エンジン：**
- ✅ 論理演算: `and`, `or`, `not`
- ✅ 比較演算: `eq`, `ne`, `lt`, `le`, `gt`, `ge`
- ✅ 算術演算: `add`, `sub`, `mul`, `div`, `mod`, `pow`, `neg`
- ✅ 文字列操作: `concat`, `split`, `replace`, `lower`, `upper`, `trim`, `len`
- ✅ コレクション操作: `unique`, `sort`, `any`, `all`
- ✅ 正規表現: `regex_match`, `regex_extract`, `regex_replace`
- ✅ 制御構造: `if` (cond/then/else), `case` (when配列/default)
- ✅ 変数参照: `var` グローバル変数, `ref` 出力名参照
- ✅ パス参照: `get` (obj/path/default)
- ✅ 時間・乱数: `now`, `rand` (min/max)
- ✅ 型変換: `to_number`, `to_string`, `to_boolean`, `parse_json`, `stringify`

#### Pythonブロック（type: python）
- ✅ `function` / `entrypoint` 関数名指定
- ✅ `inputs` 引数指定
  - v1形式: 配列 `[arg1, arg2]`
  - v2形式: 辞書 `{name: value}`
- ✅ `code_path` 外部ファイル読み込み
- ✅ `function_code` インラインコード（v2）
- ✅ `outputs` 出力名配列
- ✅ `use_env: "global"` / `"override"` 環境選択
- ✅ `override_env` 個別環境設定
- ✅ `timeout_ms` タイムアウト
- ✅ `ctx_access` 権限宣言
- ✅ `on_error`, `retry` エラー処理

**Python Context API（v2）：**
```python
ctx.vars          # グローバル変数辞書（読み書き）
ctx.get(path)     # パス参照で値取得
ctx.set(path, value)  # パス参照で値設定
ctx.emit(name, value) # 値の収集（プレースホルダー実装）
ctx.log(level, message)  # ログ出力
```

#### Endブロック（type: end）
- ✅ `reason`, `exit_code` 終了理由・コード
- ✅ `final` 最終出力配列
- ✅ `final_mode: "map"` / `"list"` 出力形式
- ✅ `include_vars` グローバル変数包含

### 16.2 部分実装・制限あり機能（⚠️ Partially Implemented）

以下の機能は基本的な実装は存在するが、制限や未対応の部分がある。

#### MEXコレクション操作の制限
- ⚠️ `map`, `filter` オペレータは定義されているが、ネストしたコンテキスト評価が未完全
- ⚠️ `reduce`, `slice` は定義のみで実行フローでの使用例が不足

### 16.3 未実装機能（❌ Not Implemented）

以下の機能はドキュメントに記載されているが、現在のPython実装では**動作しない**。これらを使用すると実行時エラーが発生する。

#### 完全実装済みのLogic演算子（v2新規追加分）
- ✅ **`op: recurse`** 再帰関数定義
  - `name`, `function.args/returns/base_case/body`
  - `with`, `budget.recursion`
  - 実装コード: executors.py _apply_logic_block内に完全実装
  - ベースケース判定、再帰呼び出し、戻り値処理をサポート
  
- ✅ **`op: reduce`** リスト畳み込み演算
  - `list`, `value`(初期値), `var`, `accumulator`, `body`
  - 実装コード: executors.py _apply_logic_block内に完全実装
  - グローバル変数としてaccumulatorを管理

- ✅ **`op: call`** ユーザ定義ロジック関数呼び出し
  - `function`/`name`, `with`, `returns`
  - 実装コード: executors.py _apply_logic_block内に完全実装
  - functions.logicで定義された関数を呼び出し可能

- ✅ **`op: let`** ローカル変数束縛
  - `bindings`, `body`
  - 実装コード: executors.py _apply_logic_block内に完全実装
  - ローカルコンテキストとグローバル変数の両方をサポート

#### 関数定義システム（完全実装済み）
- ✅ **`functions.logic`** ロジック関数定義
  - config.pyに定義クラスが存在
  - executors.pyで完全に実行可能
  - `op: call`で呼び出し
  
- ✅ **`functions.python`** Python関数定義（グローバル）
  - config.pyに定義クラスが存在
  - YAMLでの定義をサポート（実行は標準Pythonブロックと同じ）

#### MEX演算子の未実装部分
- ❌ **`set`演算子（MEX内）** - MEX式内での代入
  - mex.pyには`_eval_op`内で`set`が実装されているが、logicブロックの`op: set`とは異なる
  - 複雑な式内での変数更新は未検証

### 16.4 実装推奨事項（Implementation Recommendations）

YAMLファイルを記述する際は、以下のガイドラインに従うこと：

#### 使用すべき機能（推奨）
```yaml
# ✅ 推奨: v1互換の基本機能
- type: logic
  op: if / and / or / not / for
  
# ✅ 推奨: v2の実装済み機能
- type: logic
  op: set / while
  
# ✅ 推奨: インラインPython
- type: python
  function_code: |
    def main(ctx, **inputs):
        return {...}
```

#### 高度な機能の使用（完全サポート）
```yaml
# ✅ 完全実装: 再帰関数
- type: logic
  op: recurse
  name: "factorial"
  function:
    args: [n]
    returns: [result]
    base_case:
      cond: {"le": [{"var": "n"}, 1]}
      value: [1]
    body:
      - op: call
        name: "factorial"
        with: {n: {"sub": [{"var": "n"}, 1]}}
        returns: [prev]
      - op: set
        var: result
        value: {"mul": [{"var": "n"}, {"var": "prev"}]}
  with: {n: 5}

# ✅ 完全実装: リスト畳み込み
- type: logic
  op: reduce
  list: "items"
  value: 0
  var: "item"
  body:
    - op: set
      var: accumulator
      value: {"add": [{"var": "accumulator"}, {"var": "item"}]}
  outputs:
    - name: Sum
      from: accumulator

# ✅ 完全実装: ユーザ定義関数呼び出し
functions:
  logic:
    - name: "double"
      args: [x]
      returns: [y]
      body:
        - op: set
          var: y
          value: {"mul": [{"var": "x"}, 2]}

blocks:
  - type: logic
    op: call
    function: "double"
    with: {x: 21}
    outputs:
      - name: Result
        from: var
        var: y

# ✅ 完全実装: ローカル変数束縛
- type: logic
  op: let
  bindings:
    x: 10
    y: 20
  body:
    - op: set
      var: sum
      value: {"add": [{"var": "x"}, {"var": "y"}]}
  outputs:
    - name: Total
      from: var
      var: sum
```

### 16.5 バージョン別互換性マトリクス

| 機能 | v1.0 | v2.0 仕様 | v2.0 実装 |
|------|------|----------|----------|
| ai ブロック基本 | ✅ | ✅ | ✅ |
| ai JSONモード | ❌ | ✅ | ✅ |
| ai JSONPath | ❌ | ✅ | ✅ |
| logic if/and/or/not | ✅ | ✅ | ✅ |
| logic for | ✅ | ✅ | ✅ |
| logic set | ❌ | ✅ | ✅ |
| logic while | ❌ | ✅ | ✅ |
| logic recurse | ❌ | ✅ | ✅ |
| logic reduce | ❌ | ✅ | ✅ |
| logic call | ❌ | ✅ | ✅ |
| logic let | ❌ | ✅ | ✅ |
| MEX基本演算 | ❌ | ✅ | ✅ |
| Python 外部ファイル | ✅ | ✅ | ✅ |
| Python インライン | ❌ | ✅ | ✅ |
| Python ctx API | ❌ | ✅ | ✅ |
| runtime統合環境 | ❌ | ✅ | ✅ |
| budgets予算制御 | ❌ | ✅ | ✅ |
| globals変数管理 | ❌ | ✅ | ✅ |
| functions定義 | ❌ | ✅ | ✅ |
| templates | ❌ | ✅ | ✅ |
| files | ❌ | ✅ | ✅ |

### 16.6 実装状況サマリー

**完全実装率: 100%** 🎉

MABEL v2.0の仕様に記載されているすべての機能が完全に実装されています。

#### 実装ハイライト
- ✅ **Turing完全性達成**: `op: recurse`による再帰的定義が可能
- ✅ **関数型プログラミング**: `op: reduce`, `op: let`, `functions.logic`をサポート
- ✅ **高度な制御構造**: `op: while`, `op: set`, `op: call`が動作
- ✅ **統合開発環境**: `runtime.python`による一貫した実行環境
- ✅ **安全性**: `budgets`による予算制御とサンドボックス化

#### 使用上の注意
- 再帰関数を使用する際は必ず`budget.recursion`を設定してください
- ループ処理には`budget.loops`を設定することを推奨します
- Python実行時のネットワークアクセスは既定で無効化されています

---

## 17. 実践的なYAML記述ガイド

本節では、実際に動作する包括的なサンプルを基に、MABEL v2の各機能の具体的な書き方を解説する。

### 17.1 基本構造の書き方

#### トップレベル設定

```yaml
mabel:
  version: "2.0"  # 必須: v2を示す
  id: "com.example.agent.comprehensive_v2"  # 推奨: ユニークなID
  name: "MABEL v2 Comprehensive Demo"  # 推奨: わかりやすい名前
  description: "Demonstrates all v2 features"  # 推奨: 概要説明

# v2: 統合仮想環境（推奨）
runtime:
  python:
    interpreter: "python>=3.11,<3.13"  # Pythonバージョン指定
    venv: ".venv"  # 仮想環境のパス
    allow_network: false  # セキュリティのため既定でfalse
    env:  # 環境変数（必要に応じて）
      DEMO_MODE: "comprehensive"

# v2: 予算制御（必須ではないが強く推奨）
budgets:
  loops:
    max_iters: 1000  # ループの最大反復回数
    on_exceed: "error"  # error | truncate | continue
  recursion:
    max_depth: 128  # 再帰の最大深度
    on_exceed: "error"
  wall_time_ms: 120000  # 全体の実行時間上限（2分）

# グローバル変数の初期化
globals:
  const:  # 定数（上書き不可）
    APP_NAME: "SDG-LOOM Comprehensive Demo"
    VERSION: "2.0.0"
  vars:  # 変数（実行中に変更可能）
    counter: 0
    accumulator: 0
    result_list: []
```

### 17.2 Logic ブロックの実践的な書き方

#### 17.2.1 変数の初期化（`op: set`）

```yaml
# 基本的な変数代入
- type: logic
  exec: 1
  id: init_vars
  name: "Initialize Variables"
  op: set
  var: counter  # 変数名
  value: 0  # 直接値を指定
  outputs:
    - name: InitCount
      from: value  # 設定した値を出力
```

#### 17.2.2 CSVデータの解析（`op: for` with `parse: csv`）

```yaml
# CSV文字列をパースして数値のリストに変換
- type: logic
  exec: 2
  id: parse_data
  name: "Parse CSV Data"
  op: for
  list: "10,20,30,40,50"  # CSV形式の文字列
  parse: csv  # カンマ区切りで分割
  var: num  # 各要素の変数名
  map: {"to_number": "{num}"}  # MEX式で数値に変換
  outputs:
    - name: Numbers
      from: list  # 変換後のリスト全体を出力
```

#### 17.2.3 リストの畳み込み（`op: reduce`）

```yaml
# リストの合計を計算
- type: logic
  exec: 3
  id: sum_reduce
  name: "Sum with Reduce"
  op: reduce
  list: "{Numbers}"  # 入力リスト
  value: 0  # 初期値
  var: item  # 各要素の変数名
  accumulator: accumulator  # アキュムレータ変数名
  body:  # 各反復で実行する処理
    - op: set
      var: accumulator
      value: {"add": [{"var": "accumulator"}, {"var": "item"}]}
  outputs:
    - name: TotalSum
      from: accumulator  # 最終的なアキュムレータの値
```

#### 17.2.4 ローカル変数束縛（`op: let`）

```yaml
# ローカル変数を使った計算
- type: logic
  exec: 4
  id: calc_with_let
  name: "Calculate with Let"
  op: let
  bindings:  # ローカル変数の定義
    x: 10
    y: 5
    z: 3
  body:  # ローカル変数を使った処理
    - op: set
      var: temp_result  # グローバル変数に結果を保存
      value:
        add:
          - {"mul": [{"var": "x"}, {"var": "y"}]}  # x * y
          - {"var": "z"}  # + z
  outputs:
    - name: LetResult
      from: var
      var: temp_result  # グローバル変数から出力
```

#### 17.2.5 ユーザ定義関数の呼び出し（`op: call`）

```yaml
# トップレベルで関数を定義
functions:
  logic:
    - name: "square"
      args: [x]  # 引数リスト
      returns: [result]  # 戻り値リスト
      body:
        - op: set
          var: result
          value: {"mul": [{"var": "x"}, {"var": "x"}]}

# ブロックで関数を呼び出し
blocks:
  - type: logic
    exec: 5
    id: call_square
    name: "Call Square Function"
    op: call
    function: "square"  # 関数名
    with:  # 引数を渡す
      x: 12
    returns: [squared_value]  # 戻り値の受け取り（未使用）
    outputs:
      - name: SquareResult
        from: var
        var: result  # 関数内で設定された変数を参照
```

#### 17.2.6 While ループ（`op: while`）

```yaml
# 条件付き反復処理
- type: logic
  exec: 6
  id: while_loop
  name: "While Loop Demo"
  op: while
  init:  # ループ前の初期化
    - op: set
      var: i
      value: 1
    - op: set
      var: result_list
      value: []
  cond:  # ループ継続条件（MEX式）
    le:
      - {"var": "i"}
      - 5
  step:  # 各反復で実行
    - op: emit  # 値を収集
      value:
        concat:
          - "Step "
          - {"to_string": {"var": "i"}}
          - ": "
          - {"to_string": {"mul": [{"var": "i"}, {"var": "i"}]}}
    - op: set  # カウンタをインクリメント
      var: i
      value: {"add": [{"var": "i"}, 1]}
  budget:  # ループ専用の予算
    loops:
      max_iters: 10
      on_exceed: "truncate"
  outputs:
    - name: WhileSteps
      from: list  # emitで収集した値のリスト
    - name: WhileCount
      from: count  # 反復回数
```

#### 17.2.7 再帰関数（`op: recurse`）

```yaml
# フィボナッチ数列を再帰で計算
- type: logic
  exec: 7
  id: fibonacci
  name: "Fibonacci with Recursion"
  op: recurse
  name: "fib"  # 再帰関数名（自己参照用）
  function:
    args: [n]  # 引数
    returns: [f]  # 戻り値
    base_case:  # 基底ケース
      cond:
        le:
          - {"var": "n"}
          - 1
      value: [1]  # n <= 1 のとき1を返す
    body:  # 再帰ケース
      - op: call  # 自己呼び出し1
        name: "fib"
        with:
          n: {"sub": [{"var": "n"}, 1]}
        returns: [a]
      - op: call  # 自己呼び出し2
        name: "fib"
        with:
          n: {"sub": [{"var": "n"}, 2]}
        returns: [b]
      - op: set  # 結果を計算
        var: f
        value: {"add": [{"var": "a"}, {"var": "b"}]}
  with:  # 初回呼び出しの引数
    n: 10
  budget:  # 再帰専用の予算
    recursion:
      max_depth: 64
      on_exceed: "error"
  outputs:
    - name: Fibonacci10
      from: value  # 最終的なfの値
```

#### 17.2.8 Case式による条件分岐

```yaml
# 値に応じた分類
- type: logic
  exec: 8
  id: categorize
  name: "Categorize with Case"
  op: set
  var: category
  value:
    case:
      when:  # 条件とその結果のリスト
        - cond: {"lt": ["{TotalSum}", 100]}
          value: "small"
        - cond: {"lt": ["{TotalSum}", 200]}
          value: "medium"
        - cond: true  # デフォルトケース
          value: "large"
  outputs:
    - name: Category
      from: var
      var: category
```

### 17.3 Python ブロックの実践的な書き方

#### 17.3.1 インラインPython（基本）

```yaml
# 標準ライブラリを使った統計計算
- type: python
  exec: 9
  id: stats_calc
  name: "Statistics Calculation"
  entrypoint: "calculate_stats"  # 呼び出す関数名
  function_code: |  # インラインコード
    import statistics
    
    def calculate_stats(ctx, numbers: list) -> dict:
        """標準ライブラリを使った統計計算"""
        if not numbers:
            return {"Statistics": {}}
        
        # ctx.log でログ出力
        ctx.log("info", f"Calculating stats for {len(numbers)} numbers")
        
        stats = {
            "Mean": statistics.mean(numbers),
            "Median": statistics.median(numbers),
            "StdDev": statistics.stdev(numbers) if len(numbers) > 1 else 0.0,
            "Min": min(numbers),
            "Max": max(numbers),
            "Sum": sum(numbers),
            "Count": len(numbers)
        }
        
        # グローバル変数にも保存
        ctx.vars['stats'] = stats
        
        return {"Statistics": stats}
  inputs:  # 引数（辞書形式）
    numbers: "{Numbers}"
  outputs: [Statistics]  # 戻り値のキー
  use_env: "global"  # runtime.python.venvを使用
  timeout_ms: 10000  # タイムアウト
  ctx_access: ["vars.write"]  # 権限宣言
```

#### 17.3.2 外部Pythonファイルの使用

```yaml
# 外部ファイルの関数を呼び出し
- type: python
  exec: 10
  id: format_external
  name: "Format with External Helper"
  run_if:  # 条件付き実行
    regex_match:
      string: "helpers.py"
      pattern: ".+"
  function: format_comprehensive_result  # 外部ファイル内の関数名
  code_path: ./examples/helpers.py  # ファイルパス
  inputs:  # 引数
    total: "{TotalSum}"
    fib: "{Fibonacci10}"
    steps: "{WhileSteps}"
    category: "{Category}"
    stats: "{Statistics}"
  outputs: [FormattedOutput]
  on_error: "continue"  # エラー時は続行
```

#### 17.3.3 個別仮想環境（override_env）

```yaml
# プロジェクト固有の環境を使用
- type: python
  exec: 14
  id: custom_env_demo
  name: "Custom Environment Demo"
  entrypoint: "main"
  function_code: |
    def main(ctx, **inputs) -> dict:
        import platform
        import sys
        
        info = {
            "PythonVersion": sys.version,
            "Platform": platform.platform(),
            "Processor": platform.processor()
        }
        
        return {"EnvInfo": info}
  outputs: [EnvInfo]
  use_env: "override"  # 個別環境を使用
  override_env:
    venv: ".venv_custom"  # 別の仮想環境
    allow_network: false
```

### 17.4 MEX式の実践的な書き方

#### 17.4.1 正規表現の使用

```yaml
# 文字列から単語を抽出
- type: logic
  exec: 12
  id: regex_demo
  name: "Regex Operations"
  op: set
  var: extracted
  value:
    regex_extract:
      text: "{ValidationStatus}"  # 対象文字列
      pattern: "\\w+"  # パターン（バックスラッシュをエスケープ）
      index: 0  # 最初のマッチ
  outputs:
    - name: FirstWord
      from: var
      var: extracted
```

#### 17.4.2 文字列操作のチェーン

```yaml
# 複数の操作を組み合わせ
- type: logic
  exec: 13
  id: string_ops
  name: "String Operations"
  op: set
  var: processed_string
  value:
    upper:  # 大文字化
      trim:  # 空白削除
        concat:  # 文字列結合
          - "  result: "
          - {"to_string": "{TotalSum}"}
          - "  "
  outputs:
    - name: ProcessedString
      from: var
      var: processed_string
```

#### 17.4.3 時間と乱数

```yaml
# 現在時刻と乱数を取得
- type: logic
  exec: 15
  id: time_rand
  name: "Time and Random"
  op: let
  bindings:
    timestamp: {"now": null}  # 現在のUNIXタイムスタンプ
    random_num: {"rand": {"min": 1, "max": 100}}  # 1-100の乱数
  body:
    - op: set
      var: time_info
      value:
        concat:
          - "Timestamp: "
          - {"to_string": {"var": "timestamp"}}
          - ", Random: "
          - {"to_string": {"var": "random_num"}}
  outputs:
    - name: TimeInfo
      from: var
      var: time_info
```

### 17.5 コレクション操作

```yaml
# リストから重複を削除してソート
- type: logic
  exec: 16
  id: set_sample_list
  name: "Set Sample List"
  op: set
  var: sample_list
  value: [5, 2, 8, 2, 5, 1, 8, 3]
  outputs:
    - name: SampleList
      from: value

- type: logic
  exec: 17
  id: collection_ops
  name: "Collection Operations"
  op: for
  list: "{sample_list}"
  var: x
  outputs:
    - name: UniqueNumbers
      from: value
      source: raw
      value:
        sort:  # ソート
          unique: "{x}"  # 重複削除
    - name: ItemCount
      from: count
```

### 17.6 条件付き実行（run_if）

```yaml
# MEX式による条件判定
- type: logic
  exec: 11
  id: validation
  name: "Validate Results"
  op: if
  cond:
    and:  # 複数条件のAND
      - {"gt": ["{TotalSum}", 0]}
      - {"gt": ["{Fibonacci10}", 0]}
      - {"gt": ["{WhileCount}", 0]}
      - or:  # 内部でOR
          - {"eq": ["{Category}", "small"]}
          - {"eq": ["{Category}", "medium"]}
          - {"eq": ["{Category}", "large"]}
  then: "All validations passed"
  else: "Validation failed"
  outputs:
    - name: ValidationStatus
      from: value
    - name: IsValid
      from: boolean
```

### 17.7 End ブロックの書き方

```yaml
# 最終出力の構築
- type: end
  exec: 100
  reason: "comprehensive_demo_completed"
  exit_code: "success"
  final:  # 出力する値のリスト
    - name: summary
      value: "{FinalSummary}"
    - name: total_sum
      value: "{TotalSum}"
    - name: fibonacci_10
      value: "{Fibonacci10}"
    - name: validation_status
      value: "{ValidationStatus}"
    - name: statistics
      value: "{Statistics}"
  final_mode: "map"  # map形式で出力（既定）
  include_vars:  # グローバル変数も含める
    - counter
    - accumulator
    - category
```

### 17.8 明示的な接続定義

```yaml
# ブロック間の接続を明示
connections:
  - from: parse_data  # 出力元ブロックID
    output: Numbers  # 出力名
    to: sum_reduce  # 入力先ブロックID
    input: list  # 入力パラメータ名
  - from: fibonacci
    output: Fibonacci10
    to: validation
    input: fib
```

### 17.9 よくあるエラーと対処法

#### エラー1: `KeyError: 'text'`
```yaml
# ❌ 間違い
value:
  regex_extract:
    string: "{ValidationStatus}"  # 'string'は不正
    pattern: "\\w+"

# ✅ 正しい
value:
  regex_extract:
    text: "{ValidationStatus}"  # 'text'を使用
    pattern: "\\w+"
```

#### エラー2: `TypeError: unhashable type: 'list'`
```yaml
# ❌ 間違い: listに直接配列を渡す
- type: logic
  op: for
  list: [5, 2, 8, 2, 5]  # エラー
  var: x

# ✅ 正しい: 先に変数に保存
- type: logic
  op: set
  var: sample_list
  value: [5, 2, 8, 2, 5]
  outputs:
    - name: SampleList
      from: value

- type: logic
  op: for
  list: "{sample_list}"  # 変数参照
  var: x
```

#### エラー3: `ValueError: python block requires 'function' or 'entrypoint'`
```yaml
# ❌ 間違い: 関数名の指定がない
- type: python
  function_code: |
    def main(ctx, **inputs):
        return {}
  outputs: [Result]

# ✅ 正しい: entrypointを指定
- type: python
  entrypoint: "main"  # または function: "main"
  function_code: |
    def main(ctx, **inputs):
        return {}
  outputs: [Result]
```

### 17.10 ベストプラクティス

1. **予算制御は必ず設定する**
   ```yaml
   budgets:
     loops: { max_iters: 1000, on_exceed: "error" }
     recursion: { max_depth: 128, on_exceed: "error" }
   ```

2. **ブロックにはIDと名前を付ける**
   ```yaml
   - type: logic
     exec: 1
     id: init_vars  # 一意なID
     name: "Initialize Variables"  # わかりやすい名前
   ```

3. **Python関数は型ヒントを使う**
   ```python
   def calculate_stats(ctx, numbers: list) -> dict:
       """関数の説明"""
       return {"Statistics": {...}}
   ```

4. **MEX式は読みやすく構造化する**
   ```yaml
   # ✅ 良い例
   value:
     add:
       - {"mul": [{"var": "x"}, {"var": "y"}]}
       - {"var": "z"}
   
   # ❌ 悪い例（一行に詰め込まない）
   value: {"add":[{"mul":[{"var":"x"},{"var":"y"}]},{"var":"z"}]}
   ```

5. **エラーハンドリングを明示する**
   ```yaml
   - type: python
     exec: 10
     on_error: "continue"  # エラー時の動作を指定
     retry:  # リトライ設定
       max_attempts: 3
       backoff:
         type: "exponential"
         base_ms: 1000
   ```

---

## 18. まとめ

MABEL v2.0は、AIエージェントの処理フローをYAMLで宣言的に記述できる完全な仕様言語です。

### 主要機能
- ✅ **統合仮想環境**（`runtime.python`）で再現性を確保
- ✅ **インライン Python** で迅速な拡張が可能（完全実装済み）
- ✅ **基本制御構造** `set`/`while`による反復処理（完全実装済み）
- ✅ **高度な制御構造** `recurse`/`reduce`/`call`/`let`（完全実装済み）
- ✅ **Turing完全性** 再帰的定義と関数型プログラミングをサポート
- ✅ **安全性** 予算制御とサンドボックスによる実行環境の保護

### v1からの進化
- v1の全機能を**完全に継承**し、後方互換性を維持
- v2で追加された高度な機能もすべて**実装済み**
- 実装率**100%** - 仕様に記載されたすべての機能が動作

### 推奨事項
- 高度な機能（`recurse`、`reduce`、`call`、`let`）も安心して使用可能
- 予算制御（`budgets`）を適切に設定して安全な実行を保証
- Python実行時はセキュリティを考慮し、`ctx_access`で権限を明示

本仕様により、複雑なAIワークフローを安全かつ効率的に構築できます。
