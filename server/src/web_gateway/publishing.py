"""Local, allowlisted site registration and transactional Caddy configuration."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import urlsplit


ID = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
DENIED = {22, 2019, 2375, 2376, 3306, 5432, 6379, 8171, 10250}


def private_write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Sites:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.state_root / "sites.json"

    @contextmanager
    def lock(self):
        with (self.settings.state_root / "publish.lock").open("a") as stream:
            stream.flush()
            os.chmod(stream.name, 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def read(self):
        values = json.loads(self.path.read_text()) if self.path.exists() else []
        self.validate_registry(values)
        return values

    def validate_registry(self, values):
        if not isinstance(values, list):
            raise ValueError("Invalid sites registry")
        for site in values:
            self.validate(site, check_files=False)
        if len({site["id"] for site in values}) != len(values):
            raise ValueError("Duplicate site IDs")

    def validate(self, site, *, check_files=True):
        if not isinstance(site, dict):
            raise ValueError("Invalid site record")
        name = site.get("id", "")
        if (not isinstance(name, str) or not ID.fullmatch(name)
                or site.get("kind") not in {"static", "service"}):
            raise ValueError("Site ID must be lowercase letters/digits/_/- and start with a letter")
        title = site.get("title", name)
        if not isinstance(title, str) or not 1 <= len(title) <= 80 or "\n" in title:
            raise ValueError("Title must have 1..80 characters")
        if site["kind"] == "static":
            if not isinstance(site.get("root"), str):
                raise ValueError("Static site requires a directory")
            root = Path(site["root"])
            workspace = self.settings.workspace_root
            if (not root.is_absolute() or ".." in root.parts
                    or not root.is_relative_to(workspace) or root == workspace
                    or root.name not in {"dist", "public"}):
                raise ValueError("Publish a dedicated dist/ or public/ directory inside the workspace")
            if type(site.get("spa", False)) is not bool:
                raise ValueError("Static site requires index.html and boolean spa")
            if check_files:
                if not root.is_dir() or root.resolve(strict=True) != root:
                    raise ValueError("Static directory must exist at its canonical path")
                # Publication-time check only: the owner must keep this tree trusted.
                for item in root.rglob("*"):
                    if item.is_symlink() or item.name.startswith("."):
                        raise ValueError("Static directory must not contain symlinks or hidden files")
                if not (root / "index.html").is_file():
                    raise ValueError("Static site requires index.html")
        else:
            if not isinstance(site.get("upstream"), str):
                raise ValueError("Service requires an upstream URL")
            url = urlsplit(site["upstream"])
            if (url.scheme != "http" or url.hostname != "127.0.0.1"
                    or url.path or url.query or url.fragment or url.username or url.password
                    or not url.port or not 1024 <= url.port <= 65535
                    or url.port in DENIED | {self.settings.port, self.settings.control_port}
                    or site.get("prefix_mode") not in {"strip", "preserve"}):
                raise ValueError("Upstream must be an approved loopback HTTP port without a path")

    def url(self, name):
        return self.settings.public_origin + "/apps/" + name + "/"

    def apply(self, values, *, offline=False):
        self.validate_registry(values)
        text = caddyfile(self.settings, values)
        candidate = self.settings.state_root / "Caddyfile.candidate"
        previous = self.settings.caddyfile.read_text() if self.settings.caddyfile.exists() else None
        registry = self.path.read_text() if self.path.exists() else None
        active = self.settings.admin_socket.exists()
        if active and offline:
            raise ValueError("Cannot skip reload while Caddy is running")
        if not active and not offline:
            raise ValueError("Gateway is stopped; start it or explicitly use --offline")
        try:
            private_write(candidate, text)
            subprocess.run([str(self.settings.caddy), "validate", "--config", str(candidate),
                            "--adapter", "caddyfile"], check=True, capture_output=True, text=True)
            if active:
                subprocess.run([str(self.settings.caddy), "reload", "--config", str(candidate),
                                "--adapter", "caddyfile", "--address",
                                "unix/" + str(self.settings.admin_socket)],
                               check=True, capture_output=True, text=True)
            try:
                private_write(self.path, json.dumps(values, indent=2) + "\n")
                private_write(self.settings.caddyfile, text)
            except BaseException:
                try:
                    for path, content in ((self.path, registry),
                                          (self.settings.caddyfile, previous)):
                        if content is None:
                            path.unlink(missing_ok=True)
                        else:
                            private_write(path, content)
                finally:
                    if active and previous:
                        private_write(candidate, previous)
                        subprocess.run([str(self.settings.caddy), "reload",
                                        "--config", str(candidate), "--adapter", "caddyfile",
                                        "--address", "unix/" + str(self.settings.admin_socket)],
                                       check=True, capture_output=True, text=True)
                raise
        finally:
            candidate.unlink(missing_ok=True)

    def publish(self, site, *, replace=False, offline=False):
        with self.lock():
            self.validate(site)
            values = self.read()
            if any(item["id"] == site["id"] for item in values) and not replace:
                raise ValueError("Site exists; use --replace to update it")
            values = [item for item in values if item["id"] != site["id"]] + [site]
            self.apply(sorted(values, key=lambda item: item["id"]), offline=offline)
        return self.url(site["id"])

    def unpublish(self, name, *, offline=False):
        with self.lock():
            values = self.read()
            if not any(site["id"] == name for site in values):
                raise ValueError("Unknown site")
            self.apply([site for site in values if site["id"] != name], offline=offline)


def caddyfile(settings, sites):
    token = (settings.state_root / "internal-token").read_text().strip()
    control = f"127.0.0.1:{settings.control_port}"
    lines = [
        "{", f"  admin unix/{settings.admin_socket}", "  auto_https off", "}",
        f"http://{settings.listen_host}:{settings.port} {{",
        f"  bind {settings.listen_host}",
        "  header X-Content-Type-Options nosniff",
        "  header X-Frame-Options DENY",
        "  route {",
        "    request_header -X-Gateway-Cookie",
        "    request_header -X-Gateway-Internal",
        "    @login path /login",
        "    handle @login {",
        f"      reverse_proxy {control} {{",
        f"        header_up X-Gateway-Internal {token}", "      }", "    }",
        "    handle {",
        f"      forward_auth {control} {{",
        "        uri /auth/check",
        f"        header_up X-Gateway-Internal {token}",
        "        copy_headers X-Gateway-Cookie", "      }",
    ]
    for site in sites:
        path = "/apps/" + site["id"]
        lines += [f"      redir {path} {path}/ 308"]
        strip = site["kind"] == "static" or site["prefix_mode"] == "strip"
        lines += [f"      {'handle_path' if strip else 'handle'} {path}/* {{"]
        if site["kind"] == "static":
            lines += [f"        root * {json.dumps(site['root'])}",
                      "        @private path_regexp private (^|/)\\.",
                      "        respond @private 404"]
            if site.get("spa"):
                lines += ["        try_files {path} /index.html"]
            lines += ["        file_server"]
        else:
            upstream = urlsplit(site["upstream"]).netloc
            lines += [
                f"        reverse_proxy {upstream} {{",
                "          header_up Cookie {http.request.header.X-Gateway-Cookie}",
                "          header_up -X-Gateway-Cookie",
                "          header_up -X-Gateway-Internal",
                f"          header_up X-Forwarded-Prefix {path}",
                "          transport http {", "            response_header_timeout 120s",
                "          }", "          stream_close_delay 5m", "        }",
            ]
        lines += ["      }"]
    lines += [
        "      @control path / /api/sites /logout",
        "      handle @control {",
        f"        reverse_proxy {control} {{",
        f"          header_up X-Gateway-Internal {token}", "        }", "      }",
        '      respond "Site not found" 404',
        "    }", "  }", "}", "",
    ]
    return "\n".join(lines)
