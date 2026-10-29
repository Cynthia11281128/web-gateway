"""Single-user gateway login, with private password hashes and opaque cookies."""

import argparse
import asyncio
from collections import deque
import getpass
import hashlib
import hmac
import html
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit

from aiohttp import web


ROUNDS = 600_000
COOKIE = "web_gateway_session"
LIFETIME = 12 * 3600
LOGIN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Web Apps</title><style>
*{box-sizing:border-box}body{margin:0;font:16px system-ui;background:#f4f6f5;color:#202824}
main{width:min(360px,calc(100% - 40px));margin:80px auto}h1{font-size:24px}
label{display:block;margin:24px 0 8px}input,button{width:100%;font:inherit;padding:12px;
border:1px solid #a2aaa5;border-radius:6px}button{margin-top:16px;background:#23744b;
color:white;border:0;cursor:pointer}.error{color:#a32929}input:focus{outline:2px solid #23744b}
</style></head><body><main><h1>Web Apps</h1>
<form method="post" action="/login">
<input type="hidden" name="next" value="{next}">
<label for="password">Password</label>
<input id="password" name="password" type="password" required maxlength="256"
autocomplete="current-password" autofocus>
<button type="submit">Sign In</button><p class="error">{error}</p>
</form></main></body></html>"""


def safe_next(value):
    if not isinstance(value, str):
        return "/"
    try:
        parsed = urlsplit(value)
        if (parsed.scheme or parsed.netloc or parsed.fragment
                or not (parsed.path in {"", "/", "/index.html"}
                        or parsed.path.startswith("/apps/"))
                or any(ord(char) < 32 or char == "\\" for char in value)):
            return "/"
        return (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    except ValueError:
        return "/"


def write_credentials(path, password):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a dedicated password with 12..256 characters")
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    salt = secrets.token_bytes(16)
    value = {
        "algorithm": "pbkdf2-sha256", "rounds": ROUNDS, "salt": salt.hex(),
        "digest": hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ROUNDS).hex(),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        json.dump(value, stream)
        stream.write("\n")


class Login:
    def __init__(self, path, secure=False):
        path = Path(path).resolve(strict=True)
        stat = path.stat()
        if stat.st_mode & 0o077 or stat.st_uid != os.geteuid():
            raise ValueError("Auth file must be owned by this user and have mode 0600")
        value = json.loads(path.read_text())
        if (value.get("algorithm") != "pbkdf2-sha256"
                or type(value.get("rounds")) is not int or value["rounds"] != ROUNDS):
            raise ValueError("Unsupported password hash")
        self.salt = bytes.fromhex(value["salt"])
        self.digest = bytes.fromhex(value["digest"])
        if len(self.salt) != 16 or len(self.digest) != 32:
            raise ValueError("Invalid password hash")
        self.secure = secure
        self.sessions = {}
        self.attempts = deque()

    def authenticated(self, request):
        self.prune()
        return request.cookies.get(COOKIE) in self.sessions

    def verify(self, password):
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), self.salt, ROUNDS)
        return hmac.compare_digest(candidate, self.digest)

    def prune(self):
        now = time.monotonic()
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}

    @web.middleware
    async def protect(self, request, handler):
        if request.path == "/login":
            return await handler(request)
        if self.authenticated(request):
            return await handler(request)
        if request.method in {"GET", "HEAD"} and request.path in {"/", "/index.html"}:
            raise web.HTTPFound("/login?" + urlencode({"next": str(request.rel_url)}))
        raise web.HTTPUnauthorized(text="Sign in required")

    async def form(self, request, error="", status=200):
        # Replace placeholders without treating CSS braces as formatting fields.
        content = LOGIN.replace("{next}", html.escape(safe_next(request.query.get("next", "/")),
                                                     quote=True)).replace("{error}", error)
        return web.Response(text=content, content_type="text/html", status=status,
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "default-src 'none'; "
                                     "style-src 'unsafe-inline'; form-action 'self'; "
                                     "frame-ancestors 'none'; base-uri 'none'"})

    async def submit(self, request):
        now = time.monotonic()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 10:
            raise web.HTTPTooManyRequests(text="Try again in one minute",
                                          headers={"Retry-After": "60"})
        self.attempts.append(now)
        data = await request.post()
        password = data.get("password", "")
        if not isinstance(password, str) or len(password) > 256:
            raise web.HTTPBadRequest()
        if not await asyncio.to_thread(self.verify, password):
            return await self.form(request, error="Incorrect password", status=401)
        self.prune()
        if len(self.sessions) >= 32:
            self.sessions.pop(next(iter(self.sessions)))
        previous = request.cookies.get(COOKIE)
        self.sessions.pop(previous, None)
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.monotonic() + LIFETIME
        response = web.HTTPSeeOther(safe_next(data.get("next", "/")))
        response.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True,
                            secure=self.secure, samesite="Lax", path="/")
        response.headers["Cache-Control"] = "no-store"
        raise response

    async def logout(self, request):
        self.sessions.pop(request.cookies.get(COOKIE), None)
        response = web.HTTPSeeOther("/login")
        response.del_cookie(COOKIE, path="/")
        raise response


def upstream_cookie(request):
    cookies = SimpleCookie()
    cookies.load(request.headers.get("Cookie", ""))
    for name in (COOKIE, "web3d_session"):
        cookies.pop(name, None)
    return "; ".join(value.OutputString() for value in cookies.values())


def main():
    parser = argparse.ArgumentParser(description="Create a private gateway password hash")
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    password = getpass.getpass("Dedicated Web Apps password (12+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        write_credentials(args.file, password)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Created {args.file}; password was not saved as plaintext")


if __name__ == "__main__":
    main()
