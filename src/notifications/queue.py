from starlette.concurrency import run_in_threadpool

from src.notifications.emails import BaseEmailError
from src.notifications.tasks import send_email


class QueuedEmailSender:
    """Same interface as EmailSender, but only puts the email into the Celery queue.

    The request does not wait for SMTP, so the response time does not depend on whether an email is sent.
    """

    async def _enqueue(self, kind: str, email: str, link: str) -> None:
        try:
            await run_in_threadpool(send_email.delay, kind, email, link)
        except Exception as error:
            raise BaseEmailError(f"Failed to queue the {kind} email to {email}: {error}") from error

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        await self._enqueue("activation", email, activation_link)

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        await self._enqueue("activation_complete", email, login_link)

    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        await self._enqueue("password_reset", email, reset_link)

    async def send_password_reset_complete_email(self, email: str, login_link: str) -> None:
        await self._enqueue("password_reset_complete", email, login_link)

    async def send_comment_reply_email(self, email: str, comment_link: str) -> None:
        await self._enqueue("comment_reply", email, comment_link)

    async def send_comment_like_email(self, email: str, comment_link: str) -> None:
        await self._enqueue("comment_like", email, comment_link)
