from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import Text, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import bearer, current_user, get_db
from group_access import require_member
from inbox_stream import TAIPEI
from models import (
    Expense, ExpenseShare, Member, Notification, SessionLocal, Settlement, SettlementTransfer,
    User, now,
)

router = APIRouter(prefix="/groups/{group_id}/notifications")


class NotificationOut(BaseModel):
    id: int
    event_type: str
    summary: str
    expense_id: int | None
    settlement_id: int | None
    transfer_id: int | None
    is_read: bool
    created_at: datetime


class InboxOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


def signal_inbox(db: Session, group_id: int, member_id: int) -> None:
    """Refresh an inbox when eligibility changes without creating an event notification."""
    payload = func.json_build_array(func.current_schema(), group_id, member_id)
    db.execute(select(func.pg_notify("housemate_inbox", payload.cast(Text))))


def notify(
    db: Session, actor: Member, recipients: set[int], event_type: str, summary: str,
    *, expense_id: int | None = None, settlement_id: int | None = None,
) -> None:
    db.add_all(
        Notification(
            group_id=actor.group_id, recipient_member_id=member_id, actor_member_id=actor.id,
            event_type=event_type, summary=summary, expense_id=expense_id,
            settlement_id=settlement_id,
        )
        for member_id in sorted(recipients - {actor.id})
    )
    if actor.id in recipients:
        signal_inbox(db, actor.group_id, actor.id)


def create_expense_reminders(db: Session, member: Member, cutoff: date) -> None:
    eligible = db.execute(
        select(Expense, ExpenseShare.amount)
        .join(ExpenseShare)
        .where(
            Expense.group_id == member.group_id,
            Expense.settlement_id.is_(None),
            Expense.due_on <= cutoff,
            Expense.payer_member_id != member.id,
            ExpenseShare.member_id == member.id,
            ExpenseShare.amount > 0,
        )
        .order_by(Expense.id)
        .with_for_update(of=Expense)
    ).all()
    if not eligible:
        return
    rows = [
        dict(
            group_id=member.group_id, recipient_member_id=member.id,
            actor_member_id=expense.created_by_member_id, event_type="expense_due",
            summary=f"「{expense.description}」繳款期限為 {expense.due_on}，你的應付分攤額為 NT$ {amount}。",
            expense_id=expense.id, reminder_due_on=expense.due_on, is_read=False,
            created_at=now(),
        )
        for expense, amount in eligible
    ]
    db.execute(
        insert(Notification).values(rows).on_conflict_do_nothing(
            index_elements=["recipient_member_id", "expense_id", "reminder_due_on"]
        )
    )


def create_transfer_reminders(db: Session, member: Member, cutoff: date) -> None:
    eligible = (
        SettlementTransfer.from_member_id == member.id,
        SettlementTransfer.paid_at.is_(None),
        SettlementTransfer.due_on <= cutoff,
    )
    # 收款確認和復原都先鎖結算。取得相同的鎖後，再讀一次待付款狀態。
    has_due_transfer = select(SettlementTransfer.id).where(
        SettlementTransfer.settlement_id == Settlement.id, *eligible,
    ).exists()
    settlement_ids = db.scalars(
        select(Settlement.id)
        .where(Settlement.group_id == member.group_id, has_due_transfer)
        .order_by(Settlement.id)
        .with_for_update()
    ).all()
    if not settlement_ids:
        return
    transfers = db.execute(
        select(SettlementTransfer, User.username)
        .join(Member, Member.id == SettlementTransfer.to_member_id)
        .join(User, User.id == Member.user_id)
        .where(SettlementTransfer.settlement_id.in_(settlement_ids), *eligible)
        .order_by(SettlementTransfer.id)
    ).all()
    if not transfers:
        return
    rows = [
        dict(
            group_id=member.group_id, recipient_member_id=member.id,
            actor_member_id=transfer.to_member_id, event_type="transfer_due",
            summary=f"請於 {transfer.due_on} 前轉帳 NT$ {transfer.amount} 給 {recipient}。",
            settlement_id=transfer.settlement_id, transfer_id=transfer.id,
            reminder_due_on=transfer.due_on, is_read=False, created_at=now(),
        )
        for transfer, recipient in transfers
    ]
    db.execute(insert(Notification).values(rows).on_conflict_do_nothing(index_elements=["transfer_id"]))


def create_due_reminders(db: Session, member: Member, today: date) -> None:
    cutoff = today + timedelta(days=1)
    create_expense_reminders(db, member, cutoff)
    create_transfer_reminders(db, member, cutoff)


def to_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id, event_type=row.event_type, summary=row.summary, expense_id=row.expense_id,
        settlement_id=row.settlement_id, transfer_id=row.transfer_id, is_read=row.is_read,
        created_at=row.created_at.replace(tzinfo=timezone.utc),
    )


@router.get("", response_model=InboxOut)
def inbox(
    group_id: int, response: Response, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    member = require_member(group_id, user, db)
    create_due_reminders(db, member, now().astimezone(TAIPEI).date())
    db.commit()
    rows = db.scalars(
        select(Notification)
        .where(Notification.group_id == group_id, Notification.recipient_member_id == member.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    ).all()
    return InboxOut(items=[to_out(row) for row in rows], unread_count=sum(not row.is_read for row in rows))


@router.get("/events", response_class=StreamingResponse)
def inbox_events(
    group_id: int, request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    # Release the DB session before keeping the HTTP connection open.
    with SessionLocal() as db:
        user = current_user(credentials, db)
        member_id = require_member(group_id, user, db).id
    return StreamingResponse(
        request.app.state.inbox_stream.events(group_id, member_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    group_id: int, notification_id: int, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    member = require_member(group_id, user, db)
    row = db.get(Notification, notification_id)
    if row is None or row.group_id != group_id or row.recipient_member_id != member.id:
        raise HTTPException(404, "找不到通知")
    row.is_read = True
    db.commit()
    return to_out(row)
