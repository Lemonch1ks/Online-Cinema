from functools import lru_cache

from src.notifications.queue import QueuedEmailSender


@lru_cache
def get_email_sender() -> QueuedEmailSender:
    return QueuedEmailSender()
