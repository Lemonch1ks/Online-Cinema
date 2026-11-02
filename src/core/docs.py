from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from src.auth.dependencies import verify_docs_access
from src.core.config import settings

OPENAPI_URL = f"{settings.API_VERSION_PREFIX}{settings.OPENAPI_URL}"

router = APIRouter(
    prefix=settings.API_VERSION_PREFIX,
    include_in_schema=False,
    dependencies=[Depends(verify_docs_access)],
)


@router.get(settings.OPENAPI_URL)
async def openapi_schema(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())


@router.get(settings.DOCS_URL)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url=OPENAPI_URL, title=f"{settings.APP_TITLE} - Swagger UI")


@router.get(settings.REDOC_URL)
async def redoc() -> HTMLResponse:
    return get_redoc_html(openapi_url=OPENAPI_URL, title=f"{settings.APP_TITLE} - ReDoc")
