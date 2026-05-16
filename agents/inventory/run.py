"""
在庫確認エージェント - テストランナー

全分岐パターンのテストケースを実行する。
"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加（agent.py / config.py を参照するため）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import run_agent
from agents.inventory.prompt import definition

TEST_CASES = [
    {
        "id":          "CASE-1",
        "description": "✅ 在庫あり → 価格確認 → 予約",
        "query":       "P001のイヤホンの在庫を確認して、あれば予約してください。メールはuser@example.com です。",
    },
    {
        "id":          "CASE-2",
        "description": "📅 在庫なし・入荷予定あり → 入荷待ち登録",
        "query":       "P002のUSBハブが欲しいです。在庫状況を確認して手配してください。メールはuser@example.com です。",
    },
    {
        "id":          "CASE-3",
        "description": "🔄 在庫なし・入荷未定 → 代替品検索 → 代替品を予約",
        "query":       "P003のキーボードを購入したいです。在庫がなければ代替品でも構いません。予約までお願いします。メールはuser@example.com です。",
    },
    {
        "id":          "CASE-4",
        "description": "🔍 商品ID不明 → キーワード検索 → 在庫確認",
        "query":       "ウェブカメラが欲しいのですが、在庫はありますか？",
    },
    {
        "id":          "CASE-5",
        "description": "❌ 在庫なし・入荷未定・代替品なし → 取り扱い不可",
        "query":       "P005のPCスタンドを購入したいです。在庫がなければ代替品でも構いません。",
    },
]


async def run_single(case: dict) -> None:
    print(f"\n{'#'*60}")
    print(f"# {case['id']}: {case['description']}")
    print(f"{'#'*60}")
    await run_agent(case["query"], definition=definition)


async def main() -> None:
    if len(sys.argv) > 1:
        idx = int(sys.argv[1]) - 1
        if 0 <= idx < len(TEST_CASES):
            await run_single(TEST_CASES[idx])
        else:
            print(f"ケース番号は 1〜{len(TEST_CASES)} で指定してください")
    else:
        for case in TEST_CASES:
            await run_single(case)
            print()


if __name__ == "__main__":
    asyncio.run(main())
