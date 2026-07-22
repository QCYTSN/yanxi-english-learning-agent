from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AuthExchange(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class SessionCreate(BaseModel):
    module: Literal["listening", "reading", "writing", "speaking"]
    question_id: str | None = None
    passage_id: str | None = None
    source_id: str | None = None
    mode: str | None = None
    time_limit_minutes: float | None = Field(default=None, gt=0)


class SessionTransition(BaseModel):
    status: str


class DraftSave(BaseModel):
    draft_kind: str = Field(min_length=1, max_length=50)
    expected_revision: int | None = Field(default=None, ge=0)
    payload: dict[str, Any]


class WritingVersionSubmit(BaseModel):
    label: Literal["v1", "v2", "final"] = "v1"
    content: str = Field(min_length=1)
    expected_revision: int | None = Field(default=None, ge=0)


class ReadingHintSubmit(BaseModel):
    level: int | None = Field(default=None, ge=1, le=3)
    expected_revision: int | None = Field(default=None, ge=0)


class ReadingAnswersSubmit(BaseModel):
    answers: list[dict[str, Any]] = Field(min_length=1)
    expected_revision: int | None = Field(default=None, ge=0)


class AgentRunCreate(BaseModel):
    adapter_id: Literal["mock", "manual"]
    study_session_id: str
    action: str
    output_contract: Literal["writing-review@1", "reading-review@1"]
    source_type: str | None = None
    explicit_consent: bool = False


class AgentResultImport(BaseModel):
    result: dict[str, Any]

