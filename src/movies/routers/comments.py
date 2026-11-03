import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user
from src.auth.models import User, UserGroupEnum
from src.core.database import get_db
from src.movies.filters import BasePagination
from src.movies.models import Comment, CommentLike
from src.movies.schemas import (
    CommentInSchema,
    CommentListResponseSchema,
    CommentSchema,
    CommentWithRepliesSchema,
)
from src.movies.service import comment_link, ensure_movie_exists
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import BaseEmailError, EmailSender

logger = logging.getLogger(__name__)

router = APIRouter()

MOVIE_NOT_FOUND_RESPONSE = {
    "description": "Movie with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No movies with id:1 found."}}},
}
COMMENT_NOT_FOUND_RESPONSE = {
    "description": "Comment with the given ID was not found.",
    "content": {"application/json": {"example": {"detail": "No comment with id:1 found."}}},
}


def to_schema(comment: Comment, likes: dict[int, int]) -> CommentSchema:
    return CommentSchema(
        id=comment.id,
        movie_id=comment.movie_id,
        author_id=comment.user_id,
        parent_id=comment.parent_id,
        text=comment.text,
        created_at=comment.created_at,
        likes_count=likes.get(comment.id, 0),
    )


async def get_comment_or_404(db: AsyncSession, comment_id: int) -> Comment:
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No comment with id:{comment_id} found.")
    return comment


async def notify_author(
    db: AsyncSession, email_sender: EmailSender, comment: Comment, actor: User, kind: str, link: str
) -> None:
    """Emails the comment's author about a reply or a like; nobody is notified about their own actions."""
    if comment.user_id == actor.id:
        return
    email = (await db.execute(select(User.email).where(User.id == comment.user_id))).scalar_one()
    send = email_sender.send_comment_reply_email if kind == "reply" else email_sender.send_comment_like_email
    try:
        await send(email, link)
    except BaseEmailError:
        logger.exception("Failed to send the comment %s email to %s", kind, email)


@router.get(
    "/movies/{movie_id}/comments",
    response_model=CommentListResponseSchema,
    summary="Get Movie Comments",
    description="Top-level comments, newest first, each with its replies (oldest first) and the number of likes.",
    responses={404: MOVIE_NOT_FOUND_RESPONSE},
)
async def get_comments(
    movie_id: int,
    request: Request,
    pagination: Annotated[BasePagination, Query()],
    db: AsyncSession = Depends(get_db),
) -> CommentListResponseSchema:
    await ensure_movie_exists(db, movie_id)
    page, per_page = pagination.page, pagination.per_page
    top_level = (Comment.movie_id == movie_id, Comment.parent_id.is_(None))

    total_items = (await db.execute(select(func.count()).select_from(Comment).where(*top_level))).scalar_one()
    total_pages = (total_items + per_page - 1) // per_page

    stmt = select(Comment).where(*top_level).order_by(Comment.id.desc()).offset((page - 1) * per_page).limit(per_page)
    comments = list(await db.scalars(stmt))
    ids = [comment.id for comment in comments]

    replies: list[Comment] = []
    likes: dict[int, int] = {}
    if ids:
        replies = list(await db.scalars(select(Comment).where(Comment.parent_id.in_(ids)).order_by(Comment.id)))
        all_ids = ids + [reply.id for reply in replies]
        likes_stmt = (
            select(CommentLike.comment_id, func.count())
            .where(CommentLike.comment_id.in_(all_ids))
            .group_by(CommentLike.comment_id)
        )
        likes = {comment_id: count for comment_id, count in await db.execute(likes_stmt)}

    def page_link(page_number: int) -> str:
        url = request.url.include_query_params(page=page_number, per_page=per_page)
        return f"{url.path}?{url.query}"

    return CommentListResponseSchema(
        comments=[
            CommentWithRepliesSchema(
                **to_schema(comment, likes).model_dump(),
                replies=[to_schema(reply, likes) for reply in replies if reply.parent_id == comment.id],
            )
            for comment in comments
        ],
        prev_page=page_link(page - 1) if page > 1 else None,
        next_page=page_link(page + 1) if page < total_pages else None,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/movies/{movie_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentSchema,
    summary="Add Comment",
    description=(
        "Pass `parent_id` to reply to a top-level comment of the same movie; replies to replies are not allowed. "
        "The author of the parent comment gets an email."
    ),
    responses={
        404: {"description": "The movie or the parent comment of this movie was not found."},
        422: {"description": "Invalid text, or the parent comment is itself a reply."},
    },
)
async def add_comment(
    movie_id: int,
    data: CommentInSchema,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> CommentSchema:
    await ensure_movie_exists(db, movie_id)

    parent = None
    if data.parent_id is not None:
        parent = await db.get(Comment, data.parent_id)
        if parent is None or parent.movie_id != movie_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No comment with id:{data.parent_id} found for this movie.",
            )
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Replies can only be added to top-level comments.",
            )

    comment = Comment(movie_id=movie_id, user_id=user.id, parent_id=data.parent_id, text=data.text)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    if parent is not None:
        await notify_author(db, email_sender, parent, user, "reply", comment_link(movie_id, comment.id))
    return to_schema(comment, {})


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Comment",
    description="The author or a moderator can delete a comment; its replies and likes are deleted too.",
    responses={
        403: {"description": "Only the author or a moderator can delete the comment."},
        404: COMMENT_NOT_FOUND_RESPONSE,
    },
)
async def delete_comment(
    comment_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    comment = await get_comment_or_404(db, comment_id)
    if comment.user_id != user.id and user.group.name < UserGroupEnum.MODERATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own comments.")

    await db.execute(delete(Comment).where(Comment.id == comment_id))
    await db.commit()


@router.put(
    "/comments/{comment_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Like Comment",
    description="The author gets an email when the like is new; repeating the request changes nothing.",
    responses={404: COMMENT_NOT_FOUND_RESPONSE},
)
async def like_comment(
    comment_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> None:
    comment = await get_comment_or_404(db, comment_id)
    stmt = (
        insert(CommentLike)
        .values(user_id=user.id, comment_id=comment_id)
        .on_conflict_do_nothing()
        .returning(CommentLike.comment_id)
    )
    added = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()

    if added is not None:
        await notify_author(db, email_sender, comment, user, "like", comment_link(comment.movie_id, comment_id))


@router.delete(
    "/comments/{comment_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Like from Comment",
    responses={404: COMMENT_NOT_FOUND_RESPONSE},
)
async def unlike_comment(
    comment_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_comment_or_404(db, comment_id)
    await db.execute(delete(CommentLike).where(CommentLike.user_id == user.id, CommentLike.comment_id == comment_id))
    await db.commit()
