from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AuthExchange(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class SessionCreate(BaseModel):
    module: Literal["listening", "reading", "writing", "speaking"]
    question_id: str | None = None
    passage_id: str | None = None
    assessment_pack_id: str | None = None
    practice_mode: Literal["full_mock", "section_practice", "question_type_drill", "skill_drill"] | None = None
    source_id: str | None = None
    mode: str | None = None
    time_limit_minutes: float | None = Field(default=None, gt=0)


class AssessmentPackCreate(BaseModel):
    module: Literal["listening", "reading", "writing", "speaking"]
    title: str = Field(min_length=1, max_length=200)
    question_ids: list[str] = Field(min_length=1, max_length=100)


class AssessmentRunCreate(BaseModel):
    pack_id: str = Field(min_length=1, max_length=200)


class AssessmentResponseSave(BaseModel):
    section_key: str = Field(min_length=1, max_length=200)
    response: dict[str, Any]
    expected_revision: int | None = Field(default=None, ge=0)
    flagged: bool = False


class AssessmentNavigationSave(BaseModel):
    navigation: dict[str, Any]
    expected_revision: int | None = Field(default=None, ge=0)


class AudioPlaybackUpdate(BaseModel):
    position_seconds: float = Field(ge=0)
    completed: bool = False


class WritingAssessmentScore(BaseModel):
    task1: dict[str, Any]
    task2: dict[str, Any]


class ContentReviewCreate(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    decision: Literal["approved", "changes_requested", "rejected"]
    checklist: dict[str, bool] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=5000)


class BackupRestore(BaseModel):
    confirmed: bool = False


class ProfileUpdate(BaseModel):
    updates: dict[str, Any]
    complete_onboarding: bool = False


class DiagnosticStart(BaseModel):
    mode: Literal["quick", "full"] = "quick"


class DiagnosticAttach(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)


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


class ListeningAttemptSubmit(BaseModel):
    item_id: str = Field(min_length=1, max_length=100)
    user_answer: str = Field(min_length=1, max_length=500)
    error_tags: list[str] = Field(default_factory=list, max_length=10)
    expected_revision: int | None = Field(default=None, ge=0)


class SpeakingHandoffCreate(BaseModel):
    mode: Literal["full_mock", "part2"] = "full_mock"
    provider: str = Field(default="external_voice_live", min_length=1, max_length=100)
    question_ids: list[str] | None = Field(default=None, max_length=20)
    seed: int | None = None


class SpeakingReportImport(BaseModel):
    provider: str = Field(default="external_voice_live", min_length=1, max_length=100)
    mode: str = Field(default="full_mock", min_length=1, max_length=100)
    transcript: str | None = Field(default=None, max_length=100_000)
    report: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class StoryCreate(BaseModel):
    story_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=80)
    title: str = Field(min_length=1, max_length=200)
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    events: list[str] = Field(min_length=1)
    feelings: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    usable_topics: list[str] = Field(min_length=1)
    expressions: list[str] = Field(default_factory=list)


class AgentRunCreate(BaseModel):
    adapter_id: Literal["mock", "manual", "opencode", "claude"]
    study_session_id: str
    action: str
    output_contract: Literal[
        "writing-review@1",
        "reading-review@1",
        "listening-review@1",
        "speaking-evaluation@1",
        "study-plan@1",
        "diagnostic-summary@1",
        "weekly-coaching@1",
    ]
    timeout_seconds: int = Field(default=120, ge=5, le=1800)
    source_type: str | None = None
    explicit_consent: bool = False
    agent_provider: str | None = Field(default=None, max_length=100)
    agent_version: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    model_display_name: str | None = Field(default=None, max_length=200)
    agent_session_id: str | None = Field(default=None, max_length=300)


class AgentResultImport(BaseModel):
    result: dict[str, Any]
    usage: dict[str, Any] = Field(default_factory=dict)
    agent_provider: str | None = Field(default=None, max_length=100)
    agent_version: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    model_display_name: str | None = Field(default=None, max_length=200)
    agent_session_id: str | None = Field(default=None, max_length=300)
