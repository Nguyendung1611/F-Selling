"""Request-scoped language selection and backend message translation."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import Headers, MutableHeaders

from .translations_en import EN_MESSAGES

DEFAULT_LOCALE = "vi"
SUPPORTED_LOCALES = frozenset({"vi", "en"})
_current_locale: ContextVar[str] = ContextVar(
    "fselling_current_locale", default=DEFAULT_LOCALE
)


def normalize_locale(value: str | None) -> str | None:
    """Return a supported base language from a BCP-47-like value."""
    if not value:
        return None
    base = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LOCALES else None


def negotiate_locale(accept_language: str | None) -> str:
    """Pick vi/en from Accept-Language, respecting q weights."""
    if not accept_language:
        return DEFAULT_LOCALE

    candidates: list[tuple[float, int, str]] = []
    for order, raw_part in enumerate(accept_language.split(",")):
        segments = [segment.strip() for segment in raw_part.split(";")]
        locale = normalize_locale(segments[0])
        if not locale:
            continue
        quality = 1.0
        for segment in segments[1:]:
            if not segment.lower().startswith("q="):
                continue
            try:
                quality = float(segment[2:])
            except ValueError:
                quality = 0.0
        if quality > 0:
            candidates.append((quality, -order, locale))

    return max(candidates, default=(0.0, 0, DEFAULT_LOCALE))[2]


def get_locale() -> str:
    return _current_locale.get()


@contextmanager
def using_locale(locale: str):
    """Temporarily select a locale for jobs/tests outside an HTTP request."""
    token = _current_locale.set(normalize_locale(locale) or DEFAULT_LOCALE)
    try:
        yield
    finally:
        _current_locale.reset(token)


def translate(message: str, /, **params: Any) -> str:
    """Translate a Vietnamese message id and interpolate named parameters."""
    template = EN_MESSAGES.get(message, message) if get_locale() == "en" else message
    return template.format(**params) if params else template


# Alias familiar to gettext users and concise at HTTPException call sites.
tr = translate


class LocaleMiddleware:
    """Pure ASGI middleware so request locale reaches sync FastAPI services."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        locale = negotiate_locale(Headers(scope=scope).get("accept-language"))
        token = _current_locale.set(locale)
        is_api_response = scope.get("path", "").startswith("/api/")

        async def send_with_language(message):
            if message["type"] == "http.response.start" and is_api_response:
                headers = MutableHeaders(scope=message)
                # Một response cụ thể (ví dụ audio TTS luôn là tiếng Việt) có
                # thể khai ngôn ngữ chính xác hơn ngôn ngữ giao diện yêu cầu.
                if not headers.get("content-language"):
                    headers["Content-Language"] = locale

                vary = [
                    value.strip()
                    for value in (headers.get("vary") or "").split(",")
                    if value.strip()
                ]
                if not any(value.lower() == "accept-language" for value in vary):
                    vary.append("Accept-Language")
                    headers["Vary"] = ", ".join(vary)
            await send(message)

        try:
            await self.app(scope, receive, send_with_language)
        finally:
            _current_locale.reset(token)
