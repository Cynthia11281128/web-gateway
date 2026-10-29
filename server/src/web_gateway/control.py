"""Loopback-only login checks and website directory; never proxies applications."""

import argparse
import hmac
import html
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from aiohttp import web

from .auth import Login, safe_next, upstream_cookie
from .config import Settings
from .publishing import Sites


CSS = """
*{box-sizing:border-box}body{margin:0;font:15px system-ui;color:#202824;background:#fff}
header{border-bottom:1px solid #dde3df}header,main{padding:20px 24px}
header>div,main{max-width:1000px;margin:auto}header>div{display:flex;align-items:center;
justify-content:space-between;gap:16px}h1{font-size:22px;margin:0}button{font:inherit;
background:white;border:1px solid #adb8b1;border-radius:6px;padding:8px 12px;cursor:pointer}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:14px 12px;
border-bottom:1px solid #e3e8e5}th{font-size:13px;color:#59665f;font-weight:500}
a{color:#17664b;text-decoration:none}a:hover{text-decoration:underline}
.kind{color:#59665f}.empty{padding:32px 0;color:#59665f}
@media(max-width:600px){header,main{padding:16px}.path{display:none}th,td{padding:14px 6px}}
"""


class Control:
    def __init__(self, settings):
        self.settings = settings
        self.login = Login(settings.auth_file, secure=False)
        self.sites = Sites(settings)
        self.token = (settings.state_root / "internal-token").read_text().strip()
        self.app = web.Application(client_max_size=4096, middlewares=[self.internal])
        self.app.add_routes([
            web.get("/login", self.login.form), web.post("/login", self.sign_in),
            web.get("/auth/check", self.check),
            web.get("/", self.index), web.get("/api/sites", self.list_sites),
            web.post("/logout", self.logout), web.get("/healthz", self.health),
        ])

    @web.middleware
    async def internal(self, request, handler):
        if request.path == "/healthz":
            return await handler(request)
        if not hmac.compare_digest(request.headers.get("X-Gateway-Internal", ""), self.token):
            raise web.HTTPForbidden()
        return await handler(request)

    def origin(self, request, required=False):
        origin = request.headers.get("Origin")
        if (required and not origin) or (origin and origin != self.settings.public_origin):
            raise web.HTTPForbidden(text="Origin not allowed")

    async def sign_in(self, request):
        self.origin(request, required=True)
        return await self.login.submit(request)

    async def check(self, request):
        self.origin(request)
        method = request.headers.get("X-Forwarded-Method", "GET")
        if method not in {"GET", "HEAD", "OPTIONS"}:
            self.origin(request, required=True)
        if self.login.authenticated(request):
            return web.Response(status=204, headers={"X-Gateway-Cookie": upstream_cookie(request)})
        uri = request.headers.get("X-Forwarded-Uri", "/")
        path = urlsplit(uri).path
        navigate = ("text/html" in request.headers.get("Accept", "")
                    or request.headers.get("Sec-Fetch-Mode") == "navigate")
        if (method in {"GET", "HEAD"} and navigate
                and not path.endswith(("/proxy", "/ws"))
                and (path in {"/", "/index.html"} or path.startswith("/apps/"))):
            raise web.HTTPFound("/login?" + urlencode({"next": safe_next(uri)}))
        raise web.HTTPUnauthorized(text="Sign in required")

    def require_login(self, request):
        if not self.login.authenticated(request):
            raise web.HTTPUnauthorized()

    async def index(self, request):
        self.require_login(request)
        rows = "".join(
            '<tr><td><a href="/apps/{id}/">{title}</a></td><td class="kind">{kind}</td>'
            '<td class="path">/apps/{id}/</td></tr>'.format(
                id=site["id"], title=html.escape(site.get("title", site["id"])),
                kind="Static" if site["kind"] == "static" else "Service")
            for site in self.sites.read())
        content = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Web Apps</title><style>' + CSS + '</style></head><body>'
            '<header><div><h1>Web Apps</h1><form method="post" action="/logout">'
            '<button type="submit">Sign Out</button></form></div></header><main>'
            + ('<table><thead><tr><th>Website</th><th>Type</th><th class="path">Path</th>'
               '</tr></thead><tbody>' + rows + '</tbody></table>' if rows
               else '<div class="empty">No websites</div>')
            + '</main></body></html>')
        return web.Response(text=content, content_type="text/html",
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "default-src 'none'; "
                                     "style-src 'unsafe-inline'; form-action 'self'; "
                                     "frame-ancestors 'none'; base-uri 'none'"})

    async def list_sites(self, request):
        self.require_login(request)
        return web.json_response([{"id": site["id"], "title": site.get("title", site["id"]),
                                   "kind": site["kind"], "url": self.sites.url(site["id"])}
                                  for site in self.sites.read()],
                                 headers={"Cache-Control": "no-store"})

    async def logout(self, request):
        self.origin(request, required=True)
        self.require_login(request)
        return await self.login.logout(request)

    async def health(self, request):
        return web.json_response({"status": "ok"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.load(args.config)
    web.run_app(Control(settings).app, host="127.0.0.1", port=settings.control_port,
                access_log=None)


if __name__ == "__main__":
    main()
