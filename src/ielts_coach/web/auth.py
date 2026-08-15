from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request


COOKIE_NAME = "ielts_ui_session"
CSRF_COOKIE_NAME = "ielts_ui_csrf"
CSRF_HEADER_NAME = "X-IELTS-CSRF"
LAUNCH_TOKEN_TTL_SECONDS = 120


@dataclass
class AuthState:
    launch_token: str
    launch_consumed: bool = False
    sessions: dict[str, str] = field(default_factory=dict)
    launch_tokens: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.launch_consumed:
            self.launch_tokens[self.launch_token] = (
                time.monotonic() + LAUNCH_TOKEN_TTL_SECONDS
            )

    @classmethod
    def create(cls) -> AuthState:
        return cls(launch_token=secrets.token_urlsafe(32))

    def issue_launch_token(self) -> str:
        self._discard_expired_launch_tokens()
        token = secrets.token_urlsafe(32)
        self.launch_tokens[token] = time.monotonic() + LAUNCH_TOKEN_TTL_SECONDS
        return token

    def exchange(self, supplied: str) -> str:
        self._discard_expired_launch_tokens()
        matched = next(
            (item for item in self.launch_tokens if hmac.compare_digest(item, supplied)),
            None,
        )
        if matched is None:
            raise HTTPException(status_code=401, detail="Invalid or expired launch token")
        self.launch_tokens.pop(matched, None)
        if hmac.compare_digest(self.launch_token, matched):
            self.launch_consumed = True
        session = secrets.token_urlsafe(32)
        self.sessions[session] = secrets.token_urlsafe(32)
        return session

    def valid_session(self, value: str | None) -> bool:
        return bool(value and any(hmac.compare_digest(value, item) for item in self.sessions))

    def csrf_token(self, session: str) -> str:
        token = self.sessions.get(session)
        if token is None:
            raise HTTPException(status_code=401, detail="UI session required")
        return token

    def valid_csrf(
        self,
        session: str | None,
        cookie_token: str | None,
        header_token: str | None,
    ) -> bool:
        if not session or not cookie_token or not header_token:
            return False
        expected = next(
            (
                token
                for stored_session, token in self.sessions.items()
                if hmac.compare_digest(stored_session, session)
            ),
            None,
        )
        return bool(
            expected
            and hmac.compare_digest(expected, cookie_token)
            and hmac.compare_digest(expected, header_token)
        )

    def _discard_expired_launch_tokens(self) -> None:
        now = time.monotonic()
        self.launch_tokens = {
            token: expires_at
            for token, expires_at in self.launch_tokens.items()
            if expires_at > now
        }


def require_session(request: Request) -> None:
    state: AuthState = request.app.state.auth
    if not state.valid_session(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="UI session required")
