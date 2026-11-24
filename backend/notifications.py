from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import current_user, get_db
from group_access import require_member
from models import Expense, ExpenseShare, Member, Notification, User, now

router = APIRouter(prefix="/groups/{group_id}/notifications")
TAIPEI = ZoneInfo("Asia/Taipei")


class NotificationOut(BaseModel):
    id: int
    event_type: str
    summary: str
    expense_id: int | None
    settlement_id: int | None
    is_read: bool
    created_at: datetime


class InboxOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


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


def create_due_reminders(db: Session, member: Member, today: date) -> None:
    eligible = db.execute(
        select(Expense, ExpenseShare.amount)
        .join(ExpenseShare)
        .where(
            Expense.group_id == member.group_id,
            Expense.settlement_id.is_(None),
            Expense.due_on <= today + timedelta(days=1),
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
            summary=f"「{expense.description}」繳款期限為 {expense.due_on}，你的分攤額為 NT$ {amount}。",
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


def to_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id, event_type=row.event_type, summary=row.summary, expense_id=row.expense_id,
        settlement_id=row.settlement_id, is_read=row.is_read,
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
