"""Runtime community language packs, with admin-only installation."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import JsonValue
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.src.dependencies import (
    get_admin_session_store,
    get_party_manager,
    is_admin_authenticated,
)
from backend.src.language_packs import MAX_UPLOAD_BYTES, LanguagePackError, LanguagePackStore
from backend.src.rate_limit import RATE_LIMIT_RESPONSES
from backend.src.schemas import APIResponseModel, HTTPErrorResponse


class LanguagePackSummary(APIResponseModel):
    locale: str
    name: str
    author: str
    version: str
    revision: str


class LanguagePackList(APIResponseModel):
    languages: list[LanguagePackSummary]


class LanguagePackMessages(APIResponseModel):
    locale: str
    revision: str
    messages: dict[str, JsonValue]


class LanguagePackErrorResponse(APIResponseModel):
    detail: str
    code: Literal["invalid_language_pack", "language_pack_write_failed", "language_pack_not_found"]


class LanguagePackDeleteResponse(APIResponseModel):
    success: Literal[True]


_ERRORS: dict = {
    400: {"model": LanguagePackErrorResponse, "description": "Invalid language pack or locale"},
    404: {"model": LanguagePackErrorResponse, "description": "Language pack not found"},
}
_WRITE_ERROR: dict = {
    500: {
        "model": LanguagePackErrorResponse,
        "description": "Could not persist the requested language pack change",
    }
}
router = APIRouter(prefix="/api/languages", tags=["languages"], responses=RATE_LIMIT_RESPONSES)
admin_router = APIRouter(
    prefix="/api/admin/languages",
    tags=["admin"],
    responses={
        **RATE_LIMIT_RESPONSES,
        401: {"model": HTTPErrorResponse, "description": "Administrator authentication required"},
    },
)


def _store(request: Request) -> LanguagePackStore:
    return request.app.state.language_packs


def _require_admin(
    request: Request,
    parties=Depends(get_party_manager),
    sessions=Depends(get_admin_session_store),
) -> None:
    if not is_admin_authenticated(request, parties, sessions):
        raise HTTPException(status_code=401, detail="Not authenticated")


def _error(detail: str, code: str = "invalid_language_pack", status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"detail": detail, "code": code}, status_code=status, headers={"Cache-Control": "no-store"}
    )


@router.get("", response_model=LanguagePackList)
def list_languages(request: Request, response: Response):
    """List installed community packs; built-in English and German ship in the client."""
    response.headers["Cache-Control"] = "no-store"
    return {"languages": [pack.summary() for pack in _store(request).list()]}


@router.get("/{locale}", response_model=LanguagePackMessages, responses=_ERRORS)
def language_messages(locale: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        pack = _store(request).get(locale)
    except LanguagePackError as error:
        return _error(error.detail)
    if pack is None:
        return _error("Language pack not found.", "language_pack_not_found", 404)
    return pack.payload()


async def _uploaded_zip(request: Request) -> bytes:
    # Authenticate before parsing multipart. Bound the complete body too: the
    # multipart parser's per-part limit does not bound uploaded file spooling.
    limit = MAX_UPLOAD_BYTES + 64 * 1024
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise LanguagePackError("ZIP files must be no larger than 1 MiB.")
        chunks.append(chunk)
    body = b"".join(chunks)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    bounded = Request(request.scope, receive=receive)
    async with bounded.form(max_files=1, max_fields=0, max_part_size=limit) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile) or len(form) != 1:
            raise LanguagePackError("Upload one ZIP file in the file field.")
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise LanguagePackError("ZIP files must be no larger than 1 MiB.")
    return raw


@admin_router.post(
    "",
    response_model=LanguagePackSummary,
    responses={400: _ERRORS[400], **_WRITE_ERROR},
    dependencies=[Depends(_require_admin)],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_language(request: Request):
    """Install or replace a validated ZIP, up to 1 MiB, without rebuilding the UI."""
    try:
        raw = await _uploaded_zip(request)
        pack = await run_in_threadpool(_store(request).install, raw)
    except LanguagePackError as error:
        return _error(error.detail)
    except StarletteHTTPException:
        return _error("Could not read the uploaded language pack.")
    except OSError:
        return _error(
            "Could not save the language pack. Check data directory permissions.",
            "language_pack_write_failed",
            500,
        )
    return pack.summary()


@admin_router.get(
    "/template",
    dependencies=[Depends(_require_admin)],
    response_class=Response,
    responses={
        200: {
            "description": "Current English namespace files and an editable format-1 manifest",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def language_template(request: Request):
    return Response(
        _store(request).template(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="watchparty-language-template.zip"',
            "Cache-Control": "no-store",
        },
    )


@admin_router.delete(
    "/{locale}",
    response_model=LanguagePackDeleteResponse,
    responses={**_ERRORS, **_WRITE_ERROR},
    dependencies=[Depends(_require_admin)],
)
def delete_language(locale: str, request: Request):
    try:
        deleted = _store(request).delete(locale)
    except LanguagePackError as error:
        return _error(error.detail)
    except OSError:
        return _error(
            "Could not remove the language pack. Check data directory permissions.",
            "language_pack_write_failed",
            500,
        )
    if not deleted:
        return _error("Language pack not found.", "language_pack_not_found", 404)
    return {"success": True}
