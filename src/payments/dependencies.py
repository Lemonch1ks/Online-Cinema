from functools import lru_cache

from src.core.config import settings
from src.payments.gateway import StripeGateway


@lru_cache
def get_payment_gateway() -> StripeGateway:
    return StripeGateway(
        secret_key=settings.STRIPE_SECRET_KEY,
        success_url=settings.STRIPE_SUCCESS_URL,
        cancel_url=settings.STRIPE_CANCEL_URL,
    )
