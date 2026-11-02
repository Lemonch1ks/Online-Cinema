"""Unit tests for the real EmailSender: real Jinja templates, fake SMTP connection."""
from email import message_from_string

import aiosmtplib
import pytest

from src.core.config import settings
from src.notifications.emails import BaseEmailError, EmailSender

SENDER = "noreply@cinema.test"
RECIPIENT = "user@example.com"
LINK = "http://test/some/link/abc123"


class FakeSMTP:
    """Mimics aiosmtplib.SMTP: start_tls=True in the constructor already upgrades the connection on connect()."""

    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, hostname: str, port: int, start_tls: bool | None = None) -> None:
        self.hostname = hostname
        self.port = port
        self.start_tls_on_connect = start_tls
        self.using_tls = False
        self.calls: list[str] = []
        self.sent: list[tuple[str, list[str], str]] = []
        self.closed = False
        FakeSMTP.instances.append(self)

    async def __aenter__(self) -> "FakeSMTP":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if not isinstance(exc, (ConnectionError, TimeoutError)):
            await self.quit()
        self.close()

    def _maybe_fail(self, step: str) -> None:
        if FakeSMTP.fail_on == step:
            raise aiosmtplib.SMTPException(f"{step} failed")

    async def connect(self) -> None:
        self.calls.append("connect")
        self._maybe_fail("connect")
        if self.start_tls_on_connect:
            await self.starttls()

    async def starttls(self) -> None:
        self.calls.append("starttls")
        if self.using_tls:
            raise aiosmtplib.SMTPException("Connection already using TLS")
        self.using_tls = True

    async def login(self, username: str, password: str) -> None:
        self.calls.append("login")
        self._maybe_fail("login")

    async def sendmail(self, sender: str, recipients: list[str], message: str) -> None:
        self.calls.append("sendmail")
        self._maybe_fail("sendmail")
        self.sent.append((sender, recipients, message))

    async def quit(self) -> None:
        self.calls.append("quit")
        self.closed = True

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_on = None
    monkeypatch.setattr(aiosmtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def make_sender(password: str = "secret", use_tls: bool = False) -> EmailSender:
    return EmailSender(
        hostname="smtp.test",
        port=1025,
        email=SENDER,
        password=password,
        use_tls=use_tls,
        template_dir=str(settings.TEMPLATE_DIR),
        activation_email_template_name=settings.ACTIVATION_REQUEST_TEMPLATE_NAME,
        activation_complete_email_template_name=settings.ACTIVATION_COMPLETE_TEMPLATE_NAME,
        password_email_template_name=settings.PASSWORD_RESET_REQUEST_TEMPLATE_NAME,
        password_complete_email_template_name=settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
        activation_email_subject=settings.ACTIVATION_REQUEST_SUBJECT,
        activation_complete_email_subject=settings.ACTIVATION_COMPLETE_SUBJECT,
        password_email_subject=settings.PASSWORD_RESET_REQUEST_SUBJECT,
        password_complete_email_subject=settings.PASSWORD_RESET_COMPLETE_SUBJECT,
    )


def sent_message():
    [smtp] = FakeSMTP.instances
    [(sender, recipients, raw)] = smtp.sent
    message = message_from_string(raw)
    html = message.get_payload()[0].get_payload(decode=True).decode()
    return sender, recipients, message, html


@pytest.mark.parametrize(
    ("method", "subject", "title"),
    [
        ("send_activation_email", settings.ACTIVATION_REQUEST_SUBJECT, "Registration"),
        ("send_activation_complete_email", settings.ACTIVATION_COMPLETE_SUBJECT, "Account Activated"),
        ("send_password_reset_email", settings.PASSWORD_RESET_REQUEST_SUBJECT, "Password Reset Request"),
        ("send_password_reset_complete_email", settings.PASSWORD_RESET_COMPLETE_SUBJECT, "Password Successfully Reset"),
    ],
)
async def test_email_is_rendered_and_sent(method, subject, title):
    await getattr(make_sender(), method)(RECIPIENT, LINK)

    sender, recipients, message, html = sent_message()
    assert sender == SENDER
    assert recipients == [RECIPIENT]
    assert message["From"] == SENDER
    assert message["To"] == RECIPIENT
    assert message["Subject"] == subject
    assert message.get_payload()[0].get_content_type() == "text/html"
    assert LINK in html
    assert RECIPIENT in html
    assert f"<title>{title}</title>" in html


async def test_smtp_session_without_tls(fake_smtp):
    await make_sender(use_tls=False).send_activation_email(RECIPIENT, LINK)

    [smtp] = FakeSMTP.instances
    assert (smtp.hostname, smtp.port) == ("smtp.test", 1025)
    assert smtp.calls[:3] == ["connect", "login", "sendmail"]
    assert "starttls" not in smtp.calls
    assert smtp.closed


async def test_no_login_without_password():
    await make_sender(password="").send_activation_email(RECIPIENT, LINK)

    [smtp] = FakeSMTP.instances
    assert "login" not in smtp.calls
    assert smtp.sent


async def test_tls_connection_upgrades_once():
    await make_sender(use_tls=True).send_activation_email(RECIPIENT, LINK)

    [smtp] = FakeSMTP.instances
    assert smtp.calls.count("starttls") == 1
    assert smtp.sent


@pytest.mark.parametrize("step", ["connect", "login", "sendmail"])
async def test_smtp_error_is_wrapped_in_base_email_error(fake_smtp, step):
    fake_smtp.fail_on = step

    with pytest.raises(BaseEmailError, match=RECIPIENT):
        await make_sender().send_activation_email(RECIPIENT, LINK)

    [smtp] = FakeSMTP.instances
    assert "sendmail" not in smtp.calls[smtp.calls.index(step) + 1:]
    if step != "connect":
        assert smtp.closed, "the connection must be closed after a failed login/sendmail"
