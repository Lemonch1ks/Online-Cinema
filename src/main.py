from fastapi import FastAPI

from src.auth.routers import router as auth_router
from src.cart.routers import router as cart_router
from src.core.config import settings
from src.core.docs import router as docs_router
from src.movies.routers import router as movies_router
from src.orders.routers import router as orders_router

app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(auth_router)
app.include_router(movies_router)
app.include_router(cart_router, prefix=settings.API_VERSION_PREFIX, tags=["cart"])
app.include_router(orders_router, prefix=settings.API_VERSION_PREFIX, tags=["orders"])
app.include_router(docs_router)
