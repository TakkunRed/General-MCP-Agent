"""
汎用 MCP エージェントループ

改善点:
  ① MCPサーバーの起動方式を AgentDefinition に移し、任意の StdioServerParameters を注入可能に
  ② LLM クライアント・設定名を OpenAI/LM Studio 固有から汎用化
  ③ ログ出力を logging モジュールに切り替え、logger を外部注入可能に
     next_recommended_action フィールド名もハードコードを排除
  ④ tool_choice / temperature をステップごとにオーバーライド可能に
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI

from config import AgentConfig, load_config

# デフォルトロガー（呼び出し元が差し替えない場合に使用）
_default_logger = logging.getLogger(__name__)
if not _default_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _default_logger.addHandler(_handler)
    _default_logger.setLevel(logging.DEBUG)


# ──────────────────────────────────────────────
# ④ ステップごとの LLM パラメータオーバーライド
# ──────────────────────────────────────────────
@dataclass
class StepOverride:
    """
    特定ステップで tool_choice / temperature を上書きしたい場合に使う。

    例:
        overrides = {
            1: StepOverride(tool_choice="required"),          # 最初は必ずツールを呼ぶ
            5: StepOverride(tool_choice="none", temperature=0.7),  # Step5 は回答生成のみ
        }
    """
    tool_choice: str | dict | None = None
    temperature: float | None      = None


# ──────────────────────────────────────────────
# ① AgentDefinition（エージェント固有の設定）
# ──────────────────────────────────────────────
@dataclass
class AgentDefinition:
    """
    エージェント固有の設定。新しいエージェントを作るときはこれを用意するだけでよい。

    server_params:
        MCPサーバーの起動パラメータ。Python スクリプト・npx・uvx など任意の起動方式を指定できる。

        例）Python スクリプト:
            StdioServerParameters(command=sys.executable, args=["mcp_server.py"])

        例）npx（Node.js 製 MCP サーバー）:
            StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://..."])

        例）uvx:
            StdioServerParameters(command="uvx", args=["mcp-server-sqlite", "--db-path", "mydb.sqlite"])

    step_overrides:
        ステップ番号をキーに StepOverride を指定すると、そのステップの
        tool_choice / temperature を上書きできる。省略時はすべて config の値を使用。
    """
    name:           str
    server_params:  StdioServerParameters
    system_prompt:  str
    logger:         logging.Logger | None         = None
    step_overrides: dict[int, StepOverride]       = field(default_factory=dict)


# ──────────────────────────────────────────────
# MCPツール → OpenAI 形式 変換
# ──────────────────────────────────────────────
def _mcp_tools_to_openai(mcp_tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name":        tool.name,
                "description": tool.description,
                "parameters":  tool.inputSchema,
            }
        }
        for tool in mcp_tools
    ]


# ──────────────────────────────────────────────
# ③ ログ出力ヘルパー
# ──────────────────────────────────────────────
def _log_header(log: logging.Logger, agent_name: str, tools: list, user_query: str) -> None:
    log.info(f"\n{'='*60}")
    log.info(f"  エージェント        : {agent_name}")
    log.info(f"  利用可能なMCPツール : {[t.name for t in tools]}")
    log.info(f"{'='*60}")
    log.info(f"  [ユーザー入力]")
    log.info(f"  {user_query}")
    log.info(f"{'='*60}")


def _log_decision(log: logging.Logger, step: int, message, override: StepOverride | None) -> None:
    log.info(f"\n{'─'*60}")
    log.info(f"  [Step {step}] LLMの判断"
             + (f"  (tool_choice={override.tool_choice})" if override and override.tool_choice else ""))
    log.info(f"{'─'*60}")
    if message.tool_calls:
        for tc in message.tool_calls:
            args = json.loads(tc.function.arguments)
            log.info(f"  ▶ 選択ツール : {tc.function.name}")
            log.info(f"  ▶ 引数       : {json.dumps(args, ensure_ascii=False)}")
    else:
        log.info(f"  ▶ ツール呼び出しなし → 最終回答を生成")
    if message.content:
        log.info(f"  ▶ LLMコメント: {message.content}")


def _log_tool_result(
    log: logging.Logger,
    result_text: str,
    next_action_field: str,
) -> str:
    """ツール結果を表示し、next_action_field の値を返す"""
    try:
        result = json.loads(result_text)
        next_action = result.pop(next_action_field, "")
        log.info(f"  ◀ ツール結果 : {json.dumps(result, ensure_ascii=False)}")
        if next_action:
            log.info(f"  ◀ 次の推奨   : {next_action}")
        return next_action
    except Exception:
        log.info(f"  ◀ ツール結果 : {result_text}")
        return ""


def _log_history(log: logging.Logger, history: list[dict]) -> None:
    log.info(f"\n{'='*60}")
    log.info(f"  [ツール呼び出し履歴]")
    log.info(f"{'='*60}")
    for i, entry in enumerate(history, 1):
        log.info(f"  {i}. {entry['tool']}({json.dumps(entry['args'], ensure_ascii=False)})")
        if entry["next_action"]:
            log.info(f"     → {entry['next_action']}")


def _log_final(log: logging.Logger, answer: str) -> None:
    log.info(f"\n{'='*60}")
    log.info(f"  [最終回答]")
    log.info(f"{'='*60}")
    log.info(answer)


# ──────────────────────────────────────────────
# 汎用エージェントループ
# ──────────────────────────────────────────────
async def run_agent(
    user_query:  str,
    definition:  AgentDefinition,
    config:      AgentConfig | None = None,
) -> str:
    """
    汎用 MCP エージェントループ。

    Args:
        user_query:  ユーザーの問い合わせ
        definition:  エージェント固有の定義
                     （StdioServerParameters・システムプロンプト・logger・step_overrides）
        config:      動作設定。省略時は .env から自動読み込み

    Returns:
        最終回答テキスト
    """
    if config is None:
        config = load_config()

    # ③ logger：definition に指定があればそれを使い、なければデフォルトを使用
    log = definition.logger or _default_logger

    # ① server_params は definition から取得（起動方式はエージェント側が決める）
    async with stdio_client(definition.server_params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()
            mcp_tools    = (await session.list_tools()).tools
            openai_tools = _mcp_tools_to_openai(mcp_tools)

            if config.verbose:
                _log_header(log, definition.name, mcp_tools, user_query)

            # ② llm_base_url / llm_api_key（汎用化された設定名を使用）
            lm_client = OpenAI(
                base_url=config.llm_base_url,
                api_key=config.llm_api_key,
            )

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": definition.system_prompt},
                {"role": "user",   "content": user_query},
            ]

            tool_call_history: list[dict] = []

            for step in range(1, config.max_steps + 1):

                # ④ ステップごとのオーバーライドを適用
                override    = definition.step_overrides.get(step)
                tool_choice = (override.tool_choice if override and override.tool_choice is not None
                               else "auto")
                temperature = (override.temperature if override and override.temperature is not None
                               else config.temperature)

                response = lm_client.chat.completions.create(
                    model=config.model_name,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                )

                message = response.choices[0].message
                messages.append(message.model_dump(exclude_unset=False))

                if config.verbose:
                    _log_decision(log, step, message, override)

                # ツール呼び出しなし → 最終回答
                if not message.tool_calls:
                    final_answer = message.content or ""
                    if config.verbose:
                        _log_history(log, tool_call_history)
                        _log_final(log, final_answer)
                    return final_answer

                # ツール呼び出し実行
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)

                    mcp_result = await session.call_tool(tool_name, tool_args)

                    result_text = "".join(
                        c.text for c in mcp_result.content if hasattr(c, "text")
                    )

                    next_action = ""
                    if config.verbose:
                        # ③ next_action_field はハードコードせず config から取得
                        next_action = _log_tool_result(log, result_text, config.next_action_field)
                    else:
                        try:
                            next_action = json.loads(result_text).get(config.next_action_field, "")
                        except Exception:
                            pass

                    tool_call_history.append({
                        "tool":        tool_name,
                        "args":        tool_args,
                        "next_action": next_action,
                    })

                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tool_call.id,
                        "content":      result_text,
                    })

            return "エラー: 最大ステップ数に達しました。処理を中断します。"
