from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.auth.models import UserGroupEnum, User, UserGroup
from src.core.database import get_db
from src.auth.dependencies import require_role, get_current_active_user
from src.auth.schemas import AdminChangeGroupSchema, UserWithGroupSchema

router = APIRouter(dependencies=[Depends(require_role(UserGroupEnum.ADMIN))])


@router.patch(
    "/users/{user_id}/group",
    summary="Update user group",
    response_model=UserWithGroupSchema,
)
async def update_user_group(
        user_id: int,
        data: AdminChangeGroupSchema,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot change itself group")

    user = (await db.execute(select(User).where(User.id == user_id).options(joinedload(User.group)))).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db_new_group = (await db.execute(select(UserGroup).where(UserGroup.name == data.new_group_rank.name))).scalar_one_or_none()

    if not db_new_group:
        raise HTTPException(status_code=404, detail="Group does not exist in db table")

    try:
        user.group = db_new_group
        await db.commit()
        return UserWithGroupSchema.model_validate(user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during changing user group.",
        ) from e
