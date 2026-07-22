from __future__ import annotations

import socket
import threading
import webbrowser
from pathlib import Path

from .auth import AuthState
from .app import create_app


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

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sock.close()
        raise RuntimeError(f"Cannot bind the local UI to 127.0.0.1:{port}") from exc
    sock.listen(128)
    selected_port = int(sock.getsockname()[1])
    origin = f"http://127.0.0.1:{selected_port}"
    auth = AuthState.create()
    launch_url = f"{origin}/#launch_token={auth.launch_token}"
    app = create_app(home=home, auth=auth, allowed_origin=origin)
    config = uvicorn.Config(app, host="127.0.0.1", port=selected_port, log_level="info", workers=1)
    server = uvicorn.Server(config)
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(launch_url)).start()
    print(f"IELTS Study Desk: {launch_url}")
    print("Press Ctrl+C to stop.")
    server.run(sockets=[sock])
    return launch_url

