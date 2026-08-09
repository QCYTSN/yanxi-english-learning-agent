from __future__ import annotations

from typing import Any


class CoachError(ValueError):
    """Backward-compatible domain error with a stable API code."""

    code = "COACH_ERROR"
    recoverable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class SessionNotFoundError(CoachError):
    code = "SESSION_NOT_FOUND"


class SessionRevisionConflictError(CoachError):
    code = "SESSION_REVISION_CONFLICT"
    recoverable = True


class LearningRevisionConflictError(CoachError):
    code = "LEARNING_REVISION_CONFLICT"
    recoverable = True


class InvalidTeachingTransitionError(CoachError):
    code = "INVALID_TEACHING_TRANSITION"
    recoverable = True


class SessionMirrorConflictError(CoachError):
    code = "SESSION_MIRROR_CONFLICT"
    recoverable = True


class InvalidSessionTransitionError(CoachError):
    code = "INVALID_SESSION_TRANSITION"
    recoverable = True


class AnswerRevealLockedError(CoachError):
    code = "ANSWER_REVEAL_LOCKED"


class OutputContractInvalidError(CoachError):
    code = "OUTPUT_CONTRACT_INVALID"
    recoverable = True


class RubricUnavailableError(CoachError):
    code = "RUBRIC_UNAVAILABLE"
    recoverable = True


class PrivateProcessingBlockedError(CoachError):
    code = "PRIVATE_PROCESSING_BLOCKED"
    recoverable = True


class MediaError(CoachError):
    code = "MEDIA_UNSUPPORTED"
    recoverable = True


class MediaNotFoundError(MediaError):
    code = "MEDIA_NOT_FOUND"


class AgentError(CoachError):
    code = "AGENT_UNAVAILABLE"
    recoverable = True


class AgentCapabilityMissingError(AgentError):
    code = "AGENT_CAPABILITY_MISSING"


class AgentRunCancelledError(AgentError):
    code = "AGENT_RUN_CANCELLED"
