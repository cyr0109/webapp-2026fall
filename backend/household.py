from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import current_user, get_db
from group_access import get_group, require_active, require_admin, require_member
from models import Availability, Chore, GarbageSchedule, Member, User, now

router = APIRouter(prefix="/groups/{group_id}")
DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
GroupRow = TypeVar("GroupRow", Availability, GarbageSchedule, Chore)


class AvailabilityIn(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("結束時間須晚於開始時間")
        return self


class AvailabilityOut(AvailabilityIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_id: int


class GarbageScheduleIn(BaseModel):
    arrives_at: AwareDatetime
    location: Label


class GarbageScheduleOut(GarbageScheduleIn):
    id: int
    available_member_ids: list[int]


class ChoreIn(BaseModel):
    title: Label
    scheduled_at: AwareDatetime
    assigned_member_id: int
    garbage_schedule_id: int | None = None


class ChoreOut(ChoreIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_by_member_id: int
    completed_at: AwareDatetime | None


def group_row(
    db: Session, model: type[GroupRow], group_id: int, row_id: int, *, lock: bool = False
) -> GroupRow:
    query = select(model).where(model.id == row_id, model.group_id == group_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "找不到這筆資料")
    return row


def apply_values(row: GroupRow, body: BaseModel) -> None:
    for field, value in body.model_dump().items():
        setattr(row, field, value)


def save(db: Session, row: GroupRow, body: BaseModel) -> GroupRow:
    apply_values(row, body)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23503":
            raise HTTPException(409, "關聯資料已變更，請重新載入後再試") from exc
        raise
    return row


@router.get("/availabilities", response_model=list[AvailabilityOut])
def list_availabilities(group_id: int, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    return db.scalars(
        select(Availability).join(Member)
        .where(Availability.group_id == group_id, Member.status != "removed")
        .order_by(Availability.starts_at, Availability.id)
    ).all()


@router.post("/availabilities", response_model=AvailabilityOut, status_code=201)
def create_availability(group_id: int, body: AvailabilityIn, user: CurrentUser, db: DB):
    me = require_member(group_id, user, db)
    require_active(me)
    return save(db, Availability(group_id=group_id, member_id=me.id), body)


def own_availability(
    group_id: int, row_id: int, user: User, db: Session, *, active: bool = False,
) -> Availability:
    me = require_member(group_id, user, db)
    if active:
        require_active(me)
    row = group_row(db, Availability, group_id, row_id, lock=True)
    if row.member_id != me.id:
        raise HTTPException(403, "只能維護自己的空檔")
    return row


@router.put("/availabilities/{row_id}", response_model=AvailabilityOut)
def update_availability(group_id: int, row_id: int, body: AvailabilityIn, user: CurrentUser, db: DB):
    row = own_availability(group_id, row_id, user, db, active=True)
    return save(db, row, body)


@router.delete("/availabilities/{row_id}", status_code=204)
def delete_availability(group_id: int, row_id: int, user: CurrentUser, db: DB):
    db.delete(own_availability(group_id, row_id, user, db))
    db.commit()


def garbage_results(db: Session, group_id: int, row_id: int | None = None) -> list[GarbageScheduleOut]:
    candidates = (
        select(Availability)
        .join(Member)
        .where(Availability.group_id == group_id, Member.status == "active")
        .subquery()
    )
    query = (
        select(GarbageSchedule, candidates.c.member_id)
        .outerjoin(
            candidates,
            and_(
                candidates.c.starts_at <= GarbageSchedule.arrives_at,
                candidates.c.ends_at > GarbageSchedule.arrives_at,
            ),
        )
        .where(GarbageSchedule.group_id == group_id)
        .order_by(GarbageSchedule.arrives_at, GarbageSchedule.id, candidates.c.member_id)
        .distinct()
    )
    if row_id is not None:
        query = query.where(GarbageSchedule.id == row_id)
    results: dict[int, GarbageScheduleOut] = {}
    for row, member_id in db.execute(query):
        if row.id not in results:
            results[row.id] = GarbageScheduleOut(
                id=row.id, arrives_at=row.arrives_at, location=row.location, available_member_ids=[]
            )
        if member_id is not None:
            results[row.id].available_member_ids.append(member_id)
    return list(results.values())


@router.get("/garbage-schedules", response_model=list[GarbageScheduleOut])
def list_garbage(group_id: int, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    return garbage_results(db, group_id)


@router.post("/garbage-schedules", response_model=GarbageScheduleOut, status_code=201)
def create_garbage(group_id: int, body: GarbageScheduleIn, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    require_admin(get_group(group_id, db), user)
    return save_garbage(db, GarbageSchedule(group_id=group_id), body)


def save_garbage(db: Session, row: GarbageSchedule, body: GarbageScheduleIn) -> GarbageScheduleOut:
    apply_values(row, body)
    db.add(row)
    db.flush()
    result = garbage_results(db, row.group_id, row.id)[0]
    db.commit()
    return result


@router.put("/garbage-schedules/{row_id}", response_model=GarbageScheduleOut)
def update_garbage(group_id: int, row_id: int, body: GarbageScheduleIn, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    require_admin(get_group(group_id, db), user)
    return save_garbage(db, group_row(db, GarbageSchedule, group_id, row_id, lock=True), body)


@router.delete("/garbage-schedules/{row_id}", status_code=204)
def delete_garbage(group_id: int, row_id: int, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    require_admin(get_group(group_id, db), user)
    db.delete(group_row(db, GarbageSchedule, group_id, row_id, lock=True))
    db.commit()


def validate_chore(db: Session, group_id: int, body: ChoreIn) -> None:
    target = db.scalar(
        select(Member).where(Member.id == body.assigned_member_id, Member.group_id == group_id)
        .with_for_update()
    )
    if target is None or target.status != "active":
        raise HTTPException(400, "只能指派給同群組且啟用中的成員")
    if body.garbage_schedule_id is not None:
        group_row(db, GarbageSchedule, group_id, body.garbage_schedule_id)


@router.get("/chores", response_model=list[ChoreOut])
def list_chores(group_id: int, user: CurrentUser, db: DB):
    require_member(group_id, user, db)
    return db.scalars(
        select(Chore).where(Chore.group_id == group_id).order_by(Chore.scheduled_at, Chore.id)
    ).all()


@router.post("/chores", response_model=ChoreOut, status_code=201)
def create_chore(group_id: int, body: ChoreIn, user: CurrentUser, db: DB):
    me = require_member(group_id, user, db)
    require_active(me)
    validate_chore(db, group_id, body)
    return save(db, Chore(group_id=group_id, created_by_member_id=me.id), body)


def manageable_chore(group_id: int, row_id: int, user: User, db: Session) -> Chore:
    me = require_member(group_id, user, db)
    row = group_row(db, Chore, group_id, row_id, lock=True)
    if row.created_by_member_id != me.id:
        require_admin(get_group(group_id, db), user)
    return row


@router.put("/chores/{row_id}", response_model=ChoreOut)
def update_chore(group_id: int, row_id: int, body: ChoreIn, user: CurrentUser, db: DB):
    row = manageable_chore(group_id, row_id, user, db)
    if row.completed_at is not None:
        if body.assigned_member_id != row.assigned_member_id:
            raise HTTPException(409, "已完成的家務不能改派")
        if body.garbage_schedule_id is not None:
            group_row(db, GarbageSchedule, group_id, body.garbage_schedule_id)
    else:
        validate_chore(db, group_id, body)
    return save(db, row, body)


@router.delete("/chores/{row_id}", status_code=204)
def delete_chore(group_id: int, row_id: int, user: CurrentUser, db: DB):
    db.delete(manageable_chore(group_id, row_id, user, db))
    db.commit()


@router.patch("/chores/{row_id}/complete", response_model=ChoreOut)
def complete_chore(group_id: int, row_id: int, user: CurrentUser, db: DB):
    me = require_member(group_id, user, db)
    row = group_row(db, Chore, group_id, row_id, lock=True)
    if row.assigned_member_id != me.id:
        raise HTTPException(403, "只有受指派者可以回報完成")
    if row.completed_at is None:
        row.completed_at = now()
        db.commit()
    return row
