"""端到端檢查：註冊 → 開群組 → 記帳 → 看欠款 → 結算 → 取消結算。

跑法：./.venv/bin/python test_api.py
"""

import os
import tempfile

DB_FILE = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def auth(username: str) -> dict:
    r = client.post("/auth/register", json={"username": username, "password": "hunter22"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def main() -> None:
    # --- 帳號 ---
    amy = auth("amy")
    ben = auth("ben")

    assert client.post(
        "/auth/register", json={"username": "amy", "password": "hunter22"}
    ).status_code == 400, "重複帳號應該被擋"
    assert client.post(
        "/auth/login", json={"username": "amy", "password": "wrongpass"}
    ).status_code == 401, "密碼錯應該被擋"
    assert client.get("/groups").status_code == 401, "沒帶 token 應該被擋"

    # --- 群組 ---
    group = client.post("/groups", json={"name": "民生東路 3F"}, headers=amy).json()
    gid = group["id"]
    amy_mid = group["my_member_id"]
    assert group["i_am_admin"] is True

    assert client.get(f"/groups/{gid}", headers=ben).status_code == 404, "非成員看不到群組"

    # --- 邀請連結：amy 產生，ben 用它加入 ---
    assert client.post(f"/groups/{gid}/invites", headers=ben).status_code == 404, "非成員不能產生"
    token = client.post(f"/groups/{gid}/invites", headers=amy).json()["token"]
    assert client.post("/invites/not-a-token/join", headers=ben).status_code == 404
    assert client.post(f"/invites/{token}/join").status_code == 401, "要先登入"
    joined = client.post(f"/invites/{token}/join", headers=ben)
    assert joined.status_code == 200, joined.text
    ben_mid = joined.json()["my_member_id"]
    assert len(joined.json()["members"]) == 2
    # 重複加入不會多一個成員
    assert len(client.post(f"/invites/{token}/join", headers=ben).json()["members"]) == 2

    # 過期的連結要被擋
    from datetime import datetime
    from models import Invite, SessionLocal
    from sqlalchemy import select

    db = SessionLocal()
    db.scalar(select(Invite).where(Invite.token == token)).expires_at = datetime(2000, 1, 1)
    db.commit()
    db.close()
    cindy = auth("cindy")
    assert client.post(f"/invites/{token}/join", headers=cindy).status_code == 410

    # --- 記帳：平分除不盡，餘數給付款人 ---
    e1 = client.post(
        f"/groups/{gid}/expenses",
        json={
            "payer_member_id": amy_mid,
            "amount": 101,
            "description": "衛生紙",
            "spent_on": "2026-09-01",
            "participant_member_ids": [amy_mid, ben_mid],
        },
        headers=amy,
    ).json()
    assert e1["shares"] == {str(amy_mid): 51, str(ben_mid): 50}, e1["shares"]
    assert e1["is_settled"] is False

    # --- 記帳：自訂分攤額 ---
    e2 = client.post(
        f"/groups/{gid}/expenses",
        json={
            "payer_member_id": ben_mid,
            "amount": 300,
            "description": "網路費",
            "spent_on": "2026-09-02",
            "shares": {str(amy_mid): 200, str(ben_mid): 100},
        },
        headers=ben,
    ).json()
    assert e2["shares"] == {str(amy_mid): 200, str(ben_mid): 100}

    # 自訂金額加總對不上要被擋
    bad = client.post(
        f"/groups/{gid}/expenses",
        json={
            "payer_member_id": amy_mid,
            "amount": 300,
            "description": "亂填",
            "spent_on": "2026-09-02",
            "shares": {str(amy_mid): 100, str(ben_mid): 100},
        },
        headers=amy,
    )
    assert bad.status_code == 400, bad.text

    # --- 欠款：ben 欠 amy 50，amy 欠 ben 200 → 相抵後 amy 欠 ben 150 ---
    debts = client.get(f"/groups/{gid}/balance", headers=amy).json()
    assert debts == [
        {"from_member_id": amy_mid, "to_member_id": ben_mid, "amount": 150}
    ], debts

    # --- 編輯未結的帳 ---
    edited = client.put(
        f"/groups/{gid}/expenses/{e1['id']}",
        json={
            "payer_member_id": amy_mid,
            "amount": 200,
            "description": "衛生紙（改）",
            "spent_on": "2026-09-01",
            "participant_member_ids": [amy_mid, ben_mid],
        },
        headers=ben,
    ).json()
    assert edited["shares"] == {str(amy_mid): 100, str(ben_mid): 100}
    assert edited["description"] == "衛生紙（改）"

    # --- 只結算其中一筆 ---
    s = client.post(
        f"/groups/{gid}/settlements", json={"expense_ids": [e1["id"]]}, headers=amy
    ).json()
    assert s["expense_ids"] == [e1["id"]]
    assert s["transfers"] == [
        {"from_member_id": ben_mid, "to_member_id": amy_mid, "amount": 100}
    ], s["transfers"]

    # 已結的帳不再算進欠款，另一筆還在
    debts = client.get(f"/groups/{gid}/balance", headers=amy).json()
    assert debts == [
        {"from_member_id": amy_mid, "to_member_id": ben_mid, "amount": 200}
    ], debts

    # 已結的帳鎖住，不能改也不能刪
    assert client.put(
        f"/groups/{gid}/expenses/{e1['id']}",
        json={
            "payer_member_id": amy_mid,
            "amount": 999,
            "description": "偷改",
            "spent_on": "2026-09-01",
            "participant_member_ids": [amy_mid, ben_mid],
        },
        headers=amy,
    ).status_code == 409
    assert client.delete(f"/groups/{gid}/expenses/{e1['id']}", headers=amy).status_code == 409

    # 同一筆不能結算兩次
    assert client.post(
        f"/groups/{gid}/settlements", json={"expense_ids": [e1["id"]]}, headers=amy
    ).status_code == 409

    # 紀錄還留著
    all_expenses = client.get(f"/groups/{gid}/expenses", headers=amy).json()
    assert len(all_expenses) == 2
    assert [e for e in all_expenses if e["id"] == e1["id"]][0]["is_settled"] is True

    # --- 取消結算：帳退回未結，又可以改了 ---
    assert client.delete(f"/groups/{gid}/settlements/{s['id']}", headers=amy).status_code == 204
    assert client.get(f"/groups/{gid}/settlements", headers=amy).json() == []
    debts = client.get(f"/groups/{gid}/balance", headers=amy).json()
    assert debts == [
        {"from_member_id": amy_mid, "to_member_id": ben_mid, "amount": 100}
    ], debts
    assert client.delete(f"/groups/{gid}/expenses/{e1['id']}", headers=amy).status_code == 204

    # --- 停用成員後不能再記到他頭上 ---
    client.patch(f"/groups/{gid}/members/{ben_mid}", json={"status": "deactivated"}, headers=amy)
    blocked = client.post(
        f"/groups/{gid}/expenses",
        json={
            "payer_member_id": amy_mid,
            "amount": 100,
            "description": "搬走之後的帳",
            "spent_on": "2026-09-10",
            "participant_member_ids": [amy_mid, ben_mid],
        },
        headers=amy,
    )
    assert blocked.status_code == 400, blocked.text

    # 但他之前的未結欠款照算
    debts = client.get(f"/groups/{gid}/balance", headers=amy).json()
    assert debts == [{"from_member_id": amy_mid, "to_member_id": ben_mid, "amount": 200}], debts

    # --- 只有管理員能把人移出群組 ---
    assert client.patch(
        f"/groups/{gid}/members/{amy_mid}", json={"status": "removed"}, headers=ben
    ).status_code == 403
    assert client.patch(
        f"/groups/{gid}/members/{ben_mid}", json={"status": "removed"}, headers=amy
    ).status_code == 200

    print("test_api.py 全部檢查通過")


if __name__ == "__main__":
    main()
