import aiosmtplib
import pytest
from kombu.exceptions import OperationalError

from src.core.config import settings
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
    "send_comment_reply_email": "comment_reply",
    "send_comment_like_email": "comment_like",
    "send_payment_success_email": "payment_success",
    "send_payment_failed_email": "payment_failed",
    "send_refund_email": "refund",
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
    assert (sender._hostname, sender._port, sender._email, sender._password, sender._use_tls) == (
        settings.EMAIL_HOSTNAME,
        settings.EMAIL_PORT,
        settings.EMAIL_USERNAME,
        settings.EMAIL_PASSWORD,
        settings.EMAIL_USE_TLS,
    )
    assert (
        sender._activation_email_template_name,
        sender._activation_complete_email_template_name,
        sender._password_email_template_name,
        sender._password_complete_email_template_name,
        sender._comment_reply_email_template_name,
        sender._comment_like_email_template_name,
        sender._payment_success_email_template_name,
        sender._payment_failed_email_template_name,
        sender._refund_email_template_name,
    ) == (
        settings.ACTIVATION_REQUEST_TEMPLATE_NAME,
        settings.ACTIVATION_COMPLETE_TEMPLATE_NAME,
        settings.PASSWORD_RESET_REQUEST_TEMPLATE_NAME,
        settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
        settings.COMMENT_REPLY_TEMPLATE_NAME,
        settings.COMMENT_LIKE_TEMPLATE_NAME,
        settings.PAYMENT_SUCCESS_TEMPLATE_NAME,
        settings.PAYMENT_FAILED_TEMPLATE_NAME,
        settings.REFUND_TEMPLATE_NAME,
    )
    assert (
        sender._activation_email_subject,
        sender._activation_complete_email_subject,
        sender._password_email_subject,
        sender._password_complete_email_subject,
        sender._comment_reply_email_subject,
        sender._comment_like_email_subject,
        sender._payment_success_email_subject,
        sender._payment_failed_email_subject,
        sender._refund_email_subject,
    ) == (
        settings.ACTIVATION_REQUEST_SUBJECT,
        settings.ACTIVATION_COMPLETE_SUBJECT,
        settings.PASSWORD_RESET_REQUEST_SUBJECT,
        settings.PASSWORD_RESET_COMPLETE_SUBJECT,
        settings.COMMENT_REPLY_SUBJECT,
        settings.COMMENT_LIKE_SUBJECT,
        settings.PAYMENT_SUCCESS_SUBJECT,
        settings.PAYMENT_FAILED_SUBJECT,
        settings.REFUND_SUBJECT,
    )
    assert email_tasks.get_smtp_sender() is sender


def test_smtp_sender_follows_non_default_settings(monkeypatch):
    for name, value in {
        "EMAIL_HOSTNAME": "smtp.real.example",
        "EMAIL_PORT": 2525,
        "EMAIL_USE_TLS": True,
        "EMAIL_PASSWORD": "app-password",
    }.items():
        monkeypatch.setattr(settings, name, value)
    email_tasks.get_smtp_sender.cache_clear()
    try:
        sender = email_tasks.get_smtp_sender()

        assert (sender._hostname, sender._port, sender._use_tls, sender._password) == (
            "smtp.real.example",
            2525,
            True,
            "app-password",
        )
    finally:
        email_tasks.get_smtp_sender.cache_clear()
