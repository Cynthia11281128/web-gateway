"""Local process supervisor for Caddy and login control."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .config import PROJECT, Settings
from .publishing import private_write


def processes(settings):
    return settings.state_root / "processes.json"


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def run(settings):
    lock = (settings.state_root / "service.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError("Gateway supervisor is already running")
    logs = settings.state_root / "logs"
    logs.mkdir(parents=True, mode=0o700, exist_ok=True)
    settings.admin_socket.unlink(missing_ok=True)
    stopping = False

    def stop_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    children = {}
    restarts = {}
    commands = {
        "control": [sys.executable, "-u", "-m", "web_gateway.control",
                    "--config", str(settings.config_path)],
        "caddy": [str(settings.caddy), "run", "--config", str(settings.caddyfile),
                  "--adapter", "caddyfile"],
    }
    env = {**os.environ, "XDG_DATA_HOME": str(settings.state_root / "caddy-data"),
           "XDG_CONFIG_HOME": str(settings.state_root / "caddy-config")}
    os.umask(0o077)

    def record():
        private_write(processes(settings), json.dumps({
            "supervisor": os.getpid(),
            "children": {name: proc.pid for name, proc in children.items()},
            "public_origin": settings.public_origin,
        }, indent=2) + "\n")

    def start(name):
        with (logs / (name + ".log")).open("ab") as stream:
            children[name] = subprocess.Popen(commands[name], cwd=PROJECT,
                                               stdout=stream, stderr=stream,
                                               stdin=subprocess.DEVNULL, env=env,
                                               start_new_session=True)
        record()

    def end_child(proc):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()

    try:
        for name in commands:
            start(name)
        print("RUNNING " + settings.public_origin, flush=True)
        while not stopping:
            for name, proc in tuple(children.items()):
                if proc.poll() is not None:
                    now = time.monotonic()
                    restarts[name] = [moment for moment in restarts.get(name, [])
                                      if now - moment < 60]
                    if len(restarts[name]) >= 5:
                        raise RuntimeError(name + " repeatedly exited; inspect logs")
                    restarts[name].append(now)
                    time.sleep(1)
                    if not stopping:
                        start(name)
            time.sleep(.5)
    finally:
        for name in ("caddy", "control"):
            if name in children:
                end_child(children[name])
        settings.admin_socket.unlink(missing_ok=True)
        processes(settings).unlink(missing_ok=True)
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", choices=["run", "stop", "status"])
    args = parser.parse_args()
    try:
        settings = Settings.load(args.config)
        if args.command == "run":
            run(settings)
        else:
            state = json.loads(processes(settings).read_text()) if processes(settings).exists() else {}
            if args.command == "stop":
                pid = state.get("supervisor")
                if not pid or not alive(pid):
                    raise ValueError("Gateway is not running")
                # Check command ownership before signalling a potentially stale PID.
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
                if b"web_gateway.service" not in command:
                    raise ValueError("PID no longer belongs to this supervisor")
                os.kill(pid, signal.SIGTERM)
                for _ in range(80):
                    if not processes(settings).exists():
                        print("Stopped")
                        return 0
                    time.sleep(.5)
                raise ValueError("Shutdown is still in progress; inspect service logs")
            status = {"running": bool(state.get("supervisor") and alive(state["supervisor"])),
                      "url": settings.public_origin,
                      "children": {name: alive(pid) for name, pid in state.get("children", {}).items()}}
            print(json.dumps(status, indent=2))
            return 0 if status["running"] and all(status["children"].values()) else 1
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
