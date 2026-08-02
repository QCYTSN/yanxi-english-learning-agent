from __future__ import annotations

import sys
from pathlib import Path

from ielts_coach import desktop


def test_packaged_stop_waits_for_background_service(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []
    statuses = iter(({"running": True}, {"running": False}))

    monkeypatch.setattr(sys, "argv", ["ielts-study-desk", "--stop", "--home", str(tmp_path)])
    monkeypatch.setattr(desktop, "resolve_home", lambda value: Path(value).resolve())
    monkeypatch.setattr(desktop, "stop_ui", lambda home: calls.append(home) or True)
    monkeypatch.setattr(desktop, "ui_status", lambda home: next(statuses))
    monkeypatch.setattr(desktop.time, "sleep", lambda _seconds: None)

    desktop.main()

    assert calls == [tmp_path.resolve()]
