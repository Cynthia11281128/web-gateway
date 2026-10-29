import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/bootstrap.sh"


@pytest.mark.parametrize("python", [None, "/custom/python"])
def test_bootstrap_python_selection_and_checksum(tmp_path, python):
    project = tmp_path / "gateway"
    script = project / "scripts/bootstrap.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, script)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    trace = tmp_path / "trace"
    mocks = {
        "uv": 'printf "%s\\n" "$*" >> "$TRACE"\n',
        "curl": """
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then
        shift
        case "$1" in
            */checksums.txt)
                printf '%0128d  caddy_2.11.7_linux_amd64.tar.gz\\n' 0 > "$1" ;;
            *) : > "$1" ;;
        esac
        break
    fi
    shift
done
""",
        "sha512sum": """
input="$(cat)"
printf '%s\\n' "$input" >> "$TRACE"
test "$input" = "$(printf '%0128d  caddy_2.11.7_linux_amd64.tar.gz' 0)"
""",
        "tar": """
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-C" ]; then
        shift
        printf '#!/usr/bin/env bash\\nexit 0\\n' > "$1/caddy"
        chmod +x "$1/caddy"
        break
    fi
    shift
done
""",
    }
    for name, body in mocks.items():
        executable = binaries / name
        executable.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        executable.chmod(0o755)
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
           "TRACE": str(trace)}
    env.pop("WEB_GATEWAY_PYTHON", None)
    if python:
        env["WEB_GATEWAY_PYTHON"] = python

    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    commands = trace.read_text().splitlines()
    assert commands[0] == f"venv --python {python or 'python3'} {project}/.venv"
    assert len(commands[-1].split()[0]) == 128
    assert commands[-1].split()[1] == "caddy_2.11.7_linux_amd64.tar.gz"
