from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from ..init_home import initialise_home
from .auth import AuthState
from .app import create_app


INSTANCE_NAME = "ui-instance.json"
LOCK_NAME = "ui-service.lock"


def _runtime_dir(home: Path) -> Path:
    path = home / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def instance_path(home: Path) -> Path:
    return _runtime_dir(home) / INSTANCE_NAME


def _write_instance(home: Path, value: dict[str, Any]) -> None:
    target = instance_path(home)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _read_instance(home: Path) -> dict[str, Any] | None:
    target = instance_path(home)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    required = {"pid", "port", "origin", "control_token"}
    return value if isinstance(value, dict) and required.issubset(value) else None


def _clear_instance(home: Path, *, pid: int | None = None) -> None:
    target = instance_path(home)
    current = _read_instance(home)
    if pid is not None and current and int(current.get("pid", -1)) != pid:
        return
    target.unlink(missing_ok=True)


def _request_json(url: str, *, control_token: str | None = None, timeout: float = 1.0) -> dict[str, Any]:
    headers = {"X-IELTS-Control-Token": control_token} if control_token else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _healthy(instance: dict[str, Any]) -> bool:
    try:
        payload = _request_json(f"{instance['origin']}/api/health")
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return payload.get("status") == "ok" and payload.get("app") == "ielts-ai-coach"


def _launch_url(instance: dict[str, Any]) -> str:
    payload = _request_json(
        f"{instance['origin']}/api/internal/launch",
        control_token=str(instance["control_token"]),
    )
    return f"{payload['origin']}/#launch_token={payload['launch_token']}"


def serve_ui(
    home: Path,
    *,
    port: int = 0,
    open_browser: bool = True,
) -> str:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            'The UI requires optional dependencies. Install with: pip install -e ".[ui]"'
        ) from exc

    home = home.resolve()
    lock = FileLock(str(_runtime_dir(home) / LOCK_NAME))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise RuntimeError("The IELTS Study Desk is already running for this IELTS_HOME.") from exc

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sock.close()
        lock.release()
        raise RuntimeError(f"Cannot bind the local UI to 127.0.0.1:{port}") from exc
    sock.listen(128)
    selected_port = int(sock.getsockname()[1])
    origin = f"http://127.0.0.1:{selected_port}"
    auth = AuthState.create()
    control_token = secrets.token_urlsafe(32)
    launch_url = f"{origin}/#launch_token={auth.launch_token}"
    app = create_app(
        home=home,
        auth=auth,
        allowed_origin=origin,
        control_token=control_token,
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=selected_port, log_level="info", workers=1)
    server = uvicorn.Server(config)
    app.state.server = server
    _write_instance(
        home,
        {
            "pid": os.getpid(),
            "port": selected_port,
            "origin": origin,
            "control_token": control_token,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(launch_url)).start()
    print(f"IELTS Study Desk: {launch_url}")
    print("Press Ctrl+C to stop.")
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        _clear_instance(home, pid=os.getpid())
        lock.release()
    return launch_url


def open_ui(home: Path, *, port: int = 0, open_browser: bool = True) -> str:
    home = home.resolve()
    current = _read_instance(home)
    if current and _healthy(current):
        try:
            launch_url = _launch_url(current)
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            _clear_instance(home)
        else:
            if open_browser:
                webbrowser.open(launch_url)
            return launch_url
    if current:
        _clear_instance(home)

    # The shortcut must be sufficient after upgrades: migrate the local schema
    # and install idempotent bundled resources before starting a new service.
    initialise_home(home)

    command = [
        sys.executable,
        "-m",
        "ielts_coach.web.background",
        "serve",
        "--home",
        str(home),
        "--port",
        str(port),
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:  # pragma: no cover - Windows is the primary shortcut target
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        time.sleep(0.15)
        current = _read_instance(home)
        if current and _healthy(current):
            launch_url = _launch_url(current)
            if open_browser:
                webbrowser.open(launch_url)
            return launch_url
    raise RuntimeError("The local Study Desk did not become ready within 12 seconds.")


def stop_ui(home: Path) -> bool:
    home = home.resolve()
    current = _read_instance(home)
    if not current:
        return False
    if not _healthy(current):
        _clear_instance(home)
        return False
    _request_json(
        f"{current['origin']}/api/internal/stop",
        control_token=str(current["control_token"]),
    )
    return True


def ui_status(home: Path) -> dict[str, Any]:
    current = _read_instance(home.resolve())
    if not current or not _healthy(current):
        return {"running": False}
    return {
        "running": True,
        "pid": current["pid"],
        "port": current["port"],
        "origin": current["origin"],
        "started_at": current.get("started_at"),
    }
