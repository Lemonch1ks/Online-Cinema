import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from src.auth.models import ActivationToken, User, UserGroup, UserGroupEnum
from src.tests.utils import (
    ADMIN_USERS_URL,
    bearer,
    create_activation_token,
    create_user_in_group,
    login,
)

ADMIN_EMAIL = "admin@example.com"
TARGET_EMAIL = "target@example.com"


@pytest.fixture()
async def admin_user(db_session) -> User:
    return await create_user_in_group(db_session, ADMIN_EMAIL, UserGroupEnum.ADMIN)


@pytest.fixture()
async def admin_headers(client, admin_user) -> dict:
    tokens = await login(client, ADMIN_EMAIL)
    return bearer(tokens["access_token"])


@pytest.fixture()
async def target_user(db_session) -> User:
    return await create_user_in_group(db_session, TARGET_EMAIL, UserGroupEnum.USER)


@pytest.fixture()
async def inactive_target(db_session) -> User:
    return await create_user_in_group(db_session, TARGET_EMAIL, UserGroupEnum.USER, is_active=False)


async def get_user_with_group(db_session, user_id: int) -> User:
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.group))
        .execution_options(populate_existing=True)
    )
    return (await db_session.execute(stmt)).scalar_one()


def group_url(user_id: int) -> str:
    return f"{ADMIN_USERS_URL}/{user_id}/group"


def activate_url(user_id: int) -> str:
    return f"{ADMIN_USERS_URL}/{user_id}/activate"


# --- access control (router-level require_role(ADMIN)) ---

@pytest.mark.parametrize("group", [UserGroupEnum.USER, UserGroupEnum.MODERATOR])
async def test_non_admin_gets_403(client, db_session, target_user, group):
    await create_user_in_group(db_session, "caller@example.com", group)
    headers = bearer((await login(client, "caller@example.com"))["access_token"])

    group_response = await client.patch(
        group_url(target_user.id), json={"new_group_rank": UserGroupEnum.ADMIN}, headers=headers
    )
    activate_response = await client.post(activate_url(target_user.id), headers=headers)

    assert group_response.status_code == 403
    assert activate_response.status_code == 403
    user = await get_user_with_group(db_session, target_user.id)
    assert user.group.name == UserGroupEnum.USER


async def test_admin_endpoints_without_auth_return_401(client, target_user):
    group_response = await client.patch(group_url(target_user.id), json={"new_group_rank": UserGroupEnum.ADMIN})
    activate_response = await client.post(activate_url(target_user.id))

    assert group_response.status_code == 401
    assert activate_response.status_code == 401


async def test_role_is_read_from_db_not_from_token(client, db_session, target_user, admin_headers):
    # the access token holds only the email, so a promotion applies to an already issued token
    user_headers = bearer((await login(client, TARGET_EMAIL))["access_token"])
    await client.patch(group_url(target_user.id), json={"new_group_rank": UserGroupEnum.ADMIN}, headers=admin_headers)

    response = await client.post(activate_url(target_user.id), headers=user_headers)

    assert response.status_code == 200


# --- PATCH /users/{user_id}/group ---

@pytest.mark.parametrize("new_group", list(UserGroupEnum))
async def test_admin_changes_user_group(client, db_session, target_user, admin_headers, new_group):
    response = await client.patch(
        group_url(target_user.id), json={"new_group_rank": new_group}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": target_user.id,
        "email": TARGET_EMAIL,
        "group_rank": new_group,
        "is_active": True,
    }
    user = await get_user_with_group(db_session, target_user.id)
    assert user.group.name == new_group


async def test_admin_cannot_change_own_group(client, db_session, admin_user, admin_headers):
    response = await client.patch(
        group_url(admin_user.id), json={"new_group_rank": UserGroupEnum.USER}, headers=admin_headers
    )

    assert response.status_code == 403
    user = await get_user_with_group(db_session, admin_user.id)
    assert user.group.name == UserGroupEnum.ADMIN


async def test_change_group_of_unknown_user_returns_404(client, admin_headers):
    response = await client.patch(group_url(9999), json={"new_group_rank": UserGroupEnum.USER}, headers=admin_headers)

    assert response.status_code == 404


async def test_change_group_to_group_missing_in_db_returns_404(client, db_session, target_user, admin_headers):
    await db_session.execute(delete(UserGroup).where(UserGroup.name == UserGroupEnum.MODERATOR))
    await db_session.commit()

    response = await client.patch(
        group_url(target_user.id), json={"new_group_rank": UserGroupEnum.MODERATOR}, headers=admin_headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Group does not exist in db table"


@pytest.mark.parametrize("payload", [{}, {"new_group_rank": 3}, {"new_group_rank": "ADMIN"}])
async def test_change_group_invalid_payload_returns_422(client, target_user, admin_headers, payload):
    response = await client.patch(group_url(target_user.id), json=payload, headers=admin_headers)

    assert response.status_code == 422


# --- POST /users/{user_id}/activate ---

async def test_admin_activates_user_and_removes_token(client, db_session, email_sender, inactive_target, admin_headers):
    await create_activation_token(db_session, inactive_target)

    response = await client.post(activate_url(inactive_target.id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    await db_session.refresh(inactive_target)
    assert inactive_target.is_active is True
    token = (
        await db_session.execute(select(ActivationToken).where(ActivationToken.user_id == inactive_target.id))
    ).scalar_one_or_none()
    assert token is None
    assert [email for email, _ in email_sender.activation_complete_emails] == [TARGET_EMAIL]

    await login(client, TARGET_EMAIL)


async def test_admin_activates_user_without_token(client, db_session, inactive_target, admin_headers):
    response = await client.post(activate_url(inactive_target.id), headers=admin_headers)

    assert response.status_code == 200
    await db_session.refresh(inactive_target)
    assert inactive_target.is_active is True


async def test_activate_already_active_user_sends_no_email(client, email_sender, target_user, admin_headers):
    response = await client.post(activate_url(target_user.id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert email_sender.activation_complete_emails == []


async def test_activate_unknown_user_returns_404(client, admin_headers):
    response = await client.post(activate_url(9999), headers=admin_headers)

    assert response.status_code == 404
