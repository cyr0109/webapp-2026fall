"""HouseMate API。"""

import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import create_token, current_user, get_db, hash_password, verify_password
from group_access import get_group, require_admin, require_member
from household import router as household_router
from models import (
    Expense, ExpenseShare, Group, Invite, Member, Settlement, SettlementTransfer, User, init_db, now,
)
from notifications import notify, router as notification_router
from split import equal_shares, pairwise_debts, validate_shares

INVITE_TTL = timedelta(days=7)

# 前端透過 Vite 的 proxy 以同源方式呼叫（見 frontend/vite.config.js），所以不需要 CORS。
app = FastAPI(title="HouseMate")
app.include_router(household_router)
app.include_router(notification_router)
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
    due_on: date | None = None
    # 二選一：給 participant_member_ids 就平分，給 shares 就用自訂金額
    participant_member_ids: list[int] | None = None
    shares: dict[int, int] | None = None


class ExpenseOut(BaseModel):
    id: int
    payer_member_id: int
    amount: int
    description: str
    spent_on: date
    due_on: date | None
    shares: dict[int, int]
    settlement_id: int | None
    is_settled: bool


class DebtOut(BaseModel):
    from_member_id: int
    to_member_id: int
    amount: int


class SettlementIn(BaseModel):
    expense_ids: list[int] = Field(min_length=1)


class TransferOut(DebtOut):
    id: int
    paid_at: str | None
    due_on: date | None


class SettlementOut(BaseModel):
    id: int
    initiated_by_member_id: int
    created_at: str
    expense_ids: list[int]
    transfers: list[TransferOut]


class MemberStatusIn(BaseModel):
    status: str = Field(pattern="^(active|deactivated|removed)$")


class InviteOut(BaseModel):
    token: str
    expires_at: datetime


# ---------- 共用檢查 ----------

def to_expense_out(e: Expense) -> ExpenseOut:
    return ExpenseOut(
        id=e.id,
        payer_member_id=e.payer_member_id,
        amount=e.amount,
        description=e.description,
        spent_on=e.spent_on,
        due_on=e.due_on,
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


# ---------- 邀請連結 ----------

def utcnow_naive() -> datetime:
    # DateTime 欄位存回來不帶時區，比較時兩邊都用不帶時區的 UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.post("/groups/{group_id}/invites", response_model=InviteOut)
def create_invite(
    group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """任何成員都能產生邀請連結，7 天內可重複使用。"""
    get_group(group_id, db)
    me = require_member(group_id, user, db)
    invite = Invite(
        group_id=group_id,
        token=secrets.token_urlsafe(24),
        created_by_member_id=me.id,
        expires_at=utcnow_naive() + INVITE_TTL,
    )
    db.add(invite)
    db.commit()
    return InviteOut(token=invite.token, expires_at=invite.expires_at)


@app.post("/invites/{token}/join", response_model=GroupOut)
def join_by_invite(token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """用邀請連結加入。已是成員就直接回群組；被停用或移出的人會恢復為正常成員。"""
    invite = db.scalar(select(Invite).where(Invite.token == token))
    if invite is None:
        raise HTTPException(404, "邀請連結無效")
    if invite.expires_at < utcnow_naive():
        raise HTTPException(410, "邀請連結已過期，請向室友要新的連結")
    member = db.scalar(
        select(Member).where(Member.group_id == invite.group_id, Member.user_id == user.id)
    )
    if member is None:
        db.add(Member(group_id=invite.group_id, user_id=user.id))
    else:
        member.status = "active"
    db.commit()
    return group_detail(invite.group_id, user, db)


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
        due_on=body.due_on,
        created_by_member_id=me.id,
        shares=[ExpenseShare(member_id=mid, amount=amt) for mid, amt in shares.items()],
    )
    db.add(expense)
    db.flush()
    notify(
        db, me, {mid for mid, amount in shares.items() if amount > 0}, "expense_created",
        f"{user.username} 新增支出「{expense.description}」。", expense_id=expense.id,
    )
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
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id, Expense.group_id == group_id)
        .with_for_update(of=Expense)
    )
    if expense is None:
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
    if "due_on" in body.model_fields_set:
        expense.due_on = body.due_on
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
    expenses = db.scalars(
        select(Expense).where(Expense.id.in_(ids)).order_by(Expense.id).with_for_update(of=Expense)
    ).all()

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
    debts = debts_for(list(expenses))
    due_dates: dict[tuple[int, int], date] = {}
    for expense in expenses:
        if expense.due_on is None:
            continue
        for share in expense.shares:
            if share.amount > 0 and share.member_id != expense.payer_member_id:
                pair = (share.member_id, expense.payer_member_id)
                due_dates[pair] = min(due_dates.get(pair, expense.due_on), expense.due_on)
    for debt in debts:
        db.add(
            SettlementTransfer(
                settlement_id=settlement.id,
                from_member_id=debt.from_member_id,
                to_member_id=debt.to_member_id,
                amount=debt.amount,
                due_on=due_dates.get((debt.from_member_id, debt.to_member_id)),
            )
        )
    for e in expenses:
        e.settlement_id = settlement.id
    notify(
        db, me, {mid for debt in debts for mid in (debt.from_member_id, debt.to_member_id)},
        "settlement_created", f"{user.username} 結算了 {len(expenses)} 筆支出，請查看轉帳清單。",
        settlement_id=settlement.id,
    )
    db.commit()
    return to_settlement_out(settlement)


def to_settlement_out(s: Settlement) -> SettlementOut:
    return SettlementOut(
        id=s.id,
        initiated_by_member_id=s.initiated_by_member_id,
        created_at=s.created_at.isoformat(),
        expense_ids=sorted(e.id for e in s.expenses),
        transfers=[
            TransferOut(
                id=t.id,
                from_member_id=t.from_member_id,
                to_member_id=t.to_member_id,
                amount=t.amount,
                due_on=t.due_on,
                paid_at=t.paid_at.isoformat() if t.paid_at else None,
            )
            for t in s.transfers
        ],
    )


def lock_settlement(db: Session, group_id: int, settlement_id: int) -> Settlement:
    settlement = db.scalar(
        select(Settlement).where(Settlement.id == settlement_id, Settlement.group_id == group_id)
        .with_for_update()
    )
    if settlement is None:
        raise HTTPException(404, "找不到這次結算")
    return settlement


@app.post(
    "/groups/{group_id}/settlements/{settlement_id}/transfers/{transfer_id}/paid",
    response_model=SettlementOut,
)
def confirm_paid(
    group_id: int,
    settlement_id: int,
    transfer_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """收款人確認收到這筆轉帳。只有收款人能按，避免付款人自己說付了就算數。"""
    me = require_member(group_id, user, db)
    settlement = lock_settlement(db, group_id, settlement_id)
    t = db.get(SettlementTransfer, transfer_id)
    if t is None or t.settlement_id != settlement_id:
        raise HTTPException(404, "找不到這筆轉帳")
    if t.to_member_id != me.id:
        raise HTTPException(403, "只有收款人能確認收到")
    if t.paid_at is not None:
        raise HTTPException(409, "這筆已經確認過了")
    t.paid_at = now()
    db.commit()
    return to_settlement_out(settlement)


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
    me = require_member(group_id, user, db)
    settlement = lock_settlement(db, group_id, settlement_id)
    if settlement.initiated_by_member_id != me.id:
        require_admin(get_group(group_id, db), user)
    if any(t.paid_at for t in settlement.transfers):
        raise HTTPException(409, "已經有人確認收款，不能復原這次結算")
    for e in settlement.expenses:
        e.settlement_id = None
    db.delete(settlement)
    db.commit()
