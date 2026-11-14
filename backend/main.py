"""租屋分帳 API。"""

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import create_token, current_user, get_db, hash_password, verify_password
from models import (
    Expense, ExpenseShare, Group, Member, Settlement, SettlementTransfer, User, init_db,
)
from split import equal_shares, pairwise_debts, validate_shares

# 前端透過 Vite 的 proxy 以同源方式呼叫（見 frontend/vite.config.js），所以不需要 CORS。
app = FastAPI(title="租屋分帳")
init_db()


# ---------- 請求 / 回應格式 ----------

class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    token: str
    user_id: int
    username: str


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class MemberOut(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    is_admin: bool


class GroupOut(BaseModel):
    id: int
    name: str
    my_member_id: int
    i_am_admin: bool
    members: list[MemberOut]


class ExpenseIn(BaseModel):
    payer_member_id: int
    amount: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=200)
    spent_on: date
    # 二選一：給 participant_member_ids 就平分，給 shares 就用自訂金額
    participant_member_ids: list[int] | None = None
    shares: dict[int, int] | None = None


class ExpenseOut(BaseModel):
    id: int
    payer_member_id: int
    amount: int
    description: str
    spent_on: date
    shares: dict[int, int]
    settlement_id: int | None
    is_settled: bool


class DebtOut(BaseModel):
    from_member_id: int
    to_member_id: int
    amount: int


class SettlementIn(BaseModel):
    expense_ids: list[int] = Field(min_length=1)


class SettlementOut(BaseModel):
    id: int
    initiated_by_member_id: int
    created_at: str
    expense_ids: list[int]
    transfers: list[DebtOut]


class MemberStatusIn(BaseModel):
    status: str = Field(pattern="^(active|deactivated|removed)$")


# ---------- 共用檢查 ----------

def require_member(group_id: int, user: User, db: Session) -> Member:
    """確認登入者是這個群組的成員，並回傳他的 Member。被移出的人視同不在。"""
    member = db.scalar(
        select(Member).where(
            Member.group_id == group_id, Member.user_id == user.id, Member.status != "removed"
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到群組，或你不是這個群組的成員")
    return member


def require_admin(group: Group, user: User) -> None:
    if group.created_by_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有管理員可以做這件事")


def get_group(group_id: int, db: Session) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到群組")
    return group


def to_expense_out(e: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=e.id,
        payer_member_id=e.payer_member_id,
        amount=e.amount,
        description=e.description,
        spent_on=e.spent_on,
        shares={s.member_id: s.amount for s in e.shares},
        settlement_id=e.settlement_id,
        is_settled=e.is_settled,
    )


def resolve_shares(body: ExpenseIn, group_id: int, db: Session) -> dict[int, int]:
    """把請求換算成 {member_id: 分攤額}，並確認每個人都真的在這個群組、還沒停用。"""
    if (body.participant_member_ids is None) == (body.shares is None):
        raise HTTPException(400, "participant_member_ids 與 shares 請擇一提供")

    ids = list(body.shares) if body.shares else body.participant_member_ids
    if not ids:
        raise HTTPException(400, "至少要有一個分攤對象")
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "分攤對象有重複")

    active_ids = set(
        db.scalars(
            select(Member.id).where(Member.group_id == group_id, Member.status == "active")
        )
    )
    for mid in [*ids, body.payer_member_id]:
        if mid not in active_ids:
            raise HTTPException(400, f"成員 {mid} 不在這個群組，或已停用")

    try:
        if body.shares:
            validate_shares(body.amount, body.shares)
            return body.shares
        return equal_shares(body.amount, ids, body.payer_member_id)
    except ValueError as err:
        raise HTTPException(400, str(err))


# ---------- 帳號 ----------

@app.post("/auth/register", response_model=TokenOut)
def register(body: Credentials, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "這個帳號名稱已經有人用了")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return TokenOut(token=create_token(user.id), user_id=user.id, username=user.username)


@app.post("/auth/login", response_model=TokenOut)
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "帳號或密碼不對")
    return TokenOut(token=create_token(user.id), user_id=user.id, username=user.username)


# ---------- 群組 ----------

@app.post("/groups", response_model=GroupOut)
def create_group(
    body: GroupIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    group = Group(name=body.name, created_by_user_id=user.id)
    db.add(group)
    db.flush()
    db.add(Member(group_id=group.id, user_id=user.id))
    db.commit()
    return group_detail(group.id, user, db)


@app.get("/groups", response_model=list[GroupOut])
def list_groups(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = db.scalars(
        select(Member.group_id).where(Member.user_id == user.id, Member.status != "removed")
    ).all()
    return [group_detail(gid, user, db) for gid in ids]


@app.get("/groups/{group_id}", response_model=GroupOut)
def group_detail(
    group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    group = get_group(group_id, db)
    me = require_member(group_id, user, db)
    members = db.scalars(
        select(Member).where(Member.group_id == group_id, Member.status != "removed")
    ).all()
    return GroupOut(
        id=group.id,
        name=group.name,
        my_member_id=me.id,
        i_am_admin=group.created_by_user_id == user.id,
        members=[
            MemberOut(
                id=m.id,
                user_id=m.user_id,
                username=m.user.username,
                status=m.status,
                is_admin=m.user_id == group.created_by_user_id,
            )
            for m in members
        ],
    )


@app.patch("/groups/{group_id}/members/{member_id}", response_model=GroupOut)
def set_member_status(
    group_id: int,
    member_id: int,
    body: MemberStatusIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """停用 / 復用任何人都可以；移出群組限管理員。"""
    group = get_group(group_id, db)
    require_member(group_id, user, db)
    target = db.get(Member, member_id)
    if target is None or target.group_id != group_id:
        raise HTTPException(404, "找不到這個成員")
    if body.status == "removed":
        require_admin(group, user)
        if target.user_id == group.created_by_user_id:
            raise HTTPException(400, "管理員不能把自己移出群組")
    target.status = body.status
    db.commit()
    return group_detail(group_id, user, db)


# ---------- 支出 ----------

@app.post("/groups/{group_id}/expenses", response_model=ExpenseOut)
def create_expense(
    group_id: int,
    body: ExpenseIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    me = require_member(group_id, user, db)
    shares = resolve_shares(body, group_id, db)
    expense = Expense(
        group_id=group_id,
        payer_member_id=body.payer_member_id,
        amount=body.amount,
        description=body.description,
        spent_on=body.spent_on,
        created_by_member_id=me.id,
        shares=[ExpenseShare(member_id=mid, amount=amt) for mid, amt in shares.items()],
    )
    db.add(expense)
    db.commit()
    return to_expense_out(expense)


@app.get("/groups/{group_id}/expenses", response_model=list[ExpenseOut])
def list_expenses(
    group_id: int,
    settled: bool | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_member(group_id, user, db)
    query = select(Expense).where(Expense.group_id == group_id)
    if settled is True:
        query = query.where(Expense.settlement_id.is_not(None))
    elif settled is False:
        query = query.where(Expense.settlement_id.is_(None))
    rows = db.scalars(query.order_by(Expense.spent_on.desc(), Expense.id.desc())).all()
    return [to_expense_out(e) for e in rows]


def get_editable_expense(group_id: int, expense_id: int, db: Session) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.group_id != group_id:
        raise HTTPException(404, "找不到這筆支出")
    if expense.is_settled:
        raise HTTPException(409, "這筆已經結算過了，要先取消該次結算才能修改")
    return expense


@app.put("/groups/{group_id}/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    group_id: int,
    expense_id: int,
    body: ExpenseIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_member(group_id, user, db)
    expense = get_editable_expense(group_id, expense_id, db)
    shares = resolve_shares(body, group_id, db)

    expense.payer_member_id = body.payer_member_id
    expense.amount = body.amount
    expense.description = body.description
    expense.spent_on = body.spent_on
    # 先刪舊的分攤列並寫進資料庫，再加新的；否則同一次 flush 會撞到
    # UNIQUE(expense_id, member_id)。
    expense.shares.clear()
    db.flush()
    expense.shares = [ExpenseShare(member_id=mid, amount=amt) for mid, amt in shares.items()]
    db.commit()
    return to_expense_out(expense)


@app.delete("/groups/{group_id}/expenses/{expense_id}", status_code=204)
def delete_expense(
    group_id: int,
    expense_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_member(group_id, user, db)
    db.delete(get_editable_expense(group_id, expense_id, db))
    db.commit()


# ---------- 欠款 ----------

def debts_for(expenses: list[Expense]) -> list[DebtOut]:
    rows = [
        {"payer_id": e.payer_member_id, "shares": {s.member_id: s.amount for s in e.shares}}
        for e in expenses
    ]
    return [
        DebtOut(from_member_id=a, to_member_id=b, amount=amt)
        for (a, b), amt in pairwise_debts(rows).items()
    ]


@app.get("/groups/{group_id}/balance", response_model=list[DebtOut])
def balance(group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """只算未結的支出：誰欠誰多少。"""
    require_member(group_id, user, db)
    unsettled = db.scalars(
        select(Expense).where(Expense.group_id == group_id, Expense.settlement_id.is_(None))
    ).all()
    return debts_for(list(unsettled))


# ---------- 結算 ----------

@app.post("/groups/{group_id}/settlements", response_model=SettlementOut)
def create_settlement(
    group_id: int,
    body: SettlementIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """挑幾筆未結的支出一起算清，算出的結果凍結存下來。"""
    me = require_member(group_id, user, db)
    ids = set(body.expense_ids)
    expenses = db.scalars(select(Expense).where(Expense.id.in_(ids))).all()

    if len(expenses) != len(ids):
        raise HTTPException(404, "有些支出找不到")
    for e in expenses:
        if e.group_id != group_id:
            raise HTTPException(400, f"支出 {e.id} 不屬於這個群組")
        if e.is_settled:
            raise HTTPException(409, f"支出 {e.id} 已經結算過了")

    settlement = Settlement(group_id=group_id, initiated_by_member_id=me.id)
    db.add(settlement)
    db.flush()
    for debt in debts_for(list(expenses)):
        db.add(
            SettlementTransfer(
                settlement_id=settlement.id,
                from_member_id=debt.from_member_id,
                to_member_id=debt.to_member_id,
                amount=debt.amount,
            )
        )
    for e in expenses:
        e.settlement_id = settlement.id
    db.commit()
    return to_settlement_out(settlement)


def to_settlement_out(s: Settlement) -> SettlementOut:
    return SettlementOut(
        id=s.id,
        initiated_by_member_id=s.initiated_by_member_id,
        created_at=s.created_at.isoformat(),
        expense_ids=sorted(e.id for e in s.expenses),
        transfers=[
            DebtOut(from_member_id=t.from_member_id, to_member_id=t.to_member_id, amount=t.amount)
            for t in s.transfers
        ],
    )


@app.get("/groups/{group_id}/settlements", response_model=list[SettlementOut])
def list_settlements(
    group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_member(group_id, user, db)
    rows = db.scalars(
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .order_by(Settlement.created_at.desc())
    ).all()
    return [to_settlement_out(s) for s in rows]


@app.delete("/groups/{group_id}/settlements/{settlement_id}", status_code=204)
def cancel_settlement(
    group_id: int,
    settlement_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """取消結算：涵蓋的支出退回未結，可以再編輯。"""
    require_member(group_id, user, db)
    settlement = db.get(Settlement, settlement_id)
    if settlement is None or settlement.group_id != group_id:
        raise HTTPException(404, "找不到這次結算")
    for e in settlement.expenses:
        e.settlement_id = None
    db.delete(settlement)
    db.commit()
