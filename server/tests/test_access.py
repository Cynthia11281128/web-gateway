import json

import pytest

from web_gateway.access import password_required
from web_gateway.cli import disable_login
from web_gateway.config import Settings
from test_publishing import settings


def test_password_is_required_by_default(settings):
    assert password_required(settings.state_root)


@pytest.mark.parametrize("value", [{}, [], {"require_password": "false"},
                                  {"require_password": 0}, {"require_password": None}])
def test_invalid_access_policy_is_rejected(settings, value):
    (settings.state_root / "access.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Invalid access policy"):
        password_required(settings.state_root)


def test_disable_login_removes_credentials_without_changing_sites(settings):
    password = settings.auth_file.with_name("password.txt")
    password.write_text("test-only-password")
    registry = settings.state_root / "sites.json"
    registry.write_text("[]\n")
    disable_login(settings)
    assert not password_required(settings.state_root)
    assert not settings.auth_file.exists()
    assert not password.exists()
    assert registry.read_text() == "[]\n"
    assert (settings.state_root / "internal-token").read_text() == "test-only-internal-token"
    disable_login(settings)
    assert not password_required(settings.state_root)


def test_open_gateway_loads_without_password_file(settings):
    settings.config_path.write_text(json.dumps({
        "public_origin": settings.public_origin, "listen_host": settings.listen_host,
        "port": settings.port, "control_port": settings.control_port,
        "state_root": str(settings.state_root), "auth_file": str(settings.auth_file),
        "workspace_root": str(settings.workspace_root), "allow_insecure_http": True,
    }))
    settings.auth_file.unlink()
    with pytest.raises(FileNotFoundError):
        Settings.load(settings.config_path)
    disable_login(settings)
    loaded = Settings.load(settings.config_path)
    assert loaded.auth_file == settings.auth_file
    assert not password_required(loaded.state_root)
