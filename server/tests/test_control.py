import asyncio

from aiohttp.test_utils import TestClient, TestServer

from web_gateway.auth import COOKIE, safe_next, write_credentials
from web_gateway.control import Control
from test_publishing import settings


def test_safe_app_return_paths():
    assert safe_next("/apps/my-app/?item=sample") == "/apps/my-app/?item=sample"
    for value in ("//outside.test", "/apps/\\outside", "/auth/check", "https://outside.test"):
        assert safe_next(value) == "/"


def test_control_and_cookie_filter(settings):
    settings.auth_file.unlink()
    write_credentials(settings.auth_file, "unique-test-password")
    (settings.state_root / "sites.json").write_text("[]")
    control = Control(settings)
    async def check():
        async with TestClient(TestServer(control.app)) as client:
            response = await client.get("/auth/check")
            assert response.status == 403
            internal = {"X-Gateway-Internal": "test-only-internal-token"}
            response = await client.get("/auth/check", headers={**internal,
                "Accept": "text/html",
                "X-Forwarded-Uri": "/apps/my-app/?item=sample"}, allow_redirects=False)
            assert response.status == 302
            assert "/apps/my-app/" in response.headers["Location"].replace("%2F", "/")
            response = await client.post("/login", headers=internal,
                                        data={"password": "unique-test-password"})
            assert response.status == 403
            response = await client.post("/login", headers={**internal,
                "Origin": settings.public_origin}, data={"password": "unique-test-password",
                "next": "/apps/my-app/"}, allow_redirects=False)
            assert response.status == 303
            token = response.cookies[COOKIE].value
            response = await client.get("/auth/check", headers={**internal,
                "Cookie": f"{COOKIE}={token}; app_cookie=value; web3d_session=old"})
            assert response.status == 204
            assert response.headers["X-Gateway-Cookie"] == "app_cookie=value"
            response = await client.get("/auth/check", headers={**internal,
                "X-Forwarded-Method": "POST", "Cookie": f"{COOKIE}={token}",
                "Origin": "http://unapproved.test"})
            assert response.status == 403
    asyncio.run(check())
