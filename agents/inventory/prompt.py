"""
在庫確認エージェント固有の定義

変更点:
  - mcp_server_script（文字列）→ StdioServerParameters（起動方式ごと）に変更
    Python スクリプト起動なので command=sys.executable を使用
  - step_overrides の例を示す（コメントアウト）
"""

import sys
from pathlib import Path

from mcp import StdioServerParameters

from agent import AgentDefinition, StepOverride

# ① MCPサーバーを StdioServerParameters として組み立てる
#    Python スクリプトなので sys.executable を使用
_server_params = StdioServerParameters(
    command=sys.executable,
    args=[str(Path(__file__).parent / "mcp_server.py")],
)

# 他バックエンドへ切り替える場合の例（コメントアウト）:
#
# npx（Node.js 製 Postgres MCP サーバー）:
# _server_params = StdioServerParameters(
#     command="npx",
#     args=["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/db"],
# )
#
# uvx（Python 製 SQLite MCP サーバー）:
# _server_params = StdioServerParameters(
#     command="uvx",
#     args=["mcp-server-sqlite", "--db-path", "mydb.sqlite"],
# )

SYSTEM_PROMPT = """あなたは在庫確認エージェントです。
ユーザーが商品を入手できるよう、利用可能なツールを使って最善の手配をしてください。

## 行動原則
- 各ツールの description に書かれた「呼ぶタイミング」と「次のアクション」を必ず参照して判断すること
- ツールの結果に含まれる next_recommended_action を読んで次のステップを決めること
- すべての手配が完了したら、ツールを呼ばずに日本語で結果をまとめて最終回答を返すこと
"""

definition = AgentDefinition(
    name          = "在庫確認エージェント",
    server_params = _server_params,
    system_prompt = SYSTEM_PROMPT,

    # ④ step_overrides の例（コメントアウト）:
    # step_overrides = {
    #     1: StepOverride(tool_choice="required"),   # Step1 は必ずツールを呼ぶ
    # },
)
