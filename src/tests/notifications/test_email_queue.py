import aiosmtplib
import pytest
from kombu.exceptions import OperationalError

from src.main import app
from src.notifications import tasks as email_tasks
from src.notifications.dependencies import get_email_sender
from src.notifications.emails import BaseEmailError, EmailSender
from src.notifications.queue import QueuedEmailSender
from src.tests.utils import ACTIVATION_RESEND_URL, TEST_EMAIL, create_user

LINK = "http://test/activate/abc"
METHODS = {
    "send_activation_email": "activation",
    "send_activation_complete_email": "activation_complete",
    "send_password_reset_email": "password_reset",
    "send_password_reset_complete_email": "password_reset_complete",
}


@pytest.fixture()
def queued(monkeypatch) -> list[tuple]:
    sent: list[tuple] = []
    monkeypatch.setattr(email_tasks.send_email, "delay", lambda *args: sent.append(args))
    return sent


@pytest.fixture()
def no_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SMTP must not be used inside the request, only in the Celery worker")

    monkeypatch.setattr(aiosmtplib, "SMTP", forbidden)


# --- QueuedEmailSender ---

@pytest.mark.parametrize(("method", "kind"), METHODS.items())
async def test_queued_sender_only_enqueues(queued, no_smtp, method, kind):
    await getattr(QueuedEmailSender(), method)("user@example.com", LINK)

    assert queued == [(kind, "user@example.com", LINK)]


async def test_queued_sender_wraps_broker_errors(monkeypatch):
    def broker_down(*args):
        raise OperationalError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(email_tasks.send_email, "delay", broker_down)

    with pytest.raises(BaseEmailError) as error:
        await QueuedEmailSender().send_activation_email("user@example.com", LINK)

    assert isinstance(error.value.__cause__, OperationalError)


def test_app_uses_queued_sender():
    assert isinstance(get_email_sender(), QueuedEmailSender)


async def test_resend_enqueues_email_instead_of_sending_it(client, db_session, queued, no_smtp):
    app.dependency_overrides.pop(get_email_sender)
    await create_user(db_session, is_active=False)

    response = await client.post(ACTIVATION_RESEND_URL, json={"email": TEST_EMAIL})

    assert response.status_code == 200
    [(kind, recipient, link)] = queued
    assert (kind, recipient) == ("activation", TEST_EMAIL)
    assert "/accounts/activate/" in link


# --- send_email task (runs in the worker) ---

class RecordingSender:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str]] = []

    def __getattr__(self, method: str):
        async def send(email: str, link: str) -> None:
            self.calls.append((method, email, link))
            if self.fail:
                raise BaseEmailError("smtp is down")

        return send


@pytest.mark.parametrize(("method", "kind"), METHODS.items())
def test_task_sends_through_smtp_sender(monkeypatch, method, kind):
    sender = RecordingSender()
    monkeypatch.setattr(email_tasks, "get_smtp_sender", lambda: sender)

    email_tasks.send_email(kind, "user@example.com", LINK)

    assert sender.calls == [(method, "user@example.com", LINK)]


def test_task_rejects_unknown_kind(monkeypatch):
    monkeypatch.setattr(email_tasks, "get_smtp_sender", RecordingSender)

    with pytest.raises(ValueError, match="newsletter"):
        email_tasks.send_email("newsletter", "user@example.com", LINK)


def test_task_is_retried_three_times_when_smtp_fails(monkeypatch):
    sender = RecordingSender(fail=True)
    monkeypatch.setattr(email_tasks, "get_smtp_sender", lambda: sender)

    result = email_tasks.send_email.apply(args=("activation", "user@example.com", LINK))

    assert len(sender.calls) == 1 + 3
    assert result.state == "FAILURE"
    assert isinstance(result.result, BaseEmailError)


def test_task_is_registered_in_celery_app():
    from src.tasks import app as celery_app

    celery_app.loader.import_default_modules()
    assert "src.notifications.tasks.send_email" in celery_app.tasks


def test_smtp_sender_is_built_from_settings_and_cached():
    sender = email_tasks.get_smtp_sender()

    assert isinstance(sender, EmailSender)
    assert email_tasks.get_smtp_sender() is sender
