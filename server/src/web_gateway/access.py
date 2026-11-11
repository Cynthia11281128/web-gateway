"""Persistent access policy, read on each request for live administration."""

import json


def password_required(state_root):
    path = state_root / "access.json"
    if not path.exists():
        return True
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or type(value.get("require_password")) is not bool:
        raise ValueError("Invalid access policy")
    return value["require_password"]
