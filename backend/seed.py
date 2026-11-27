"""清空資料庫並塞入一組示範資料，方便展示與檢視畫面。

跑法：./.venv/bin/python seed.py（先 docker compose up -d 啟動 PostgreSQL）
注意：會重建 DATABASE_URL 指到的資料庫裡的應用程式資料表。

三個示範帳號密碼都是 demo1234：amy / ben / cindy
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from auth import hash_password
from models import (
    Availability, Base, Chore, Expense, ExpenseShare, GarbageSchedule, Group, Member,
    SessionLocal, Settlement, SettlementTransfer, User, now,
)
from notifications import TAIPEI, create_due_reminders, notify
from split import equal_shares, pairwise_debts


def seed(db: Session) -> None:
    today = now().astimezone(TAIPEI).date()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)
    users = {}
    for name in ("amy", "ben", "cindy"):
        user = User(username=name, password_hash=hash_password("demo1234"))
        db.add(user)
        users[name] = user
    db.flush()

    group = Group(name="民生東路 3F", created_by_user_id=users["amy"].id)
    db.add(group)
    db.flush()

    mid = {}
    members = {}
    for name, user in users.items():
        member = Member(group_id=group.id, user_id=user.id)
        db.add(member)
        db.flush()
        mid[name] = member.id
        members[name] = member

    # (日期, 說明, 墊付人, 金額, 分攤成員, 自訂分攤額 or None)
    entries = [
        ("2026-09-01", "衛生紙", "amy", 101, ["amy", "ben", "cindy"], None),
        ("2026-09-02", "網路費 9 月", "ben", 1200, ["amy", "ben", "cindy"], None),
        ("2026-09-03", "洗衣精", "cindy", 259, ["amy", "cindy"], None),
        ("2026-09-05", "電費 7-8 月", "amy", 2340, ["amy", "ben", "cindy"], None),
        ("2026-09-07", "火鍋食材", "ben", 890, ["amy", "ben", "cindy"],
         {"amy": 300, "ben": 300, "cindy": 290}),
    ]

    created = []
    for spent_on, description, payer, amount, people, custom in entries:
        ids = [mid[p] for p in people]
        shares = (
            {mid[p]: amt for p, amt in custom.items()}
            if custom
            else equal_shares(amount, ids, mid[payer])
        )
        expense = Expense(
            group_id=group.id,
            payer_member_id=mid[payer],
            amount=amount,
            description=description,
            spent_on=date.fromisoformat(spent_on),
            due_on=tomorrow if description == "電費 7-8 月" else None,
            created_by_member_id=mid[payer],
            shares=[ExpenseShare(member_id=m, amount=a) for m, a in shares.items()],
        )
        db.add(expense)
        created.append(expense)
    db.flush()

    # 把最早兩筆結算掉，讓「結算紀錄」與「已結項目」有東西可看
    to_settle = created[:2]
    settlement = Settlement(group_id=group.id, initiated_by_member_id=mid["amy"])
    db.add(settlement)
    db.flush()

    rows = [
        {"payer_id": e.payer_member_id, "shares": {s.member_id: s.amount for s in e.shares}}
        for e in to_settle
    ]
    debts = pairwise_debts(rows)
    for (debtor, creditor), amount in debts.items():
        db.add(
            SettlementTransfer(
                settlement_id=settlement.id,
                from_member_id=debtor,
                to_member_id=creditor,
                amount=amount,
            )
        )
    for e in to_settle:
        e.settlement_id = settlement.id

    bill = next(e for e in created if e.due_on is not None)
    notify(
        db, members["amy"], {share.member_id for share in bill.shares}, "expense_created",
        f"amy 新增支出「{bill.description}」。", expense_id=bill.id,
    )
    notify(
        db, members["amy"], {member_id for pair in debts for member_id in pair},
        "settlement_created", "amy 結算了 2 筆支出，請查看轉帳清單。", settlement_id=settlement.id,
    )

    arrival = datetime.combine(tomorrow, time(18, 30), tzinfo=TAIPEI)
    truck = GarbageSchedule(group_id=group.id, arrives_at=arrival, location="民生東路巷口")
    db.add_all([
        truck,
        Availability(
            group_id=group.id, member_id=mid["ben"],
            starts_at=arrival - timedelta(minutes=30), ends_at=arrival + timedelta(minutes=30),
        ),
        Availability(
            group_id=group.id, member_id=mid["cindy"],
            starts_at=arrival + timedelta(minutes=30), ends_at=arrival + timedelta(hours=1),
        ),
    ])
    db.flush()
    db.add_all([
        Chore(
            group_id=group.id, title="倒垃圾", scheduled_at=arrival,
            created_by_member_id=mid["amy"], assigned_member_id=mid["ben"],
            garbage_schedule_id=truck.id,
            rotation_member_ids=[mid["ben"], mid["cindy"]],
        ),
        Chore(
            group_id=group.id, title="打掃公共區域",
            scheduled_at=datetime.combine(yesterday, time(17), tzinfo=TAIPEI),
            created_by_member_id=mid["amy"], assigned_member_id=mid["cindy"],
            completed_at=datetime.combine(yesterday, time(17, 30), tzinfo=TAIPEI),
        ),
    ])
    for member in members.values():
        create_due_reminders(db, member, today)


def main() -> None:
    with SessionLocal.begin() as db:
        conn = db.connection()
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        seed(db)
    print("示範資料已建立。登入：amy / ben / cindy，密碼都是 demo1234")


if __name__ == "__main__":
    main()
