from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


PROJECT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    public_origin: str
    listen_host: str
    port: int
    control_port: int
    state_root: Path
    auth_file: Path
    workspace_root: Path
    config_path: Path

    @classmethod
    def load(cls, path):
        path = Path(path).resolve(strict=True)
        values = json.loads(path.read_text())
        origin = values["public_origin"].rstrip("/")
        url = urlsplit(origin)
        host = ipaddress.IPv4Address(values["listen_host"])
        if host.is_unspecified or host.is_multicast:
            raise ValueError("Use a specific IPv4 listen address")
        if (url.scheme not in {"http", "https"} or not url.hostname or url.path
                or url.query or url.fragment or url.username or url.password):
            raise ValueError("Use an HTTP(S) origin without a path or credentials")
        if url.scheme == "http" and values.get("allow_insecure_http") is not True:
            raise ValueError("HTTP requires explicit allow_insecure_http")
        # This deployment terminates HTTP only; do not silently advertise nonexistent TLS.
        if url.scheme != "http":
            raise ValueError("Native TLS is not configured in this release")
        port, control = values["port"], values["control_port"]
        if (type(port) is not int or type(control) is not int
                or not 1024 <= port <= 65535 or not 1024 <= control <= 65535 or port == control
                or url.hostname != str(host) or (url.port or 80) != port):
            raise ValueError("Origin must match the listener; ports must be distinct")
        workspace = Path(values["workspace_root"]).resolve(strict=True)
        state = Path(values["state_root"]).resolve()
        if not workspace.is_dir() or not state.is_relative_to(workspace):
            raise ValueError("State must stay inside the workspace")
        state.mkdir(parents=True, mode=0o700, exist_ok=True)
        return cls(origin, str(host), port, control, state,
                   Path(values["auth_file"]).resolve(strict=True), workspace, path)

    @property
    def admin_socket(self):
        return self.state_root / "caddy-admin.sock"

    @property
    def caddy(self):
        return PROJECT / ".bin/caddy"

    @property
    def caddyfile(self):
        return self.state_root / "Caddyfile"
