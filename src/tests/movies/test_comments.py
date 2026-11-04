"""Comments with one level of replies, comment likes and the emails to the comment's author."""

from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from src.auth.models import UserGroupEnum
from src.core.config import settings
from src.main import app
from src.movies.models import Comment, CommentLike
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import BaseEmailError
from src.tests.movies.conftest import make_member
from src.tests.utils import MOVIES_URL

COMMENTS_URL = f"{settings.API_VERSION_PREFIX}/comments"


def movie_comments_url(movie_id: int) -> str:
    return f"{MOVIES_URL}/{movie_id}/comments"


def like_url(comment_id: int) -> str:
    return f"{COMMENTS_URL}/{comment_id}/like"


def link(movie_id: int, comment_id: int) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/movies/{movie_id}#comment-{comment_id}"


async def post_comment(client, member, movie, text: str, parent_id: int | None = None) -> dict:
    body = {"text": text} if parent_id is None else {"text": text, "parent_id": parent_id}
    response = await client.post(movie_comments_url(movie.id), json=body, headers=member.headers)
    assert response.status_code == 201, response.text
    return response.json()


async def comment_texts(db_session) -> list[str]:
    return list(await db_session.scalars(select(Comment.text).order_by(Comment.id)))


async def like_rows(db_session) -> list[tuple[int, int]]:
    stmt = select(CommentLike.user_id, CommentLike.comment_id).order_by(CommentLike.user_id, CommentLike.comment_id)
    return [tuple(row) for row in await db_session.execute(stmt)]


# --- POST ---


async def test_anonymous_cannot_comment_or_like(client, db_session, catalog, alice):
    comment = await post_comment(client, alice, catalog["The Matrix"], "Great")

    responses = [
        await client.post(movie_comments_url(catalog["The Matrix"].id), json={"text": "Hi"}),
        await client.delete(f"{COMMENTS_URL}/{comment['id']}"),
        await client.put(like_url(comment["id"])),
        await client.delete(like_url(comment["id"])),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]
    assert await comment_texts(db_session) == ["Great"]


async def test_add_comment(client, db_session, catalog, alice, email_sender):
    matrix = catalog["The Matrix"]

    response = await client.post(
        movie_comments_url(matrix.id), json={"text": "  Great movie!  "}, headers=alice.headers
    )

    assert response.status_code == 201
    body = response.json()
    row = await db_session.get(Comment, body["id"])
    assert row is not None
    assert (row.movie_id, row.user_id, row.parent_id, row.text) == (matrix.id, alice.id, None, "Great movie!")
    assert body == {
        "id": row.id,
        "movie_id": matrix.id,
        "author_id": alice.id,
        "parent_id": None,
        "text": "Great movie!",
        "created_at": body["created_at"],
        "likes_count": 0,
    }
    assert datetime.fromisoformat(body["created_at"]) == row.created_at
    assert email_sender.comment_reply_emails == []


async def test_reply_emails_the_author_of_the_parent(client, catalog, alice, bob, email_sender):
    matrix = catalog["The Matrix"]
    parent = await post_comment(client, alice, matrix, "Great")

    reply = await post_comment(client, bob, matrix, "Agree", parent["id"])

    assert reply["parent_id"] == parent["id"]
    assert email_sender.comment_reply_emails == [(alice.email, link(matrix.id, reply["id"]))]
    assert email_sender.comment_like_emails == []


async def test_reply_to_own_comment_sends_no_email(client, catalog, alice, email_sender):
    parent = await post_comment(client, alice, catalog["The Matrix"], "Great")

    await post_comment(client, alice, catalog["The Matrix"], "And one more thing", parent["id"])

    assert email_sender.comment_reply_emails == []


async def test_reply_to_a_reply_returns_422(client, db_session, catalog, alice, bob, email_sender):
    matrix = catalog["The Matrix"]
    parent = await post_comment(client, alice, matrix, "Great")
    reply = await post_comment(client, bob, matrix, "Agree", parent["id"])
    email_sender.comment_reply_emails.clear()

    response = await client.post(
        movie_comments_url(matrix.id), json={"text": "Deeper", "parent_id": reply["id"]}, headers=alice.headers
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Replies can only be added to top-level comments."}
    assert await comment_texts(db_session) == ["Great", "Agree"]
    assert email_sender.comment_reply_emails == []


async def test_reply_to_a_comment_of_another_movie_returns_404(client, db_session, catalog, alice, bob):
    parent = await post_comment(client, alice, catalog["The Matrix"], "Great")

    response = await client.post(
        movie_comments_url(catalog["Inception"].id), json={"text": "Hi", "parent_id": parent["id"]}, headers=bob.headers
    )

    assert response.status_code == 404
    assert response.json() == {"detail": f"No comment with id:{parent['id']} found for this movie."}
    assert await comment_texts(db_session) == ["Great"]


async def test_reply_to_unknown_comment_returns_404(client, db_session, catalog, alice):
    response = await client.post(
        movie_comments_url(catalog["The Matrix"].id), json={"text": "Hi", "parent_id": 999}, headers=alice.headers
    )

    assert response.status_code == 404
    assert await comment_texts(db_session) == []


async def test_comment_on_unknown_movie_returns_404(client, db_session, alice):
    response = await client.post(movie_comments_url(999), json={"text": "Hi"}, headers=alice.headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "No movies with id:999 found."}


@pytest.mark.parametrize(
    "body", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 2001}, {"text": "Hi", "x": 1}, {"text": None}]
)
async def test_invalid_comment_returns_422(client, db_session, catalog, alice, body):
    response = await client.post(movie_comments_url(catalog["The Matrix"].id), json=body, headers=alice.headers)

    assert response.status_code == 422
    assert await comment_texts(db_session) == []


async def test_max_length_comment_is_allowed(client, catalog, alice):
    response = await client.post(
        movie_comments_url(catalog["The Matrix"].id), json={"text": "x" * 2000}, headers=alice.headers
    )

    assert response.status_code == 201


async def test_email_failure_does_not_break_the_reply(client, db_session, catalog, alice, bob):
    class BrokenSender:
        async def send_comment_reply_email(self, email: str, comment_link: str) -> None:
            raise BaseEmailError("broker is down")

    matrix = catalog["The Matrix"]
    parent = await post_comment(client, alice, matrix, "Great")
    app.dependency_overrides[get_email_sender] = BrokenSender

    response = await client.post(
        movie_comments_url(matrix.id), json={"text": "Agree", "parent_id": parent["id"]}, headers=bob.headers
    )

    assert response.status_code == 201
    assert await comment_texts(db_session) == ["Great", "Agree"]


# --- GET ---


async def test_comments_list_newest_first_with_replies_oldest_first(client, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    first = await post_comment(client, alice, matrix, "First")
    second = await post_comment(client, bob, matrix, "Second")
    reply_1 = await post_comment(client, bob, matrix, "Reply 1", first["id"])
    reply_2 = await post_comment(client, alice, matrix, "Reply 2", first["id"])
    await post_comment(client, alice, catalog["Inception"], "Other movie")

    response = await client.get(movie_comments_url(matrix.id))

    assert response.status_code == 200
    body = response.json()
    assert [(comment["id"], [reply["id"] for reply in comment["replies"]]) for comment in body["comments"]] == [
        (second["id"], []),
        (first["id"], [reply_1["id"], reply_2["id"]]),
    ]
    assert body["comments"][1]["replies"][0] == reply_1
    assert (body["total_items"], body["total_pages"], body["prev_page"], body["next_page"]) == (2, 1, None, None)


async def test_comments_list_shows_likes(client, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    comment = await post_comment(client, alice, matrix, "Great")
    reply = await post_comment(client, bob, matrix, "Agree", comment["id"])
    for member in (alice, bob):
        await client.put(like_url(comment["id"]), headers=member.headers)
    await client.put(like_url(reply["id"]), headers=alice.headers)

    body = (await client.get(movie_comments_url(matrix.id))).json()

    [listed] = body["comments"]
    assert listed["likes_count"] == 2
    assert listed["replies"][0]["likes_count"] == 1


async def test_comments_pagination_counts_top_level_only(client, catalog, alice):
    matrix = catalog["The Matrix"]
    created = [await post_comment(client, alice, matrix, f"Comment {i}") for i in range(3)]
    await post_comment(client, alice, matrix, "Reply", created[0]["id"])

    first = (await client.get(movie_comments_url(matrix.id), params={"per_page": 2})).json()
    second = (await client.get(movie_comments_url(matrix.id), params={"per_page": 2, "page": 2})).json()

    assert [comment["text"] for comment in first["comments"]] == ["Comment 2", "Comment 1"]
    assert [comment["text"] for comment in second["comments"]] == ["Comment 0"]
    assert second["comments"][0]["replies"][0]["text"] == "Reply"
    assert (first["total_items"], first["total_pages"]) == (3, 2)
    for page_link, page in ((first["next_page"], "2"), (second["prev_page"], "1")):
        parts = urlsplit(page_link)
        assert parts.path == movie_comments_url(matrix.id)
        assert parse_qs(parts.query) == {"page": [page], "per_page": ["2"]}


async def test_comments_of_movie_without_comments(client, catalog):
    response = await client.get(movie_comments_url(catalog["The Matrix"].id))

    assert response.json() == {"comments": [], "total_items": 0, "total_pages": 0, "prev_page": None, "next_page": None}


async def test_comments_of_unknown_movie_returns_404(client):
    response = await client.get(movie_comments_url(999))

    assert response.status_code == 404


# --- DELETE ---


async def test_author_deletes_comment_with_its_replies_and_likes(client, db_session, catalog, alice, bob):
    matrix = catalog["The Matrix"]
    comment = await post_comment(client, alice, matrix, "Great")
    reply = await post_comment(client, bob, matrix, "Agree", comment["id"])
    other = await post_comment(client, bob, matrix, "Other")
    await client.put(like_url(comment["id"]), headers=bob.headers)
    await client.put(like_url(reply["id"]), headers=alice.headers)
    await client.put(like_url(other["id"]), headers=alice.headers)

    response = await client.delete(f"{COMMENTS_URL}/{comment['id']}", headers=alice.headers)

    assert response.status_code == 204
    assert await comment_texts(db_session) == ["Other"]
    assert await like_rows(db_session) == [(alice.id, other["id"])]


async def test_other_user_cannot_delete_comment(client, db_session, catalog, alice, bob):
    comment = await post_comment(client, alice, catalog["The Matrix"], "Great")

    response = await client.delete(f"{COMMENTS_URL}/{comment['id']}", headers=bob.headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "You can only delete your own comments."}
    assert await comment_texts(db_session) == ["Great"]


@pytest.mark.parametrize("group", [UserGroupEnum.MODERATOR, UserGroupEnum.ADMIN])
async def test_moderator_and_admin_delete_any_comment(client, db_session, catalog, alice, group):
    staff = await make_member(client, db_session, "staff@example.com", group)
    comment = await post_comment(client, alice, catalog["The Matrix"], "Rude")

    response = await client.delete(f"{COMMENTS_URL}/{comment['id']}", headers=staff.headers)

    assert response.status_code == 204
    assert await comment_texts(db_session) == []


async def test_delete_unknown_comment_returns_404(client, alice):
    response = await client.delete(f"{COMMENTS_URL}/999", headers=alice.headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "No comment with id:999 found."}


# --- likes ---


async def test_like_saves_it_and_emails_the_author_once(client, db_session, catalog, alice, bob, email_sender):
    matrix = catalog["The Matrix"]
    comment = await post_comment(client, alice, matrix, "Great")

    first = await client.put(like_url(comment["id"]), headers=bob.headers)
    second = await client.put(like_url(comment["id"]), headers=bob.headers)

    assert (first.status_code, second.status_code) == (204, 204)
    assert await like_rows(db_session) == [(bob.id, comment["id"])]
    assert email_sender.comment_like_emails == [(alice.email, link(matrix.id, comment["id"]))]
    assert email_sender.comment_reply_emails == []


async def test_liking_own_comment_sends_no_email(client, db_session, catalog, alice, email_sender):
    comment = await post_comment(client, alice, catalog["The Matrix"], "Great")

    await client.put(like_url(comment["id"]), headers=alice.headers)

    assert await like_rows(db_session) == [(alice.id, comment["id"])]
    assert email_sender.comment_like_emails == []


async def test_unlike(client, db_session, catalog, alice, bob):
    comment = await post_comment(client, alice, catalog["The Matrix"], "Great")
    await client.put(like_url(comment["id"]), headers=bob.headers)
    await client.put(like_url(comment["id"]), headers=alice.headers)

    response = await client.delete(like_url(comment["id"]), headers=bob.headers)
    again = await client.delete(like_url(comment["id"]), headers=bob.headers)

    assert (response.status_code, again.status_code) == (204, 204)
    assert await like_rows(db_session) == [(alice.id, comment["id"])]


async def test_like_unknown_comment_returns_404(client, alice):
    put = await client.put(like_url(999), headers=alice.headers)
    delete = await client.delete(like_url(999), headers=alice.headers)

    assert (put.status_code, delete.status_code) == (404, 404)


async def test_email_failure_does_not_break_the_like(client, db_session, catalog, alice, bob):
    class BrokenSender:
        async def send_comment_like_email(self, email: str, comment_link: str) -> None:
            raise BaseEmailError("broker is down")

    comment = await post_comment(client, alice, catalog["The Matrix"], "Great")
    app.dependency_overrides[get_email_sender] = BrokenSender

    response = await client.put(like_url(comment["id"]), headers=bob.headers)

    assert response.status_code == 204
    assert await like_rows(db_session) == [(bob.id, comment["id"])]
