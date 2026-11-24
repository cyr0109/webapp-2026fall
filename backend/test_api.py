"""端到端檢查：註冊 → 開群組 → 記帳 → 看欠款 → 結算 → 取消結算。

跑法：./.venv/bin/python test_api.py
"""

import os
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/housemate_test"
)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from models import Base, engine, now  # noqa: E402
from notifications import TAIPEI  # noqa: E402

# 每次從空資料庫開始
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

client = TestClient(app)


def auth(username: str) -> dict:
    r = client.post("/auth/register", json={"username": username, "password": "hunter22"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def verify_milestone_3() -> None:
    admin, roommate, third, outsider = map(auth, ("ms3admin", "ms3mate", "ms3third", "ms3outsider"))
    group = client.post("/groups", json={"name": "MS3 測試"}, headers=admin).json()
    root = f"/groups/{group['id']}"
    token = client.post(f"{root}/invites", headers=admin).json()["token"]
    mate = client.post(f"/invites/{token}/join", headers=roommate).json()["my_member_id"]
    client.post(f"/invites/{token}/join", headers=third)
    payer = group["my_member_id"]
    today = now().astimezone(TAIPEI).date()
    expense_body = {
        "payer_member_id": payer, "amount": 100, "description": "MS3 網路費",
        "spent_on": str(today), "due_on": str(today + timedelta(days=2)),
        "participant_member_ids": [payer, mate],
    }
    expenses = f"{root}/expenses"
    pending = client.post(expenses, json=expense_body, headers=admin)
    assert pending.status_code == 200, pending.text
    expense = f"{expenses}/{pending.json()['id']}"
    inbox = f"{root}/notifications"
    response = client.get(inbox, headers=roommate).json()
    assert response["unread_count"] == 1
    [notice] = response["items"]
    assert notice["event_type"] == "expense_created"
    read_url = f"{inbox}/{notice['id']}/read"
    assert client.patch(read_url, headers=admin).status_code == 404
    assert client.get(inbox, headers=outsider).status_code == 404
    assert client.patch(read_url, headers=roommate).json()["is_read"]

    # Old callers that omit the field keep the current deadline.
    without_due = {key: value for key, value in expense_body.items() if key != "due_on"}
    assert client.put(expense, json=without_due, headers=admin).json()["due_on"] == expense_body["due_on"]
    assert client.get(inbox, headers=roommate).json()["unread_count"] == 0
    for delta in (1, 0, -1):
        expense_body["due_on"] = str(today + timedelta(days=delta))
        assert client.put(expense, json=expense_body, headers=admin).json()["due_on"] == expense_body["due_on"]
        for _ in range(2):
            reminders = [
                n for n in client.get(inbox, headers=roommate).json()["items"]
                if n["event_type"] == "expense_due"
            ]
            assert len(reminders) == 2 - delta
            assert expense_body["due_on"] in reminders[0]["summary"]

    # A pending reminder must not be generated once the expense is settled.
    expense_body["due_on"] = str(today - timedelta(days=2))
    client.put(expense, json=expense_body, headers=admin)
    settlement = f"{root}/settlements"
    selection = {"expense_ids": [pending.json()["id"]]}
    created = client.post(settlement, json=selection, headers=roommate).json()
    url = f"{settlement}/{created['id']}"
    assert client.delete(url, headers=third).status_code == 403
    assert sum(n["event_type"] == "expense_due" for n in client.get(inbox, headers=roommate).json()["items"]) == 3
    assert [n["event_type"] for n in client.get(inbox, headers=admin).json()["items"]] == ["settlement_created"]
    assert client.delete(url, headers=admin).status_code == 204
    created = client.post(settlement, json=selection, headers=roommate).json()
    assert client.delete(f"{settlement}/{created['id']}", headers=roommate).status_code == 204
    assert client.put(expense, json={**expense_body, "due_on": None}, headers=admin).json()["due_on"] is None

    # Two overlapping slots yield one matching member. Start is inclusive and end is exclusive.
    availability = f"{root}/availabilities"
    slot = {"starts_at": "2026-12-01T18:00:00+08:00", "ends_at": "2026-12-01T19:00:00+08:00"}
    assert client.post(availability, json={**slot, "ends_at": slot["starts_at"]}, headers=roommate).status_code == 422
    ids = []
    for _ in range(2):
        row = client.post(availability, json=slot, headers=roommate)
        assert row.status_code == 201, row.text
        ids.append(row.json()["id"])
    assert client.put(f"{availability}/{ids[0]}", json=slot, headers=admin).status_code == 403
    assert client.get(availability, headers=outsider).status_code == 404
    assert client.put(f"{availability}/{ids[0]}", json=slot, headers=roommate).status_code == 200
    garbage = f"{root}/garbage-schedules"
    schedule = {"arrives_at": slot["starts_at"], "location": "巷口"}
    assert client.post(garbage, json=schedule, headers=roommate).status_code == 403
    assert client.post(garbage, json=schedule, headers=outsider).status_code == 404
    arrival = client.post(garbage, json=schedule, headers=admin)
    assert arrival.status_code == 201, arrival.text
    assert arrival.json()["available_member_ids"] == [mate]
    arrival_id = arrival.json()["id"]
    assert client.put(f"{garbage}/{arrival_id}", json={**schedule, "arrives_at": slot["ends_at"]},
                      headers=admin).json()["available_member_ids"] == []
    assert client.delete(f"{availability}/{ids[0]}", headers=roommate).status_code == 204

    chores = f"{root}/chores"
    chore = {"title": "倒垃圾", "scheduled_at": slot["ends_at"],
             "assigned_member_id": mate, "garbage_schedule_id": arrival_id}
    outsider_id = client.post("/groups", json={"name": "其他群組"}, headers=outsider).json()["my_member_id"]
    assert client.post(chores, json={**chore, "assigned_member_id": outsider_id}, headers=admin).status_code == 400
    client.patch(f"{root}/members/{mate}", json={"status": "deactivated"}, headers=admin)
    assert client.post(chores, json=chore, headers=admin).status_code == 400
    client.patch(f"{root}/members/{mate}", json={"status": "active"}, headers=admin)
    task = client.post(chores, json=chore, headers=admin)
    assert task.status_code == 201, task.text
    task_url = f"{chores}/{task.json()['id']}"
    assert client.put(task_url, json=chore, headers=roommate).status_code == 403
    assert client.put(task_url, json=chore, headers=admin).status_code == 200
    assert client.patch(f"{task_url}/complete", headers=admin).status_code == 403
    completed = client.patch(f"{task_url}/complete", headers=roommate).json()["completed_at"]
    assert completed and client.patch(f"{task_url}/complete", headers=roommate).json()["completed_at"] == completed
    assert client.delete(f"{garbage}/{arrival_id}", headers=admin).status_code == 204
    [saved] = client.get(chores, headers=roommate).json()
    assert saved["completed_at"] == completed and saved["garbage_schedule_id"] is None
    assert client.delete(task_url, headers=admin).status_code == 204
    print("MS3 復原權限、通知與期限、空檔與垃圾車、家務檢查通過")


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
    [t] = s["transfers"]
    assert (t["from_member_id"], t["to_member_id"], t["amount"]) == (ben_mid, amy_mid, 100), t
    assert t["paid_at"] is None, "結算後只是待付款，還沒付"

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

    # --- 付款確認：只有收款人能按，按過就不能復原結算（停用的 ben 也能收錢）---
    s = client.post(
        f"/groups/{gid}/settlements", json={"expense_ids": [e2["id"]]}, headers=amy
    ).json()
    [t] = s["transfers"]  # amy 欠 ben 200
    paid_url = f"/groups/{gid}/settlements/{s['id']}/transfers/{t['id']}/paid"
    assert client.post(paid_url, headers=amy).status_code == 403, "付款人不能自己確認"
    r = client.post(paid_url, headers=ben)
    assert r.status_code == 200, r.text
    assert r.json()["transfers"][0]["paid_at"] is not None
    assert client.post(paid_url, headers=ben).status_code == 409, "不能重複確認"
    assert client.delete(f"/groups/{gid}/settlements/{s['id']}", headers=amy).status_code == 409

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
    verify_milestone_3()
