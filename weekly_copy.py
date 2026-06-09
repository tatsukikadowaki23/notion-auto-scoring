"""
weekly_copy.py
週次コピー処理：入力DB → 参照DBへのコピー
日報対象：今週日曜〜木曜、アーカイブ状態「通常」
週報対象：今週月曜〜日曜、アーカイブ状態「通常」
処理後：入力DBの対象レコードをアーカイブ済に更新 → ゴミ箱に移動
実行タイミング：毎週土曜0時（JST）
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# =====================
# 設定（環境変数から取得）
# =====================
NOTION_TOKEN = os.environ["NOTION_TOKEN"]

# DB ID（テスト環境）
NISSHO_INPUT_DB  = "37668896-b631-8057-8526-f78fb86ea7b5"  # 日報入力DB
NISSHO_REF_DB    = "37a68896-b631-80c9-8740-c02553416af1"  # 日報参照DB
SHYUHO_INPUT_DB  = "37668896-b631-80b2-9200-f23016a98027"  # 週報入力DB
SHYUHO_REF_DB    = "37a68896-b631-800f-9dd1-d7bb0a790148"  # 週報参照DB

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

JST = timezone(timedelta(hours=9))


def notion_request(method: str, path: str, body: dict = None) -> dict:
    url = f"https://api.notion.com/v1{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] {method} {path} -> {e.code}: {e.read().decode()}")
        raise


def get_dates() -> dict:
    """土曜0時実行時点での各期間を返す（JST）"""
    now = datetime.now(JST)
    # 土曜=5
    monday   = now - timedelta(days=5)  # 今週月曜
    sunday   = now - timedelta(days=6)  # 今週日曜
    thursday = now - timedelta(days=2)  # 今週木曜
    last_sunday = now - timedelta(days=1)  # 週報の終端（=昨日の金曜ではなく日曜）
    return {
        "monday":      monday.strftime("%Y-%m-%d"),
        "sunday":      sunday.strftime("%Y-%m-%d"),
        "thursday":    thursday.strftime("%Y-%m-%d"),
        "last_sunday": last_sunday.strftime("%Y-%m-%d"),
    }


def query_db(database_id: str, filter_body: dict) -> list:
    """DBをフィルタしてページ一覧を返す（ページネーション対応）"""
    results = []
    body = {"filter": filter_body, "page_size": 100}
    while True:
        res = notion_request("POST", f"/databases/{database_id}/query", body)
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        body["start_cursor"] = res["next_cursor"]
    return results


def get_text(prop) -> str:
    if not prop:
        return ""
    ptype = prop.get("type")
    if ptype == "rich_text":
        return "".join(t["plain_text"] for t in prop.get("rich_text", []))
    if ptype == "title":
        return "".join(t["plain_text"] for t in prop.get("title", []))
    return ""


def archive_page(page_id: str):
    """入力DBのレコードをゴミ箱に移動"""
    notion_request("PATCH", f"/pages/{page_id}", {"in_trash": True})


def copy_nissho_records(sunday: str, thursday: str):
    """日報入力DB → 日報参照DBへコピー（日曜〜木曜対象）"""
    print(f"[日報] {sunday} 〜 {thursday} のレコードを取得中...")

    filter_body = {
        "and": [
            {"property": "日付", "date": {"on_or_after": sunday}},
            {"property": "日付", "date": {"on_or_before": thursday}},
            {"property": "アーカイブ状態", "select": {"equals": "通常"}},
        ]
    }
    pages = query_db(NISSHO_INPUT_DB, filter_body)
    print(f"[日報] {len(pages)}件取得")

    for page in pages:
        page_id = page["id"]
        props = page["properties"]
        new_props = {
            "アクション内容": {"title": props["アクション内容"]["title"]},
            "日付": {"date": props["日付"]["date"]},
            "AI活用": {"rich_text": props["AI活用"]["rich_text"]},
            "相手・関係者（会社名）": {"rich_text": props["相手・関係者（会社名）"]["rich_text"]},
            "結果・成果": {"rich_text": props["結果・成果"]["rich_text"]},
            "メモ・備考": {"rich_text": props["メモ・備考"]["rich_text"]},
            "作成者": {"people": [{"id": p["id"]} for p in props["作成者"]["people"]]},
            "アーカイブ状態": {"select": {"name": "アーカイブ済"}},
        }
        notion_request("POST", "/pages", {
            "parent": {"database_id": NISSHO_REF_DB},
            "properties": new_props,
        })
        title = get_text(props["アクション内容"])
        print(f"  [コピー完了] {title}")

        # アーカイブ済に更新 → ゴミ箱に移動
        notion_request("PATCH", f"/pages/{page_id}", {
            "properties": {"アーカイブ状態": {"select": {"name": "アーカイブ済"}}}
        })
        archive_page(page_id)
        print(f"  [削除完了] {title}")

    print(f"[日報] 処理完了: {len(pages)}件")


def copy_shyuho_records(monday: str, last_sunday: str):
    """週報入力DB → 週報参照DBへコピー（月曜〜日曜対象）"""
    print(f"[週報] {monday} 〜 {last_sunday} のレコードを取得中...")

    filter_body = {
        "and": [
            {"property": "作成日", "date": {"on_or_after": monday}},
            {"property": "作成日", "date": {"on_or_before": last_sunday}},
            {"property": "アーカイブ状態", "select": {"equals": "通常"}},
        ]
    }
    pages = query_db(SHYUHO_INPUT_DB, filter_body)
    print(f"[週報] {len(pages)}件取得")

    for page in pages:
        page_id = page["id"]
        props = page["properties"]
        new_props = {
            "タイトル": {"title": props["タイトル"]["title"]},
            "Y（やったこと）": {"rich_text": props["Y（やったこと）"]["rich_text"]},
            "W（わかったこと）": {"rich_text": props["W（わかったこと）"]["rich_text"]},
            "T（次にやること）": {"rich_text": props["T（次にやること）"]["rich_text"]},
            "AI活用": {"rich_text": props["AI活用"]["rich_text"]},
            "作成日": {"date": props["作成日"]["date"]},
            "作成者": {"people": [{"id": p["id"]} for p in props["作成者"]["people"]]},
            "ステータス": {"select": props["ステータス"]["select"]},
            "アーカイブ状態": {"select": {"name": "アーカイブ済"}},
        }
        notion_request("POST", "/pages", {
            "parent": {"database_id": SHYUHO_REF_DB},
            "properties": new_props,
        })
        title = get_text(props["タイトル"])
        print(f"  [コピー完了] {title}")

        # アーカイブ済に更新 → ゴミ箱に移動
        notion_request("PATCH", f"/pages/{page_id}", {
            "properties": {"アーカイブ状態": {"select": {"name": "アーカイブ済"}}}
        })
        archive_page(page_id)
        print(f"  [削除完了] {title}")

    print(f"[週報] 処理完了: {len(pages)}件")


def main():
    dates = get_dates()
    print(f"=== 週次コピー処理開始 ===")
    print(f"日報対象: {dates['sunday']} 〜 {dates['thursday']}")
    print(f"週報対象: {dates['monday']} 〜 {dates['last_sunday']}")
    copy_nissho_records(dates["sunday"], dates["thursday"])
    copy_shyuho_records(dates["monday"], dates["last_sunday"])
    print(f"=== 週次コピー処理完了 ===")


if __name__ == "__main__":
    main()
