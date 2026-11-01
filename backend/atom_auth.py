"""One-token browser login for the single-process Atoms workbench."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .settings import Settings


COOKIE = "atom_session"
SESSION_SECONDS = 12 * 60 * 60


def _signature(token: str, timestamp: str) -> str:
    return hmac.new(token.encode("utf-8"), timestamp.encode("ascii"), hashlib.sha256).hexdigest()


def valid_session(cookie: str | None, token: str, now: int | None = None) -> bool:
    if not cookie or not token:
        return False
    timestamp, separator, signature = cookie.partition(".")
    if not separator or not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12:
        return False
    current = int(time.time()) if now is None else now
    issued = int(timestamp)
    return current - SESSION_SECONDS <= issued <= current + 60 and hmac.compare_digest(signature, _signature(token, timestamp))


def login_page(error: bool = False) -> HTMLResponse:
    message = "<p role='alert'>Token 无效，请重试。</p>" if error else ""
    body = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>MYATOM 登录</title><style>body{font:18px system-ui;background:#f8f6ef;color:#183329;display:grid;place-items:center;min-height:100vh;margin:0}"
            "main{width:min(90vw,400px);background:white;padding:32px;border:1px solid #d9ded5;border-radius:16px}"
            "label,input,button{display:block;width:100%;box-sizing:border-box}input,button{font:inherit;padding:12px;margin-top:10px}"
            "button{background:#164c3b;color:white;border:0;border-radius:8px;cursor:pointer}p{color:#9b3c27}</style>"
            f"<main><h1>MYATOM</h1><p>输入部署访问 Token。</p>{message}"
            "<form method='post' action='/api/auth/login'><label for='token'>访问 Token</label>"
            "<input id='token' name='token' type='password' autocomplete='current-password' required>"
            "<button type='submit'>登录</button></form></main></html>")
    return HTMLResponse(body, status_code=401 if error else 200, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    })


def install_atom_auth(app: FastAPI, settings: Settings) -> None:
    token = settings.atom_access_token
    if len(token) < 32:
        raise RuntimeError("APP_ENV=atom 需要至少 32 字符的 ATOM_ACCESS_TOKEN")

    @app.middleware("http")
    async def atom_gate(request: Request, call_next):
        path = request.url.path
        if path not in {"/login", "/api/auth/login", "/api/health"} and not valid_session(request.cookies.get(COOKIE), token):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "请先使用访问 Token 登录"}, status_code=401,
                                    headers={"Cache-Control": "no-store"})
            return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/login", include_in_schema=False)
    def login():
        return login_page()

    @app.post("/api/auth/login", include_in_schema=False)
    async def submit_login(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                return login_page(error=True)
        supplied = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True).get("token", [""])[0]
        if not hmac.compare_digest(supplied, token):
            return login_page(error=True)
        timestamp = str(int(time.time()))
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, f"{timestamp}.{_signature(token, timestamp)}", max_age=SESSION_SECONDS,
                            httponly=True, secure=settings.workbench_origin.startswith("https://"),
                            samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/logout", include_in_schema=False)
    def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE, path="/")
        return response
