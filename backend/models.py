"""資料表定義。金額欄位一律為整數（台幣元）。"""

import os
from datetime import date, datetime, timezone

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, create_engine, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import ARRAY


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    memberships: Mapped[list["Member"]] = relationship(back_populates="user")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # 管理員 = 建立者。用 user_id 而非 member_id，避免 group 與 member 互相依賴。
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    members: Mapped[list["Member"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Member(Base):
    """一個 User 在一個 Group 內的身分。

    status:
      active      — 正常
      deactivated — 搬走了，不可選入新支出，但既有欠款照算
      removed     — 被管理員移出，不再看得到此群組；歷史紀錄保留
    """

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_member_group_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    group: Mapped["Group"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Invite(Base):
    """邀請連結。7 天內可重複使用，不限一次一人。"""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Settlement(Base):
    """一次結算：把數筆未結支出一起算清的紀錄。"""

    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    initiated_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    transfers: Mapped[list["SettlementTransfer"]] = relationship(
        back_populates="settlement", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(back_populates="settlement")


class SettlementTransfer(Base):
    """結算算出的「誰付誰多少」。刻意存下來凍結結果，日後改分帳規則也不影響舊紀錄。"""

    __tablename__ = "settlement_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    settlement_id: Mapped[int] = mapped_column(
        ForeignKey("settlements.id", ondelete="CASCADE"), index=True
    )
    from_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    to_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    amount: Mapped[int] = mapped_column(Integer)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 結算只算出「該付」；收款人確認收到才算真的付了
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    settlement: Mapped["Settlement"] = relationship(back_populates="transfers")


class Expense(Base):
    """一筆共同支出。settlement_id 有值即為已結，鎖定不可改。"""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    payer_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    spent_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    settlement_id: Mapped[int | None] = mapped_column(
        ForeignKey("settlements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    shares: Mapped[list["ExpenseShare"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", lazy="selectin"
    )
    settlement: Mapped["Settlement | None"] = relationship(back_populates="expenses")

    @property
    def is_settled(self) -> bool:
        return self.settlement_id is not None


class ExpenseShare(Base):
    """某位成員在某筆支出中應負擔的金額。所有 share 加總 = expense.amount。"""

    __tablename__ = "expense_shares"
    __table_args__ = (UniqueConstraint("expense_id", "member_id", name="uq_share_expense_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)

    expense: Mapped["Expense"] = relationship(back_populates="shares")


class Notification(Base):
    """站內通知。summary 存下當時的文字快照，來源被刪掉也還讀得懂。"""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "uq_notification_due_reminder",
            "recipient_member_id", "expense_id", "reminder_due_on", unique=True,
        ),
        Index("uq_notification_transfer_reminder", "transfer_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    recipient_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    actor_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    event_type: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(Text)
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True
    )
    settlement_id: Mapped[int | None] = mapped_column(
        ForeignKey("settlements.id", ondelete="CASCADE"), nullable=True
    )
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("settlement_transfers.id", ondelete="CASCADE"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(default=False)
    reminder_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Availability(Base):
    __tablename__ = "availabilities"
    __table_args__ = (CheckConstraint("starts_at < ends_at", name="availability_time_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GarbageSchedule(Base):
    __tablename__ = "garbage_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String(200))


class Chore(Base):
    __tablename__ = "chores"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    assigned_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    garbage_schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("garbage_schedules.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotation_member_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)


# 本機預設連 docker-compose 的 PostgreSQL；部署時用環境變數指到雲端資料庫
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/housemate")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def init_db() -> None:
    with engine.begin() as conn:
        # Serialize startup schema upgrades when multiple workers start together.
        conn.execute(text("SELECT pg_advisory_xact_lock(36417301)"))
        Base.metadata.create_all(conn)
        conn.execute(text("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS due_on DATE"))
        conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS reminder_due_on DATE"))
        if "due_on" not in {column["name"] for column in inspect(conn).get_columns("settlement_transfers")}:
            conn.execute(text("ALTER TABLE settlement_transfers ADD COLUMN due_on DATE"))
            conn.execute(text("""
                UPDATE settlement_transfers AS transfer
                SET due_on = (
                    SELECT MIN(expense.due_on)
                    FROM expenses AS expense
                    JOIN expense_shares AS share ON share.expense_id = expense.id
                    WHERE expense.settlement_id = transfer.settlement_id
                      AND expense.payer_member_id = transfer.to_member_id
                      AND share.member_id = transfer.from_member_id
                      AND share.amount > 0
                )
            """))
        conn.execute(text("""
            ALTER TABLE notifications ADD COLUMN IF NOT EXISTS transfer_id INTEGER
                REFERENCES settlement_transfers (id) ON DELETE CASCADE
        """))
        conn.execute(text("ALTER TABLE chores ADD COLUMN IF NOT EXISTS rotation_member_ids INTEGER[]"))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_due_reminder
            ON notifications (recipient_member_id, expense_id, reminder_due_on)
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_transfer_reminder
            ON notifications (transfer_id)
        """))


if __name__ == "__main__":
    init_db()
