import json

import pytest

from web_gateway.config import Settings
from web_gateway.publishing import Sites, caddyfile, private_write


@pytest.fixture
def settings(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    (tmp_path / "internal-token").write_text("test-only-internal-token")
    return Settings("http://127.0.0.1:8081", "127.0.0.1", 8081, 8100,
                    tmp_path, auth, tmp_path, tmp_path / "runtime.json")


def test_site_boundaries(settings):
    sites = Sites(settings)
    service = {"id": "app", "kind": "service", "upstream": "http://127.0.0.1:8201",
               "prefix_mode": "strip"}
    sites.validate(service)
    for upstream in ("http://localhost:8201", "http://127.0.0.1:8100",
                     "http://127.0.0.1:22", "http://127.0.0.1:8201/api",
                     "http://user:password@127.0.0.1:8201"):
        with pytest.raises(ValueError):
            sites.validate({**service, "upstream": upstream})
    with pytest.raises(ValueError):
        sites.validate({**service, "id": "../escape"})
    public = settings.state_root / "example/public"
    public.mkdir(parents=True)
    (public / "index.html").write_text("<h1>Example</h1>")
    static = {"id": "example", "kind": "static", "root": str(public), "spa": False}
    sites.validate(static)
    (public / "escape").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlinks"):
        sites.validate(static)
    (public / "escape").unlink()
    (public / ".env").write_text("private")
    with pytest.raises(ValueError, match="hidden"):
        sites.validate(static)


def test_config_auth_precedes_apps_and_keeps_prefix_mode(settings):
    sites = [{"id": "my-app", "kind": "service", "upstream": "http://127.0.0.1:8201",
              "prefix_mode": "strip"}]
    text = caddyfile(settings, sites)
    assert text.index("forward_auth") < text.index("handle_path /apps/my-app/*")
    assert "header_up -X-Gateway-Internal" in text
    assert "header_up Cookie {http.request.header.X-Gateway-Cookie}" in text
    assert "X-Forwarded-Prefix /apps/my-app" in text
    text = caddyfile(settings, [{**sites[0], "prefix_mode": "preserve"}])
    assert "handle /apps/my-app/*" in text and "handle_path /apps/my-app/*" not in text


def test_site_ids_do_not_add_legacy_redirects(settings):
    site = {"id": "web3d", "kind": "service", "upstream": "http://127.0.0.1:8201",
            "prefix_mode": "strip"}
    text = caddyfile(settings, [site])
    assert "handle_path /apps/web3d/*" in text
    assert "@legacy" not in text
    assert "query asset=*" not in text


def test_failed_validation_leaves_registry_unchanged(settings, monkeypatch):
    sites = Sites(settings)
    sites.path.write_text("[]\n")
    def fail(*args, **kwargs):
        raise ValueError("bad configuration")
    monkeypatch.setattr("web_gateway.publishing.subprocess.run", fail)
    with pytest.raises(ValueError):
        sites.publish({"id": "app", "kind": "service", "upstream": "http://127.0.0.1:8201",
                       "prefix_mode": "strip"}, offline=True)
    assert sites.path.read_text() == "[]\n"
    assert not (settings.state_root / "Caddyfile.candidate").exists()


def test_missing_static_directory_can_be_listed_and_unpublished(settings, monkeypatch):
    sites = Sites(settings)
    static = {"id": "missing", "kind": "static",
              "root": str(settings.state_root / "removed/public"), "spa": False}
    sites.path.write_text(json.dumps([static]))
    assert sites.read() == [static]
    monkeypatch.setattr("web_gateway.publishing.subprocess.run", lambda *args, **kwargs: None)
    sites.unpublish("missing", offline=True)
    assert sites.read() == []


def test_persistence_failure_restores_registry_and_config(settings, monkeypatch):
    sites = Sites(settings)
    sites.path.write_text("[]\n")
    settings.caddyfile.write_text("previous configuration\n")
    commands = []
    settings.admin_socket.touch()
    monkeypatch.setattr("web_gateway.publishing.subprocess.run",
                        lambda command, **kwargs: commands.append(command))
    failed = False

    def fail_once(path, value):
        nonlocal failed
        if path == settings.caddyfile and not failed:
            failed = True
            raise OSError("simulated disk failure")
        private_write(path, value)

    monkeypatch.setattr("web_gateway.publishing.private_write", fail_once)
    with pytest.raises(OSError, match="simulated"):
        sites.publish({"id": "app", "kind": "service",
                       "upstream": "http://127.0.0.1:8201", "prefix_mode": "strip"})
    assert sites.path.read_text() == "[]\n"
    assert settings.caddyfile.read_text() == "previous configuration\n"
    assert [command[1] for command in commands] == ["validate", "reload", "reload"]
    assert not (settings.state_root / "Caddyfile.candidate").exists()
