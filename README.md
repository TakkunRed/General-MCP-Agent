# 汎用 MCP エージェント

任意の OpenAI 互換 LLM（LM Studio・Ollama・OpenAI 等）と MCP Python SDK を組み合わせた、  
**多段階・分岐ありのツール呼び出しエージェント**のサンプル実装です。

---

## 目次

1. [概要](#概要)
2. [仕組み](#仕組み)
3. [ファイル構成](#ファイル構成)
4. [LLMによるツール制御の設計方針](#llmによるツール制御の設計方針)
5. [在庫確認エージェントの分岐フロー](#在庫確認エージェントの分岐フロー)
6. [実行時ログの見方](#実行時ログの見方)
7. [セットアップ](#セットアップ)
8. [実行方法](#実行方法)
9. [新しいエージェントの追加方法](#新しいエージェントの追加方法)

---

## 概要

```
ユーザー入力
    ↓
LLM（OpenAI 互換バックエンド）
    ↓  ツールを選んで呼び出す
MCP サーバー（疑似ツール群 / 外部サービス）
    ↓  結果を返す
LLM（結果を読んで次のツールを選ぶ）
    ↓  繰り返す
最終回答
```

ポイントは **LLM がツールの呼び出し順を自律的に判断する** 点です。  
Python コードに分岐ロジックは書かず、LLM への情報の与え方（プロンプト・ツール定義・ツール結果）によって制御します。

---

## 仕組み

### 全体のアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│  agents/inventory/run.py  （テストランナー）             │
│    ↓ AgentDefinition を渡して呼び出す                    │
├─────────────────────────────────────────────────────────┤
│  agent.py  （汎用エージェントループ）                    │
│                                                         │
│  1. StdioServerParameters で MCP サーバーを起動          │
│  2. 利用可能なツール一覧を取得して OpenAI 形式に変換     │
│  3. LLM へ「システムプロンプト＋ユーザー入力」送信       │
│  4. LLM がツールを選んで呼び出す                        │
│  5. ツール結果を会話履歴に追加して LLM へ再送信         │
│  6. ツール呼び出しがなくなったら最終回答として返す       │
│     （4〜6 を MAX_STEPS 回まで繰り返す）                 │
├─────────────────────────────────────────────────────────┤
│  agents/inventory/mcp_server.py  （疑似ツール群）        │
│    ↑ stdio 経由で agent.py から呼ばれる                  │
└─────────────────────────────────────────────────────────┘
```

### エージェントループの詳細（agent.py）

```
┌──────────────────────────────────────────────────────┐
│ Step N                                               │
│                                                      │
│  step_overrides[N] があれば tool_choice/temperature  │
│  をそのステップだけ上書き（なければ .env の値を使用） │
│                                                      │
│  messages（会話履歴）                                 │
│  ├─ system:    SYSTEM_PROMPT                        │
│  ├─ user:      ユーザー入力                          │
│  ├─ assistant: 前回のツール呼び出し指示              │
│  ├─ tool:      前回のツール結果                      │
│  └─ ...（繰り返し）                                  │
│         ↓ LLM へ送信                                 │
│  LLM の応答                                          │
│  ├─ tool_calls あり → ツールを呼んで結果を追加       │
│  └─ tool_calls なし → 最終回答として返す             │
└──────────────────────────────────────────────────────┘
```

---

## ファイル構成

```
inventory_agent/
│
├── .env                          # 接続設定・動作設定（gitignore 推奨）
├── .env.example                  # .env のテンプレート
│
├── config.py                     # .env を読んで AgentConfig を提供
├── agent.py                      # 汎用エージェントループ本体
│
└── agents/
    └── inventory/                # 在庫確認エージェント
        ├── mcp_server.py         # 疑似ツール7種の定義と実装
        ├── prompt.py             # AgentDefinition（起動パラメータ・プロンプト等）
        └── run.py                # テストランナー（5ケース）
```

### 各ファイルの役割

| ファイル | 役割 | 変更頻度 |
|---------|------|---------|
| `.env` | LLM 接続先・モデル名・動作パラメータ | 環境ごとに変える |
| `config.py` | `.env` を読んで型付きデータクラスに変換 | ほぼ変えない |
| `agent.py` | エージェントループ・ログ出力（エージェント非依存） | ほぼ変えない |
| `agents/inventory/prompt.py` | `AgentDefinition`（起動方式・プロンプト・オーバーライド） | エージェントごとに作る |
| `agents/inventory/mcp_server.py` | ツールの定義・実装・疑似データ | エージェントごとに作る |
| `agents/inventory/run.py` | テストケースの定義と実行 | エージェントごとに作る |

---

## LLMによるツール制御の設計方針

Python コードに分岐ロジックを書かず、以下の **3層** で LLM への情報を整備することで、LLM 自身がツールの呼び出し順を判断します。

### 第1層：SYSTEM_PROMPT（agents/inventory/prompt.py）

エージェントの **目的と行動原則** だけを書きます。具体的な分岐ルールは書きません。

```
あなたは在庫確認エージェントです。
ユーザーが商品を入手できるよう、利用可能なツールを使って最善の手配をしてください。

## 行動原則
- 各ツールの description に書かれた「呼ぶタイミング」と「次のアクション」を必ず参照して判断すること
- ツールの結果に含まれる next_recommended_action を読んで次のステップを決めること
```

> ❌ SYSTEM_PROMPT に「在庫ありなら check_price を呼べ」などの分岐ルールは書かない  
> ✅ 分岐ルールは各ツールの description に書く

---

### 第2層：ツールの description（agents/inventory/mcp_server.py）

各ツールの description に **「いつ呼ぶか」「結果が何を意味するか」「次に何をすべきか」** を記述します。

```python
Tool(
    name="check_inventory",
    description="""
商品IDで在庫状況を確認する。

## 呼ぶタイミング
- product_id が判明したら最初に必ず呼ぶ
- search_by_keyword で product_id を特定した直後にも呼ぶ

## 結果の意味と次のアクション
- status=in_stock     → check_price を呼ぶ
- status=out_of_stock → check_restock_date を呼ぶ
- status=not_found    → search_by_keyword を呼ぶ
""",
)
```

LLM はツール結果を受け取るたびに description を参照して次の行動を自律判断します。

---

### 第3層：ツール結果の next_recommended_action（agents/inventory/mcp_server.py）

ツールの戻り値に `next_recommended_action` フィールドを含めます。  
LLM は実際に返ってきたデータ（在庫数・入荷日など）を踏まえた **動的なアドバイス** を受け取れます。

```python
# 在庫ありの場合
{
    "status": "in_stock",
    "stock": 15,
    "next_recommended_action": "在庫があります。check_price を呼んで価格を確認してください。"
}

# 在庫なし・入荷未定の場合
{
    "status": "out_of_stock",
    "has_schedule": false,
    "next_recommended_action": "入荷予定が未定です。search_alternatives を呼んで代替品を探してください。"
}
```

> description は静的なルール、next_recommended_action は動的なナビゲーションという使い分けです。  
> フィールド名は `.env` の `NEXT_ACTION_FIELD` で変更できます。

---

## 在庫確認エージェントの分岐フロー

```
ユーザー入力
    ↓
【商品ID不明の場合】search_by_keyword → 商品ID を特定
    ↓
check_inventory（在庫確認）
    │
    ├─ in_stock（在庫あり）
    │       ↓
    │   check_price（価格確認）
    │       ↓
    │   reserve_item（仮予約）              ✅ 予約完了 → 最終回答
    │
    ├─ out_of_stock（在庫なし）
    │       ↓
    │   check_restock_date（入荷予定確認）
    │       │
    │       ├─ has_schedule=true（入荷予定あり）
    │       │       ↓
    │       │   register_waitlist（入荷待ち登録）  📅 登録完了 → 最終回答
    │       │
    │       └─ has_schedule=false（入荷未定）
    │               ↓
    │           search_alternatives（代替品検索）
    │               │
    │               ├─ 代替品あり → check_inventory → check_price → reserve_item
    │               │                                               🔄 代替品を予約 → 最終回答
    │               └─ 代替品なし              ❌ 取り扱い不可 → 最終回答
    │
    └─ not_found（商品不明）
            ↓
        search_by_keyword → check_inventory（再実行）
```

### テストケース一覧

| No | 分岐パターン | 呼び出されるツールの流れ |
|----|-------------|------------------------|
| CASE-1 | ✅ 在庫あり | `check_inventory` → `check_price` → `reserve_item` |
| CASE-2 | 📅 在庫なし・入荷予定あり | `check_inventory` → `check_restock_date` → `register_waitlist` |
| CASE-3 | 🔄 在庫なし・入荷未定・代替品あり | `check_inventory` → `check_restock_date` → `search_alternatives` → `check_inventory` → `check_price` → `reserve_item` |
| CASE-4 | 🔍 商品ID不明 | `search_by_keyword` → `check_inventory` → `check_price` → `reserve_item` |
| CASE-5 | ❌ 在庫なし・代替品なし | `check_inventory` → `check_restock_date` → `search_alternatives` → 終了 |

---

## 実行時ログの見方

`VERBOSE=true` の場合、以下のようなログが出力されます。

```
============================================================
  エージェント        : 在庫確認エージェント
  利用可能なMCPツール : ['check_inventory', 'check_price', ...]
============================================================
  [ユーザー入力]
  P001のイヤホンの在庫を確認して、あれば予約してください。
============================================================

────────────────────────────────────────────────────────────
  [Step 1] LLMの判断           ← step_overrides があれば "(tool_choice=required)" 等が付く
────────────────────────────────────────────────────────────
  ▶ 選択ツール : check_inventory
  ▶ 引数       : {"product_id": "P001"}
  ◀ ツール結果 : {"status": "in_stock", "stock": 15, ...}
  ◀ 次の推奨   : 在庫があります。check_price を呼んで価格を確認してください。
                                  ↑ next_recommended_action（NEXT_ACTION_FIELD）の内容

────────────────────────────────────────────────────────────
  [Step 2] LLMの判断
────────────────────────────────────────────────────────────
  ▶ 選択ツール : check_price    ← 推奨に従って次のツールを選択
  ...（以下続く）

============================================================
  [ツール呼び出し履歴]          ← 最後にまとめて表示
============================================================
  1. check_inventory({"product_id": "P001"})
     → 在庫があります。check_price を呼んで価格を確認してください。
  2. check_price({"product_id": "P001"})
     → 価格は12800円です。reserve_item を呼んで仮予約してください。
  3. reserve_item({"product_id": "P001", "quantity": 1})
     → 予約が完了しました。reservation_id をユーザーに伝えてください。

============================================================
  [最終回答]
============================================================
ワイヤレスイヤホン Pro (P001) の在庫を確認しました。
価格は12,800円で、予約番号 RSV-P001-1 で仮予約が完了しました。
```

---

## セットアップ

### 前提条件

- Python 3.11 以上
- [uv](https://docs.astral.sh/uv/) インストール済み
- tool calling 対応の OpenAI 互換 LLM バックエンド（下記いずれか）
  - [LM Studio](https://lmstudio.ai/)（推奨モデル：`qwen2.5-7b-instruct`、`mistral-nemo` 等）
  - [Ollama](https://ollama.com/)
  - OpenAI API

### 手順

```bash
# 1. 依存ライブラリのインストール
git clone https://github.com/TakkunRed/General-MCP-Agent.git
cd General-MCP-Agent
uv sync

# 2. .env を編集して接続先・モデル名を設定
notepad .env

# 3. LLM バックエンドを起動する
#    （LM Studio の場合：ローカルサーバー ポート 1234 を有効にする）
```

### .env の設定項目

| 設定キー | デフォルト値 | 説明 |
|---------|------------|------|
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LLM バックエンドのエンドポイント |
| `LLM_API_KEY` | `lm-studio` | API キー（LM Studio・Ollama は任意の文字列で可） |
| `MODEL_NAME` | `your-model-name` | **要変更**：使用するモデル名 |
| `MAX_STEPS` | `10` | エージェントループの最大繰り返し回数 |
| `TEMPERATURE` | `0.1` | LLM の出力のゆらぎ（低いほど安定） |
| `VERBOSE` | `true` | 詳細ログの表示（`false` で最終回答のみ） |
| `NEXT_ACTION_FIELD` | `next_recommended_action` | ツール結果内の「次の推奨」フィールド名 |

### LLM バックエンド別の設定例

```ini
# LM Studio（デフォルト）
LLM_BASE_URL=http://localhost:1234/v1
LLM_API_KEY=lm-studio

# Ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama

# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
```

---

## 実行方法

```bash
# 全テストケースを実行
uv run python agents/inventory/run.py

# 特定のケースだけ実行（1〜5）
uv run python agents/inventory/run.py 1
```

---

## 新しいエージェントの追加方法

`agent.py` と `config.py` は一切変更不要です。  
`agents/` 以下に新しいフォルダを作成して 3 ファイルを用意するだけです。

```
agents/
└── your_agent/
    ├── mcp_server.py   # ツールの定義と実装
    ├── prompt.py       # AgentDefinition を定義
    └── run.py          # テストランナー
```

### prompt.py のテンプレート

```python
import sys
from pathlib import Path
from mcp import StdioServerParameters
from agent import AgentDefinition, StepOverride

# ── MCPサーバーの起動方式を選ぶ ──────────────────────────

# Python スクリプト
_server_params = StdioServerParameters(
    command=sys.executable,
    args=[str(Path(__file__).parent / "mcp_server.py")],
)

# npx（Node.js 製 MCP サーバー / Postgres 公式サーバー等）
# _server_params = StdioServerParameters(
#     command="npx",
#     args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/db"],
# )

# uvx（Python 製 MCP サーバー）
# _server_params = StdioServerParameters(
#     command="uvx",
#     args=["mcp-server-sqlite", "--db-path", "mydb.sqlite"],
# )

# ── SYSTEM_PROMPT は目的と原則のみ。分岐ルールは書かない ─

SYSTEM_PROMPT = """あなたは〇〇エージェントです。
...
"""

# ── AgentDefinition を組み立てる ─────────────────────────

definition = AgentDefinition(
    name          = "〇〇エージェント",
    server_params = _server_params,
    system_prompt = SYSTEM_PROMPT,

    # 特定ステップで tool_choice / temperature を上書きしたい場合
    # step_overrides = {
    #     1: StepOverride(tool_choice="required"),  # Step1 は必ずツールを呼ぶ
    # },

    # ログ出力先を変えたい場合（省略時は標準出力）
    # logger = logging.getLogger("your_agent"),
)
```

### mcp_server.py のツール定義のポイント

```python
Tool(
    name="your_tool",
    description="""
ツールの説明。

## 呼ぶタイミング              ← LLM がいつ呼ぶかを判断する材料
- ...

## 結果の意味と次のアクション  ← LLM が次のツールを選ぶ材料
- result_x → 次のツール A を呼ぶ
- result_y → 次のツール B を呼ぶ
""",
)
```

### ツール結果に next_recommended_action を含める

```python
result = {
    "your_field": value,
    # NEXT_ACTION_FIELD（デフォルト: "next_recommended_action"）と合わせること
    "next_recommended_action": "〇〇の結果です。次に △△ を呼んでください。",
}
```

### Postgres への接続例

`mcp_server.py` を自作せず、公式 MCP サーバーを `npx` で起動するだけで接続できます。

```python
# agents/postgres/prompt.py
_server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/db"],
)
```

`agent.py` の変更は不要です。
