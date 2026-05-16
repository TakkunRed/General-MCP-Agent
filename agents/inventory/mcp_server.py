"""
在庫確認エージェント - MCPサーバー（疑似ツール定義）

LLMが自律判断できるよう
- description に「呼ぶタイミング」「結果の意味」「次のアクション」を記述
- ツール結果に next_recommended_action を含める
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json
import asyncio

app = Server("inventory-server")

# ──────────────────────────────────────────────
# 疑似データ
# ──────────────────────────────────────────────
PRODUCTS = {
    "P001": {"name": "ワイヤレスイヤホン Pro",  "stock": 15, "price": 12800},
    "P002": {"name": "USBハブ 7ポート",          "stock": 0,  "price": 3200,  "restock_date": "2026-06-10"},
    "P003": {"name": "メカニカルキーボード",      "stock": 0,  "price": 8500,  "restock_date": None},
    "P004": {"name": "4Kウェブカメラ",           "stock": 3,  "price": 15000},
    "P005": {"name": "ノートPC スタンド",         "stock": 0,  "price": 4200,  "restock_date": "2026-05-25"},
}

KEYWORD_INDEX = {
    "イヤホン":   ["P001"],
    "ハブ":       ["P002"],
    "キーボード": ["P003"],
    "カメラ":     ["P004"],
    "スタンド":   ["P005"],
    "PC":         ["P004", "P005"],
    "USB":        ["P002"],
}

ALTERNATIVES = {
    "P002": ["P006"],
    "P003": ["P007"],
    "P005": [],
}

ALTERNATIVE_PRODUCTS = {
    "P006": {"name": "USBハブ 4ポート (代替品)",      "stock": 8,  "price": 1980},
    "P007": {"name": "メンブレンキーボード (代替品)",  "stock": 20, "price": 2800},
}


# ──────────────────────────────────────────────
# ツール定義（descriptionにLLMへの判断材料を記述）
# ──────────────────────────────────────────────
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_inventory",
            description="""
商品IDで在庫状況を確認する。

## 呼ぶタイミング
- product_idが判明したら最初に必ず呼ぶ
- search_by_keywordでproduct_idを特定した直後にも呼ぶ
- search_alternativesで代替品のproduct_idが見つかった直後にも呼ぶ

## 結果の意味と次のアクション
- status=in_stock    : 在庫あり。ユーザーは購入可能。→ check_price を呼ぶ
- status=out_of_stock: 在庫なし。入荷見込みを確認する必要がある。→ check_restock_date を呼ぶ
- status=not_found   : 商品IDが存在しない。キーワードで探し直す必要がある。→ search_by_keyword を呼ぶ
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品ID (例: P001)"}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="check_price",
            description="""
商品の価格情報を取得する。

## 呼ぶタイミング
- check_inventory の結果が status=in_stock だったときのみ呼ぶ
- 在庫がない商品には呼ばない

## 結果の意味と次のアクション
- price が返ってきたら購入手続きに進める。→ reserve_item を呼ぶ
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品ID"}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="reserve_item",
            description="""
商品を仮予約する。

## 呼ぶタイミング
- check_price の直後に呼ぶ
- 必ず check_price を呼んだ後でないと呼ばない

## 結果の意味と次のアクション
- status=reserved : 予約成功。reservation_id をユーザーに伝えて処理完了。→ 最終回答を生成する
- status=failed   : 予約失敗。在庫不足の可能性。→ check_inventory を再度呼んで状況を確認する
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品ID"},
                    "quantity":   {"type": "integer", "description": "予約数量 (デフォルト1)", "default": 1}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="check_restock_date",
            description="""
在庫なし商品の入荷予定日を確認する。

## 呼ぶタイミング
- check_inventory の結果が status=out_of_stock だったときのみ呼ぶ

## 結果の意味と次のアクション
- has_schedule=true  : 入荷予定日が確定している。ユーザーに通知できる。→ register_waitlist を呼ぶ
- has_schedule=false : 入荷予定が未定。代替品を探す必要がある。→ search_alternatives を呼ぶ
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品ID"}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="register_waitlist",
            description="""
入荷待ちリストにメールアドレスを登録する。

## 呼ぶタイミング
- check_restock_date の結果が has_schedule=true だったときのみ呼ぶ
- has_schedule=false のときは呼ばない（入荷未定なので登録しても意味がない）

## 結果の意味と次のアクション
- status=registered : 登録成功。入荷日と通知先メールをユーザーに伝えて処理完了。→ 最終回答を生成する
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "商品ID"},
                    "email":      {"type": "string", "description": "通知先メールアドレス"}
                },
                "required": ["product_id", "email"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="search_alternatives",
            description="""
在庫なし・入荷未定の商品の代替品を検索する。

## 呼ぶタイミング
- check_restock_date の結果が has_schedule=false だったときのみ呼ぶ

## 結果の意味と次のアクション
- count > 0      : 代替品が見つかった。それぞれの product_id で在庫を確認する。→ check_inventory を呼ぶ
- count = 0      : 代替品なし。この商品はお取り扱いできない。→ 最終回答を生成する（取り扱い不可を伝える）
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "元の商品ID"}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            }
        ),
        Tool(
            name="search_by_keyword",
            description="""
キーワードで商品IDを検索する。

## 呼ぶタイミング
- ユーザーが商品名・カテゴリ名で話しており product_id が不明なときに呼ぶ
- check_inventory の結果が status=not_found だったときに呼ぶ

## 結果の意味と次のアクション
- count > 0 : 商品が見つかった。product_id が判明した。→ check_inventory を呼ぶ
- count = 0 : 該当商品なし。ユーザーに取り扱いがない旨を伝える。→ 最終回答を生成する
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "検索キーワード (例: イヤホン, キーボード)"}
                },
                "required": ["keyword"],
                "additionalProperties": False,
            }
        ),
    ]


# ──────────────────────────────────────────────
# ツール実装（結果に next_recommended_action を付与）
# ──────────────────────────────────────────────
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "check_inventory":
        pid = arguments["product_id"]
        if pid in PRODUCTS:
            p = PRODUCTS[pid]
            if p["stock"] > 0:
                result = {
                    "product_id": pid, "name": p["name"], "status": "in_stock", "stock": p["stock"],
                    "next_recommended_action": "在庫があります。check_price を呼んで価格を確認してください。",
                }
            else:
                result = {
                    "product_id": pid, "name": p["name"], "status": "out_of_stock", "stock": 0,
                    "next_recommended_action": "在庫がありません。check_restock_date を呼んで入荷予定を確認してください。",
                }
        elif pid in ALTERNATIVE_PRODUCTS:
            p = ALTERNATIVE_PRODUCTS[pid]
            result = {
                "product_id": pid, "name": p["name"], "status": "in_stock", "stock": p["stock"],
                "next_recommended_action": "代替品の在庫があります。check_price を呼んで価格を確認してください。",
            }
        else:
            result = {
                "product_id": pid, "status": "not_found",
                "next_recommended_action": "商品IDが見つかりません。search_by_keyword を呼んでキーワードで商品を探してください。",
            }

    elif name == "check_price":
        pid = arguments["product_id"]
        p = PRODUCTS.get(pid) or ALTERNATIVE_PRODUCTS.get(pid)
        if p:
            result = {
                "product_id": pid, "name": p["name"], "price": p["price"],
                "next_recommended_action": f"価格は {p['price']}円です。reserve_item を呼んで仮予約してください。",
            }
        else:
            result = {
                "error": f"商品 {pid} が見つかりません",
                "next_recommended_action": "商品が見つかりません。check_inventory で再確認してください。",
            }

    elif name == "reserve_item":
        pid = arguments["product_id"]
        qty = arguments.get("quantity", 1)
        p = PRODUCTS.get(pid) or ALTERNATIVE_PRODUCTS.get(pid)
        if p and p["stock"] >= qty:
            p["stock"] -= qty
            result = {
                "status": "reserved", "product_id": pid, "name": p["name"],
                "quantity": qty, "reservation_id": f"RSV-{pid}-{qty}",
                "next_recommended_action": "予約が完了しました。reservation_id をユーザーに伝えて最終回答を生成してください。",
            }
        else:
            result = {
                "status": "failed", "reason": "在庫不足または商品不明",
                "next_recommended_action": "予約に失敗しました。check_inventory を再度呼んで在庫状況を確認してください。",
            }

    elif name == "check_restock_date":
        pid = arguments["product_id"]
        p = PRODUCTS.get(pid)
        if p:
            restock = p.get("restock_date")
            result = {
                "product_id": pid, "name": p["name"],
                "restock_date": restock, "has_schedule": restock is not None,
                "next_recommended_action": (
                    f"入荷予定日は {restock} です。register_waitlist を呼んでユーザーを入荷待ちリストに登録してください。"
                    if restock else
                    "入荷予定が未定です。search_alternatives を呼んで代替品を探してください。"
                ),
            }
        else:
            result = {
                "error": f"商品 {pid} が見つかりません",
                "next_recommended_action": "商品が見つかりません。check_inventory で再確認してください。",
            }

    elif name == "register_waitlist":
        pid, email = arguments["product_id"], arguments["email"]
        p = PRODUCTS.get(pid)
        result = {
            "status": "registered", "product_id": pid,
            "name": p["name"] if p else pid, "email": email,
            "message": f"入荷時に {email} へ通知します",
            "next_recommended_action": "入荷待ち登録が完了しました。登録内容をユーザーに伝えて最終回答を生成してください。",
        }

    elif name == "search_alternatives":
        pid  = arguments["product_id"]
        alts = ALTERNATIVES.get(pid, [])
        if alts:
            items = [
                {"product_id": aid, "name": ALTERNATIVE_PRODUCTS.get(aid, {}).get("name", aid),
                 "stock": ALTERNATIVE_PRODUCTS.get(aid, {}).get("stock", 0),
                 "price": ALTERNATIVE_PRODUCTS.get(aid, {}).get("price", 0)}
                for aid in alts
            ]
            result = {
                "alternatives": items, "count": len(items),
                "next_recommended_action": f"代替品が {len(items)} 件見つかりました。各 product_id に対して check_inventory を呼んで在庫を確認してください。",
            }
        else:
            result = {
                "alternatives": [], "count": 0,
                "next_recommended_action": "代替品が見つかりませんでした。この商品はお取り扱いできない旨を伝えて最終回答を生成してください。",
            }

    elif name == "search_by_keyword":
        kw   = arguments["keyword"]
        pids = KEYWORD_INDEX.get(kw, [])
        if pids:
            items = [
                {"product_id": pid, "name": PRODUCTS.get(pid, {}).get("name", pid),
                 "stock": PRODUCTS.get(pid, {}).get("stock", 0)}
                for pid in pids
            ]
            result = {
                "found": items, "count": len(items),
                "next_recommended_action": f"{len(items)} 件の商品が見つかりました。product_id を使って check_inventory を呼んでください。",
            }
        else:
            result = {
                "found": [], "count": 0,
                "next_recommended_action": f"'{kw}' に一致する商品が見つかりませんでした。取り扱いがない旨をユーザーに伝えて最終回答を生成してください。",
            }

    else:
        result = {"error": f"未知のツール: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
