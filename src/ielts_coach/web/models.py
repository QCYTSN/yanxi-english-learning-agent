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
    practice_unit_id: str | None = Field(default=None, min_length=1, max_length=120)


class AssessmentPackCreate(BaseModel):
    module: Literal["listening", "reading", "writing", "speaking"]
    title: str = Field(min_length=1, max_length=200)
    question_ids: list[str] = Field(min_length=1, max_length=100)


class AssessmentRunCreate(BaseModel):
    pack_id: str = Field(min_length=1, max_length=200)
    practice_unit_id: str | None = Field(default=None, min_length=1, max_length=120)


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
    practice_unit_id: str | None = Field(default=None, min_length=1, max_length=120)


class TodayMaterialise(BaseModel):
    slot: Literal["primary", "consolidation", "diagnostic"]


class TodayIntent(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class StudyThreadCreate(BaseModel):
    title: str = Field(default="新的 IELTS 学习对话", min_length=1, max_length=120)
    module: Literal["listening", "reading", "writing", "speaking", "mixed"] = "mixed"
    model_provider_id: str | None = Field(default=None, max_length=120)
    source_context: dict[str, Any] = Field(default_factory=dict)


class StudyThreadUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class LearnerMemoryCreate(BaseModel):
    memory_type: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    scope: str = Field(default="teaching_style", min_length=1, max_length=80)
    source_thread_id: str | None = Field(default=None, max_length=120)
    source_session_id: str | None = Field(default=None, max_length=120)


class LearnerMemoryUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "dismissed"] | None = None
    scope: str | None = Field(default=None, min_length=1, max_length=80)


class TutorContextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    module: Literal["listening", "reading", "writing", "speaking"] | None = None


class TutorProposalDecision(BaseModel):
    decision: Literal["confirm", "dismiss"]


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
    question_id: str | None = Field(default=None, min_length=1, max_length=200)
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
    mode: Literal["full_mock", "part1", "part2", "part3"] = "full_mock"
    provider: str = Field(default="external_voice_live", min_length=1, max_length=100)
    question_ids: list[str] | None = Field(default=None, max_length=20)
    seed: int | None = None
    practice_unit_id: str | None = Field(default=None, min_length=1, max_length=120)


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
    adapter_id: Literal[
        "mock", "manual", "opencode", "claude", "codex-managed"
    ] | None = None
    model_provider_id: str | None = Field(default=None, max_length=120)
    execution_profile_id: str | None = Field(default=None, max_length=120)
    study_session_id: str | None = Field(default=None, max_length=120)
    study_thread_id: str | None = Field(default=None, max_length=120)
    user_message_id: str | None = Field(default=None, max_length=120)
    action: str
    output_contract: Literal[
        "writing-review@1",
        "writing-mock-review@1",
        "reading-review@1",
        "listening-review@1",
        "speaking-evaluation@1",
        "study-plan@1",
        "diagnostic-summary@1",
        "weekly-coaching@1",
        "study-help@1",
    ]
    timeout_seconds: int = Field(default=300, ge=5, le=1800)
    source_type: str | None = None
    explicit_consent: bool = False
    agent_provider: str | None = Field(default=None, max_length=100)
    agent_version: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    model_display_name: str | None = Field(default=None, max_length=200)
    agent_session_id: str | None = Field(default=None, max_length=300)


class ExecutionProfileUpdate(BaseModel):
    model_id: str | None = Field(default=None, max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=40)
    is_enabled: bool | None = None
    is_default: bool | None = None
    config: dict[str, Any] | None = None


class ModelProviderCreate(BaseModel):
    provider_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    provider_kind: Literal["openai_compatible", "local_http"]
    base_url: str = Field(min_length=8, max_length=500)
    model_id: str = Field(min_length=1, max_length=200)
    auth_mode: Literal["api_key", "none"] = "api_key"
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)
    role: Literal["primary", "fallback", "disabled"] = "disabled"
    config: dict[str, Any] = Field(default_factory=dict)


class ModelProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=40)
    role: Literal["primary", "fallback", "disabled"] | None = None
    fallback_order: int | None = Field(default=None, ge=1, le=100)
    is_enabled: bool | None = None
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)
    clear_api_key: bool = False
    config: dict[str, Any] | None = None


class ContentImportPagePlanUpdate(BaseModel):
    stored_name: str = Field(min_length=1, max_length=180)
    pages: dict[str, Literal[
        "unassigned",
        "passage",
        "questions",
        "answer_key",
        "task_visual",
        "transcript",
        "instructions",
        "exclude",
    ]]


class ContentImportOcrRequest(BaseModel):
    stored_name: str = Field(min_length=1, max_length=180)
    pages: list[int] = Field(min_length=1, max_length=50)


class ContentImportDraftSegmentUpdate(BaseModel):
    text: str = Field(default="", max_length=500_000)
    review_status: Literal["needs_review", "reviewed", "excluded"]
    expected_revision: int = Field(ge=1)


class AudioTranscriptCue(BaseModel):
    cue_id: str | None = Field(default=None, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)


class ContentImportAudioReviewUpdate(BaseModel):
    stored_name: str = Field(min_length=1, max_length=180)
    transcript: str = Field(default="", max_length=500_000)
    cues: list[AudioTranscriptCue] = Field(default_factory=list, max_length=5000)
    duration_seconds: float | None = Field(default=None, ge=0, le=86_400)
    review_status: Literal["needs_review", "reviewed"]
    expected_revision: int = Field(ge=0)


class ContentImportBatchDelete(BaseModel):
    import_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False


class CodexLoginStart(BaseModel):
    login_type: Literal["chatgpt", "chatgptDeviceCode", "apiKey"]
    api_key: str | None = Field(default=None, min_length=1, max_length=1000)


class AgentResultImport(BaseModel):
    result: dict[str, Any]
    usage: dict[str, Any] = Field(default_factory=dict)
    agent_provider: str | None = Field(default=None, max_length=100)
    agent_version: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    model_display_name: str | None = Field(default=None, max_length=200)
    agent_session_id: str | None = Field(default=None, max_length=300)
