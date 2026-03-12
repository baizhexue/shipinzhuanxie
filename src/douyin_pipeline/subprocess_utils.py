from __future__ import annotations

import os
import signal
import subprocess
from typing import Mapping, Optional, Sequence


def run_command(
    command: Sequence[str],
    *,
    timeout: Optional[int] = None,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": dict(env) if env is not None else None,
        "cwd": cwd,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(list(command), **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            process.args,
            timeout,
            output=stdout,
            stderr=stderr,
        )

    return subprocess.CompletedProcess(
        args=process.args,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
            return
        except Exception:
            pass

    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.kill()
        except Exception:
            return
