from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Group, Member, User


def require_member(group_id: int, user: User, db: Session) -> Member:
    member = db.scalar(
        select(Member).where(
            Member.group_id == group_id, Member.user_id == user.id, Member.status != "removed"
        )
    )
    if member is None:
        raise HTTPException(404, "找不到群組，或你不是這個群組的成員")
    return member


def get_group(group_id: int, db: Session) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "找不到群組")
    return group


def require_admin(group: Group, user: User) -> None:
    if group.created_by_user_id != user.id:
        raise HTTPException(403, "只有管理員可以做這件事")


def require_active(member: Member) -> None:
    if member.status != "active":
        raise HTTPException(403, "只有啟用中的成員可以做這件事")
