"""Studio authentication helpers."""

from __future__ import annotations

from html import escape

from fastapi.responses import HTMLResponse

from reconforge.studio.components import _layout

STUDIO_SESSION_COOKIE = "reconforge_studio_session"


def _safe_denial_page(title: str, message: str, *, status_code: int, auth_nav: str = "") -> HTMLResponse:
    body = f"<h2>{escape(title)}</h2><p>{escape(message)}</p>"
    return HTMLResponse(_layout(title, body, auth_nav=auth_nav), status_code=status_code)
