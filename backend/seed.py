"""清空資料庫並塞入一組示範資料，方便展示與檢視畫面。

跑法：./.venv/bin/python seed.py（先 docker compose up -d 啟動 PostgreSQL）
注意：會刪掉 DATABASE_URL 指到的資料庫裡所有資料表。

三個示範帳號密碼都是 demo1234：amy / ben / cindy
"""

from datetime import date

from auth import hash_password
from models import (
    Base, Expense, ExpenseShare, Group, Member, Settlement, SettlementTransfer, User,
    SessionLocal, engine,
)
from split import equal_shares, pairwise_debts


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

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
    for name, user in users.items():
        member = Member(group_id=group.id, user_id=user.id)
        db.add(member)
        db.flush()
        mid[name] = member.id

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
    for (debtor, creditor), amount in pairwise_debts(rows).items():
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

    db.commit()
    db.close()
    print("示範資料已建立。登入：amy / ben / cindy，密碼都是 demo1234")


if __name__ == "__main__":
    main()
