import json
import signal

import pytest

from web_gateway import service
from test_publishing import settings


@pytest.mark.parametrize("site_id", ["my-app", "web3d"])
def test_supervisor_only_manages_gateway_processes(settings, monkeypatch, site_id):
    (settings.state_root / "sites.json").write_text(json.dumps([
        {"id": site_id, "kind": "service", "upstream": "http://127.0.0.1:8201",
         "prefix_mode": "strip"}
    ]))
    handlers = {}
    children = []
    stopped = []

    class Process:
        def __init__(self, command, **kwargs):
            self.command = command
            self.pid = 10000 + len(children)
            children.append(self)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def stop_after_start(_):
        state = json.loads(service.processes(settings).read_text())
        assert set(state["children"]) == {"control", "caddy"}
        handlers[signal.SIGTERM]()

    monkeypatch.setattr(service.signal, "signal", lambda sig, handler: handlers.update({sig: handler}))
    monkeypatch.setattr(service.subprocess, "Popen", Process)
    monkeypatch.setattr(service.time, "sleep", stop_after_start)
    monkeypatch.setattr(service.os, "killpg", lambda pid, sig: stopped.append((pid, sig)))
    monkeypatch.setattr(service.os, "umask", lambda mask: None)
    service.run(settings)

    assert len(children) == 2
    assert "web_gateway.control" in children[0].command
    assert children[1].command[1] == "run"
    assert stopped == [(children[1].pid, signal.SIGTERM),
                       (children[0].pid, signal.SIGTERM)]
    assert not service.processes(settings).exists()
