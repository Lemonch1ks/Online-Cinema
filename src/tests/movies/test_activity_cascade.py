"""Favorites, reactions, ratings, comments and comment likes disappear with their movie or their user."""

from sqlalchemy import delete, func, select

from src.auth.models import User
from src.movies.models import Comment, CommentLike, Favorite, MovieRating, MovieReaction
from src.tests.utils import MOVIES_URL, create_user

ACTIVITY = (Favorite, MovieReaction, MovieRating, Comment, CommentLike)


async def counts(db_session) -> dict[str, int]:
    return {
        model.__tablename__: (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
        for model in ACTIVITY
    }


async def add_activity(db_session, user_id: int, movie_id: int, other_user_id: int) -> None:
    """Every kind of activity of `user_id` on the movie, plus a reply and a like of another user."""
    db_session.add_all(
        [
            Favorite(user_id=user_id, movie_id=movie_id),
            MovieReaction(user_id=user_id, movie_id=movie_id, is_like=True),
            MovieRating(user_id=user_id, movie_id=movie_id, score=7),
        ]
    )
    comment = Comment(movie_id=movie_id, user_id=user_id, text="Mine")
    db_session.add(comment)
    await db_session.flush()
    reply = Comment(movie_id=movie_id, user_id=other_user_id, parent_id=comment.id, text="Reply")
    db_session.add(reply)
    await db_session.flush()
    db_session.add_all(
        [
            CommentLike(user_id=other_user_id, comment_id=comment.id),
            CommentLike(user_id=user_id, comment_id=reply.id),
        ]
    )
    await db_session.commit()


async def test_deleting_a_movie_removes_its_activity_only(client, db_session, catalog, moderator_headers):
    first = await create_user(db_session, email="first@example.com")
    second = await create_user(db_session, email="second@example.com")
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await add_activity(db_session, first.id, matrix.id, second.id)
    await add_activity(db_session, second.id, inception.id, first.id)
    before = await counts(db_session)

    response = await client.delete(f"{MOVIES_URL}/{matrix.id}", headers=moderator_headers)

    assert response.status_code == 204, response.text
    assert await counts(db_session) == {table: count // 2 for table, count in before.items()}
    assert set(await db_session.scalars(select(Comment.movie_id))) == {inception.id}
    assert set(await db_session.scalars(select(Favorite.movie_id))) == {inception.id}


async def test_deleting_a_user_removes_their_activity_and_replies_to_their_comments(db_session, catalog):
    leaving = await create_user(db_session, email="leaving@example.com")
    staying = await create_user(db_session, email="staying@example.com")
    matrix, inception = catalog["The Matrix"], catalog["Inception"]
    await add_activity(db_session, leaving.id, matrix.id, staying.id)
    await add_activity(db_session, staying.id, inception.id, leaving.id)

    await db_session.execute(delete(User).where(User.id == leaving.id))
    await db_session.commit()

    assert await counts(db_session) == {
        "favorites": 1,
        "movie_reactions": 1,
        "movie_ratings": 1,
        "comments": 1,
        "comment_likes": 0,
    }
    assert list(await db_session.scalars(select(Comment.text))) == ["Mine"]
    assert set(await db_session.scalars(select(Favorite.user_id))) == {staying.id}
