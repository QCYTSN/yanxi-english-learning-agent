from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field

from fastapi import HTTPException, Request


COOKIE_NAME = "ielts_ui_session"


@dataclass
class AuthState:
    launch_token: str
    launch_consumed: bool = False
    sessions: set[str] = field(default_factory=set)

    @classmethod
    def create(cls) -> "AuthState":
        return cls(launch_token=secrets.token_urlsafe(32))

    def exchange(self, supplied: str) -> str:
        if self.launch_consumed or not hmac.compare_digest(self.launch_token, supplied):
            raise HTTPException(status_code=401, detail="Invalid or expired launch token")
        self.launch_consumed = True
        session = secrets.token_urlsafe(32)
        self.sessions.add(session)
        return session

    def valid_session(self, value: str | None) -> bool:
        return bool(value and any(hmac.compare_digest(value, item) for item in self.sessions))


def require_session(request: Request) -> None:
    state: AuthState = request.app.state.auth
    if not state.valid_session(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="UI session required")

