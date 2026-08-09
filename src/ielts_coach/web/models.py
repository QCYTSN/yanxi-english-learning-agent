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
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    model_provider_id: str | None = Field(default=None, max_length=120)
    source_context: dict[str, Any] = Field(default_factory=dict)


class StudyThreadUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class LearnerMemoryCreate(BaseModel):
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    memory_type: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    scope: str = Field(default="teaching_style", min_length=1, max_length=80)
    source_thread_id: str | None = Field(default=None, max_length=120)
    source_session_id: str | None = Field(default=None, max_length=120)
    memory_key: str | None = Field(default=None, max_length=160)
    expires_at: str | None = Field(default=None, max_length=80)
    supersedes_memory_id: str | None = Field(default=None, max_length=120)
    conflicts_with: list[str] = Field(default_factory=list, max_length=20)


class LearnerMemoryUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=1, max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "dismissed"] | None = None
    scope: str | None = Field(default=None, min_length=1, max_length=80)
    memory_key: str | None = Field(default=None, min_length=1, max_length=160)
    expires_at: str | None = Field(default=None, max_length=80)
    clear_expiry: bool = False
    expected_revision: int | None = Field(default=None, ge=1)
    change_reason: str = Field(default="learner_update", min_length=1, max_length=120)


class LearnerMemoryConflictDecision(BaseModel):
    resolution: Literal["keep_left", "keep_right", "keep_both", "dismiss_both"]
    rationale: str | None = Field(default=None, max_length=1000)


class LearningObjectiveCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    dimension_id: str = Field(min_length=1, max_length=120)
    skill_id: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["planned", "active", "achieved", "paused", "archived"] = "active"
    priority: int = Field(default=50, ge=0, le=100)
    target_value: float | None = Field(default=None, ge=0, le=1)
    target_label: str | None = Field(default=None, max_length=120)
    due_at: str | None = Field(default=None, max_length=80)
    source_type: str = Field(default="learner", min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningObjectiveUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["planned", "active", "achieved", "paused", "archived"] | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    target_value: float | None = Field(default=None, ge=0, le=1)
    target_label: str | None = Field(default=None, max_length=120)
    due_at: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class LearningActivityCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    dimension_id: str | None = Field(default=None, max_length=120)
    objective_id: str | None = Field(default=None, max_length=120)
    source_type: str = Field(default="runtime", min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=240)
    session_id: str | None = Field(default=None, max_length=120)
    thread_id: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["planned", "in_progress", "completed", "cancelled"] = "planned"


class LearningActivityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = None
    payload: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class MasteryEvidenceCreate(BaseModel):
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    skill_id: str = Field(min_length=1, max_length=160)
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_kind: Literal[
        "attempt", "assessment", "review", "tutor_observation", "self_report"
    ]
    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=240)
    objective_id: str | None = Field(default=None, max_length=120)
    activity_id: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=120)
    thread_id: str | None = Field(default=None, max_length=120)
    rationale: str | None = Field(default=None, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = Field(default=None, max_length=80)
    schedule_review: bool = True


class LearningReviewComplete(BaseModel):
    score: float = Field(ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    rationale: str | None = Field(default=None, max_length=2000)
    continue_review: bool = True


class LearningReviewStatusUpdate(BaseModel):
    status: Literal["pending", "in_progress", "dismissed"]


class TeachingCycleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    track_id: str = Field(
        default="ielts-academic",
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    phase: Literal[
        "diagnose",
        "teach",
        "guided_practice",
        "independent_practice",
        "assess",
        "review",
        "consolidate",
    ] = "diagnose"
    dimension_id: str | None = Field(default=None, max_length=120)
    skill_id: str | None = Field(default=None, max_length=160)
    objective_id: str | None = Field(default=None, max_length=120)
    activity_id: str | None = Field(default=None, max_length=120)
    thread_id: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=120)
    context: dict[str, Any] = Field(default_factory=dict)


class TeachingCycleTransition(BaseModel):
    to_phase: Literal[
        "diagnose",
        "teach",
        "guided_practice",
        "independent_practice",
        "assess",
        "review",
        "consolidate",
    ]
    expected_revision: int = Field(ge=0)
    reason_code: str = Field(default="learner_transition", min_length=1, max_length=120)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeachingCycleStatusUpdate(BaseModel):
    status: Literal["active", "paused", "completed", "cancelled"]
    expected_revision: int = Field(ge=0)
    reason_code: str | None = Field(default=None, max_length=120)


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
