from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..agent_contracts import CONTRACT_SKILLS, persist_agent_contract
from ..agent_gateway import adapter_descriptors, adapter_diagnostics, get_adapter
from ..agent_jobs import AgentJobManager
from ..assessment_builder import assemble_assessment_pack
from ..assessment_runtime import (
    bind_speaking_result,
    create_speaking_handoff as create_assessment_speaking_handoff,
    get_assessment_run,
    list_assessment_runs,
    pause_assessment_run,
    record_writing_score,
    resume_assessment_run,
    save_navigation,
    save_response,
    start_assessment_run,
    start_audio_playback,
    submit_assessment_run,
    update_audio_playback,
)
from ..allocation import recommend_allocation
from ..backups import create_backup, list_backups, restore_backup, verify_backup
from ..config import load_profile
from ..conformance import standard_profile
from ..content_imports import create_import, imports as list_content_imports, process_import
from ..content_inventory import build_content_readiness, content_requirements
from ..content_reviews import (
    get_target_review,
    get_target_review_statuses,
    list_content_reviews,
    list_review_queue,
    record_content_review,
)
from ..errors import CoachError, PrivateProcessingBlockedError, SessionNotFoundError
from ..diagnostics import (
    attach_diagnostic_session,
    cancel_diagnostic,
    complete_diagnostic,
    diagnostic_status,
    start_diagnostic,
)
from ..health import audit_data_home
from ..locking import runtime_lock
from ..media import import_audio_bytes, import_image_bytes, resolve_media_file
from ..listening_corpus import (
    browse_listening_items,
    listening_categories,
    listening_item,
)
from ..onboarding import complete_onboarding, onboarding_status, update_profile
from ..paths import resolve_home
from ..privacy import check_processing_permission
from ..performance import RequestPerformanceMonitor, database_performance_status
from ..profiles import build_learning_profile
from ..progress_dashboard import build_progress_dashboard
from ..question_bank import search_questions, show_question, show_reading_set
from ..reports import build_summary, build_trend_report
from ..rubrics import list_rubrics
from ..session_manager import (
    finish_session,
    show_session,
    start_session,
    transition_session,
)
from ..storage import (
    append_agent_run_event,
    create_agent_run,
    db_path,
    get_agent_run,
    get_idempotency_record,
    get_study_draft,
    list_agent_run_events,
    list_agent_runs,
    list_coaching_artifacts,
    get_assessment_pack,
    list_error_profile,
    list_assessment_packs,
    list_media_assets,
    list_sessions,
    latest_active_session,
    save_study_draft,
    save_idempotency_record,
    telemetry_summary,
    update_agent_run,
)
from ..study_context import build_study_context
from ..study_runtime import (
    apply_reading_review,
    apply_writing_review,
    record_reading_hint,
    submit_listening_attempt,
    submit_reading_answers,
    submit_writing_version,
)
from ..speaking_handoff import create_speaking_handoff, speaking_questions
from ..speaking_io import import_speaking_report_data
from ..story_bank import list_stories, save_story
from .auth import AuthState, COOKIE_NAME, require_session
from .models import (
    AgentResultImport,
    AgentRunCreate,
    AssessmentPackCreate,
    AssessmentNavigationSave,
    AssessmentResponseSave,
    AssessmentRunCreate,
    AudioPlaybackUpdate,
    AuthExchange,
    BackupRestore,
    ContentReviewCreate,
    DiagnosticAttach,
    DiagnosticStart,
    DraftSave,
    ListeningAttemptSubmit,
    ReadingAnswersSubmit,
    ReadingHintSubmit,
    ProfileUpdate,
    SessionCreate,
    SessionTransition,
    SpeakingHandoffCreate,
    SpeakingReportImport,
    StoryCreate,
    WritingVersionSubmit,
    WritingAssessmentScore,
)


TERMINAL_RUN_STATUSES = {
    "persisted",
    "test_passed",
    "cancelled",
    "failed",
    "invalid_output",
    "awaiting_import",
}


class LoopbackSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, allowed_origin: str, test_mode: bool = False) -> None:
        super().__init__(app)
        self.allowed_origin = allowed_origin.rstrip("/")
        self.test_mode = test_mode

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:16]
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        allowed_hosts = {"127.0.0.1"} | ({"testserver"} if self.test_mode else set())
        if host not in allowed_hosts:
            response = _error_response(400, "INVALID_HOST", "Only loopback access is allowed.")
        else:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != self.allowed_origin:
                response = _error_response(403, "INVALID_ORIGIN", "The request origin is not allowed.")
            elif request.method in {"POST", "PUT", "PATCH", "DELETE"} and not origin and not self.test_mode:
                response = _error_response(403, "ORIGIN_REQUIRED", "An Origin header is required.")
            else:
                response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            route = request.scope.get("route")
            request.app.state.performance.record(
                str(getattr(route, "path", request.url.path)),
                request.method,
                response.status_code,
                duration_ms,
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def _error_response(status: int, code: str, message: str, **details: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "recoverable": status < 500,
                "details": details,
            }
        },
    )


def _session_or_404(home: Path, session_id: str) -> dict[str, Any]:
    session = show_session(home, session_id)
    if not session:
        raise SessionNotFoundError(f"Unknown Session: {session_id}")
    return session


def _public_media(asset: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in asset.items() if key != "local_path"}
    metadata = dict(public.get("metadata") or {})
    # Listening transcripts and timestamps are answer evidence. They are only
    # revealed through a submitted AssessmentRun, never through media listing.
    metadata.pop("transcript", None)
    metadata.pop("timestamps", None)
    public["metadata"] = metadata
    return public


def _agent_media_refs(
    home: Path,
    session_id: str,
    *,
    adapter_id: str,
    image_input: bool,
    audio_input: bool,
) -> list[dict[str, Any]]:
    refs = []
    for asset in list_media_assets(
        home,
        limit=20,
        owner_type="session",
        owner_id=session_id,
    ):
        supported = (
            asset["media_type"] == "image" and image_input
        ) or (
            asset["media_type"] == "audio" and audio_input
        )
        delivery = (
            "adapter_input"
            if supported
            else "manual_attachment_required"
            if adapter_id == "manual"
            else "unsupported_by_adapter"
        )
        refs.append(
            {
                "media_id": asset["media_id"],
                "media_type": asset["media_type"],
                "mime_type": asset["mime_type"],
                "content_hash": asset["content_hash"],
                "width": asset.get("width"),
                "height": asset.get("height"),
                "alt_text": asset.get("alt_text"),
                "privacy_status": asset["privacy_status"],
                "delivery": delivery,
                "available_to_agent": supported,
            }
        )
    return refs


def _idempotency_key(value: str | None) -> str:
    if not value or len(value) < 8 or len(value) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key must contain 8-200 characters")
    return value


def create_app(
    *,
    home: Path | None = None,
    auth: AuthState | None = None,
    allowed_origin: str = "http://127.0.0.1",
    static_dir: Path | None = None,
    test_mode: bool = False,
    control_token: str | None = None,
) -> FastAPI:
    target = resolve_home(home)
    agent_jobs = AgentJobManager(target)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        agent_jobs.recover()
        try:
            yield
        finally:
            agent_jobs.shutdown()

    app = FastAPI(
        title="IELTS AI Coach Local UI",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.home = target
    app.state.auth = auth or AuthState.create()
    app.state.control_token = control_token
    app.state.server = None
    app.state.agent_jobs = agent_jobs
    app.state.performance = RequestPerformanceMonitor()
    app.add_middleware(
        LoopbackSecurityMiddleware, allowed_origin=allowed_origin, test_mode=test_mode
    )

    @app.exception_handler(CoachError)
    async def coach_error_handler(_: Request, exc: CoachError) -> JSONResponse:
        status = 409 if exc.code == "SESSION_REVISION_CONFLICT" else 404 if exc.code.endswith("NOT_FOUND") else 422
        return _error_response(status, exc.code, str(exc), **exc.details)

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_: Request, exc: PermissionError) -> JSONResponse:
        return _error_response(403, "PRIVATE_PROCESSING_BLOCKED", str(exc))

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return _error_response(422, "VALIDATION_ERROR", str(exc))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "app": "ielts-ai-coach", "version": __version__}

    def require_control(supplied: str | None) -> None:
        expected = app.state.control_token
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=404, detail="Not found")

    @app.get("/api/internal/launch", include_in_schema=False)
    def internal_launch(
        request: Request,
        supplied: str | None = Header(default=None, alias="X-IELTS-Control-Token"),
    ) -> dict[str, str]:
        require_control(supplied)
        return {
            "launch_token": request.app.state.auth.issue_launch_token(),
            "origin": allowed_origin.rstrip("/"),
        }

    @app.get("/api/internal/stop", include_in_schema=False)
    def internal_stop(
        request: Request,
        supplied: str | None = Header(default=None, alias="X-IELTS-Control-Token"),
    ) -> dict[str, bool]:
        require_control(supplied)
        server = request.app.state.server
        if server is not None:
            threading.Timer(0.1, lambda: setattr(server, "should_exit", True)).start()
        return {"stopping": server is not None}

    @app.post("/api/auth/exchange")
    def exchange(payload: AuthExchange, response: Response, request: Request) -> dict[str, Any]:
        session = request.app.state.auth.exchange(payload.token)
        response.set_cookie(
            COOKIE_NAME,
            session,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return {"authenticated": True}

    @app.get("/api/v1/bootstrap", dependencies=[Depends(require_session)])
    def bootstrap() -> dict[str, Any]:
        profile_path = target / "config" / "profile.yaml"
        settings_path = target / "config" / "settings.yaml"
        if not profile_path.exists() or not settings_path.exists() or not db_path(target).exists():
            return {
                "api_version": 1,
                "core_version": __version__,
                "setup_required": True,
                "onboarding": None,
                "profile": None,
                "active_session": None,
                "health": {"database": False, "configuration": False},
                "agents": adapter_descriptors(),
                "storage": {
                    "data_home": str(target),
                    "database_path": str(db_path(target)),
                    "backups_path": str(target / "backups"),
                },
            }
        profile = load_profile(target)
        active_row = latest_active_session(target)
        active = dict(active_row) if active_row else None
        return {
            "api_version": 1,
            "core_version": __version__,
            "setup_required": False,
            "onboarding": onboarding_status(target),
            "profile": {
                "exam_type": profile["exam"]["type"],
                "test_date": profile["exam"].get("test_date"),
                "target": profile["target"],
                "minimum_required": profile.get("minimum_required", {}),
                "current": profile.get("current", {}),
                "preferences": profile.get("preferences", {}),
                "privacy": profile.get("privacy", {}),
            },
            "active_session": active,
            "health": {"database": True, "configuration": True},
            "agents": adapter_descriptors(),
            "storage": {
                "data_home": str(target),
                "database_path": str(db_path(target)),
                "backups_path": str(target / "backups"),
            },
        }

    @app.get("/api/v1/today", dependencies=[Depends(require_session)])
    def today() -> dict[str, Any]:
        return build_study_context(target)

    @app.get("/api/v1/profile", dependencies=[Depends(require_session)])
    def profile_endpoint() -> dict[str, Any]:
        return {
            "profile": load_profile(target),
            "onboarding": onboarding_status(target),
        }

    @app.put("/api/v1/profile", dependencies=[Depends(require_session)])
    def update_profile_endpoint(payload: ProfileUpdate) -> dict[str, Any]:
        if payload.complete_onboarding:
            complete_onboarding(target, payload.updates)
            return {
                "profile": load_profile(target),
                "onboarding": onboarding_status(target),
            }
        return update_profile(target, payload.updates)

    @app.get("/api/v1/system/health", dependencies=[Depends(require_session)])
    def system_health_endpoint() -> dict[str, Any]:
        return audit_data_home(target)

    @app.get("/api/v1/system/performance", dependencies=[Depends(require_session)])
    def system_performance_endpoint() -> dict[str, Any]:
        return {
            "requests": app.state.performance.summary(),
            "database": database_performance_status(target),
            "architecture": {
                "api": "FastAPI local process",
                "runtime": "Python",
                "frontend": "React + TypeScript",
                "heavy_jobs": "bounded background workers",
            },
        }

    @app.get("/api/v1/agents/diagnostics", dependencies=[Depends(require_session)])
    def agent_diagnostics_endpoint() -> list[dict[str, object]]:
        return adapter_diagnostics()

    @app.get("/api/v1/rubrics", dependencies=[Depends(require_session)])
    def rubrics_endpoint() -> list[dict[str, Any]]:
        return list_rubrics(target)

    @app.get("/api/v1/telemetry/summary", dependencies=[Depends(require_session)])
    def telemetry_endpoint(days: int = Query(30, ge=1, le=3650)) -> list[dict[str, Any]]:
        return [dict(row) for row in telemetry_summary(target, days=days)]

    @app.get("/api/v1/diagnostics/current", dependencies=[Depends(require_session)])
    def diagnostic_current_endpoint() -> dict[str, Any]:
        return diagnostic_status(target)

    @app.post("/api/v1/diagnostics", dependencies=[Depends(require_session)])
    def diagnostic_start_endpoint(payload: DiagnosticStart) -> dict[str, Any]:
        return start_diagnostic(target, payload.mode)

    @app.post(
        "/api/v1/diagnostics/{diagnostic_id}/sessions",
        dependencies=[Depends(require_session)],
    )
    def diagnostic_attach_endpoint(
        diagnostic_id: str,
        payload: DiagnosticAttach,
    ) -> dict[str, Any]:
        return attach_diagnostic_session(target, diagnostic_id, payload.session_id)

    @app.post(
        "/api/v1/diagnostics/{diagnostic_id}/complete",
        dependencies=[Depends(require_session)],
    )
    def diagnostic_complete_endpoint(diagnostic_id: str) -> dict[str, Any]:
        return complete_diagnostic(target, diagnostic_id)

    @app.post(
        "/api/v1/diagnostics/{diagnostic_id}/cancel",
        dependencies=[Depends(require_session)],
    )
    def diagnostic_cancel_endpoint(diagnostic_id: str) -> dict[str, Any]:
        return cancel_diagnostic(target, diagnostic_id)

    @app.get("/api/v1/standards/ielts-academic", dependencies=[Depends(require_session)])
    def ielts_standard_endpoint() -> dict[str, Any]:
        return standard_profile()

    @app.get("/api/v1/content/requirements", dependencies=[Depends(require_session)])
    def content_requirements_endpoint() -> dict[str, Any]:
        return content_requirements()

    @app.get("/api/v1/content/readiness", dependencies=[Depends(require_session)])
    def content_readiness_endpoint() -> dict[str, Any]:
        return build_content_readiness(target)

    @app.get("/api/v1/backups", dependencies=[Depends(require_session)])
    def backups_endpoint() -> list[dict[str, Any]]:
        return list_backups(target)

    @app.post("/api/v1/backups", dependencies=[Depends(require_session)])
    def create_backup_endpoint() -> dict[str, Any]:
        return create_backup(target, kind="manual-ui")

    @app.post("/api/v1/backups/{backup_id}/verify", dependencies=[Depends(require_session)])
    def verify_backup_endpoint(backup_id: str) -> dict[str, Any]:
        return verify_backup(target, backup_id, allow_external_path=False)

    @app.post("/api/v1/backups/{backup_id}/restore", dependencies=[Depends(require_session)])
    def restore_backup_endpoint(backup_id: str, payload: BackupRestore) -> dict[str, Any]:
        return restore_backup(
            target,
            backup_id,
            confirmed=payload.confirmed,
            allow_external_path=False,
        )

    @app.get("/api/v1/content/imports", dependencies=[Depends(require_session)])
    def content_imports_endpoint(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return list_content_imports(target, limit=limit)

    @app.post("/api/v1/content/imports", dependencies=[Depends(require_session)])
    async def create_content_import_endpoint(
        files: list[UploadFile] = File(...),
        title: str = Form(..., min_length=1, max_length=200),
        source_type: str = Form(...),
        authenticity: str = Form(default="unreviewed", max_length=100),
        rights_status: str = Form(default="local_private"),
    ) -> dict[str, Any]:
        payloads: list[tuple[str, bytes, str | None]] = []
        for item in files:
            payloads.append((item.filename or "unnamed", await item.read(), item.content_type))
            await item.close()
        return create_import(
            target,
            title=title,
            source_type=source_type,
            authenticity=authenticity,
            rights_status=rights_status,
            files=payloads,
        )

    @app.post("/api/v1/content/imports/{import_id}/process", dependencies=[Depends(require_session)])
    def process_content_import_endpoint(import_id: str) -> dict[str, Any]:
        return process_import(target, import_id)

    @app.get("/api/v1/content-reviews", dependencies=[Depends(require_session)])
    def content_reviews_endpoint(
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_content_reviews(
            target,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
        )

    @app.get("/api/v1/content-reviews/queue", dependencies=[Depends(require_session)])
    def content_review_queue_endpoint(
        target_type: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_review_queue(target, target_type=target_type, limit=limit)

    @app.get(
        "/api/v1/content-reviews/targets/{target_type}/{target_id}",
        dependencies=[Depends(require_session)],
    )
    def content_review_target_endpoint(target_type: str, target_id: str) -> dict[str, Any]:
        return get_target_review(target, target_type, target_id)

    @app.post(
        "/api/v1/content-reviews/targets/{target_type}/{target_id}",
        dependencies=[Depends(require_session)],
    )
    def create_content_review_endpoint(
        target_type: str,
        target_id: str,
        payload: ContentReviewCreate,
    ) -> dict[str, Any]:
        return record_content_review(
            target,
            target_type=target_type,
            target_id=target_id,
            reviewer=payload.reviewer,
            decision=payload.decision,
            checklist=payload.checklist,
            notes=payload.notes,
        )

    @app.get("/api/v1/assessment-packs", dependencies=[Depends(require_session)])
    def assessment_packs_endpoint(
        module: str | None = None,
        practice_mode: str | None = None,
        conformance_status: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        items = list_assessment_packs(
            target,
            module=module,
            practice_mode=practice_mode,
            conformance_status=conformance_status,
            limit=limit,
            offset=offset,
        )
        statuses = get_target_review_statuses(
            target,
            "assessment_pack",
            [str(item["pack_id"]) for item in items],
        )
        for item in items:
            item["local_review_status"] = statuses.get(
                str(item["pack_id"]), "unreviewed"
            )
        return items

    @app.post("/api/v1/assessment-packs", dependencies=[Depends(require_session)])
    def create_assessment_pack_endpoint(payload: AssessmentPackCreate) -> dict[str, Any]:
        return assemble_assessment_pack(
            target,
            module=payload.module,
            title=payload.title,
            question_ids=payload.question_ids,
        )

    @app.get("/api/v1/assessment-packs/{pack_id}", dependencies=[Depends(require_session)])
    def assessment_pack_endpoint(pack_id: str) -> dict[str, Any]:
        item = get_assessment_pack(target, pack_id)
        if not item:
            raise HTTPException(status_code=404, detail="Assessment pack not found")
        item["local_review_status"] = get_target_review(
            target,
            "assessment_pack",
            pack_id,
            include_material=False,
        )["local_review_status"]
        return item

    @app.get("/api/v1/assessment-runs", dependencies=[Depends(require_session)])
    def assessment_runs_endpoint(
        status: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_assessment_runs(target, status=status, limit=limit)

    @app.post("/api/v1/assessment-runs", dependencies=[Depends(require_session)])
    def assessment_run_start_endpoint(
        payload: AssessmentRunCreate,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return start_assessment_run(
            target,
            payload.pack_id,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.get(
        "/api/v1/assessment-runs/{run_id}",
        dependencies=[Depends(require_session)],
    )
    def assessment_run_endpoint(run_id: str) -> dict[str, Any]:
        return get_assessment_run(target, run_id)

    @app.put(
        "/api/v1/assessment-runs/{run_id}/responses/{question_id}",
        dependencies=[Depends(require_session)],
    )
    def assessment_response_endpoint(
        run_id: str,
        question_id: str,
        payload: AssessmentResponseSave,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return save_response(
            target,
            run_id,
            question_id,
            payload.response,
            section_key=payload.section_key,
            expected_revision=payload.expected_revision,
            flagged=payload.flagged,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.put(
        "/api/v1/assessment-runs/{run_id}/navigation",
        dependencies=[Depends(require_session)],
    )
    def assessment_navigation_endpoint(
        run_id: str,
        payload: AssessmentNavigationSave,
    ) -> dict[str, Any]:
        return save_navigation(
            target,
            run_id,
            payload.navigation,
            expected_revision=payload.expected_revision,
        )

    @app.post(
        "/api/v1/assessment-runs/{run_id}/pause",
        dependencies=[Depends(require_session)],
    )
    def assessment_pause_endpoint(run_id: str) -> dict[str, Any]:
        return pause_assessment_run(target, run_id)

    @app.post(
        "/api/v1/assessment-runs/{run_id}/resume",
        dependencies=[Depends(require_session)],
    )
    def assessment_resume_endpoint(run_id: str) -> dict[str, Any]:
        return resume_assessment_run(target, run_id)

    @app.post(
        "/api/v1/assessment-runs/{run_id}/submit",
        dependencies=[Depends(require_session)],
    )
    def assessment_submit_endpoint(
        run_id: str,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return submit_assessment_run(
            target,
            run_id,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.post(
        "/api/v1/assessment-runs/{run_id}/audio/{media_id}/start",
        dependencies=[Depends(require_session)],
    )
    def assessment_audio_start_endpoint(run_id: str, media_id: str) -> dict[str, Any]:
        return start_audio_playback(target, run_id, media_id)

    @app.put(
        "/api/v1/assessment-runs/{run_id}/audio/{media_id}",
        dependencies=[Depends(require_session)],
    )
    def assessment_audio_update_endpoint(
        run_id: str,
        media_id: str,
        payload: AudioPlaybackUpdate,
    ) -> dict[str, Any]:
        return update_audio_playback(
            target,
            run_id,
            media_id,
            position_seconds=payload.position_seconds,
            completed=payload.completed,
        )

    @app.get(
        "/api/v1/assessment-runs/{run_id}/audio/{media_id}/content",
        dependencies=[Depends(require_session)],
    )
    def assessment_audio_content_endpoint(run_id: str, media_id: str) -> FileResponse:
        run = get_assessment_run(target, run_id)
        state = run.get("media_state", {}).get(media_id) or {}
        if int(state.get("play_count", 0)) != 1:
            raise ValueError("Audio playback must be authorised by this AssessmentRun")
        asset, path = resolve_media_file(target, media_id)
        if asset["media_type"] != "audio":
            raise ValueError("Requested media is not audio")
        return FileResponse(path, media_type=asset["mime_type"], filename=path.name)

    @app.post(
        "/api/v1/assessment-runs/{run_id}/writing-score",
        dependencies=[Depends(require_session)],
    )
    def assessment_writing_score_endpoint(
        run_id: str,
        payload: WritingAssessmentScore,
    ) -> dict[str, Any]:
        return record_writing_score(
            target,
            run_id,
            task1=payload.task1,
            task2=payload.task2,
        )

    @app.post(
        "/api/v1/assessment-runs/{run_id}/speaking-handoff",
        dependencies=[Depends(require_session)],
    )
    def assessment_speaking_handoff_endpoint(
        run_id: str,
        payload: SpeakingHandoffCreate,
    ) -> dict[str, Any]:
        return create_assessment_speaking_handoff(
            target,
            run_id,
            provider=payload.provider,
        )

    @app.post(
        "/api/v1/assessment-runs/{run_id}/speaking-report",
        dependencies=[Depends(require_session)],
    )
    def assessment_speaking_report_endpoint(
        run_id: str,
        payload: SpeakingReportImport,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        run = get_assessment_run(target, run_id)
        if run["module"] != "speaking":
            raise ValueError("Speaking report requires a Speaking AssessmentRun")
        raw_report = dict(payload.report or {})
        if payload.transcript:
            raw_report.setdefault("transcript", payload.transcript)
        raw_report.setdefault("provider", payload.provider)
        raw_report.setdefault("mode", payload.mode)
        imported = import_speaking_report_data(
            target,
            raw_report,
            session_id=str(run["session_id"]),
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )
        return bind_speaking_result(target, run_id, imported)

    @app.get("/api/v1/sessions", dependencies=[Depends(require_session)])
    def sessions(
        module: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in list_sessions(
                target, module=module, limit=limit, offset=offset
            )
        ]

    @app.post("/api/v1/sessions", dependencies=[Depends(require_session)])
    def create_session_endpoint(
        payload: SessionCreate,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        path = start_session(
            target,
            payload.module,
            question_id=payload.question_id,
            source_id=payload.source_id,
            passage_id=payload.passage_id,
            assessment_pack_id=payload.assessment_pack_id,
            practice_mode=payload.practice_mode,
            mode=payload.mode,
            time_limit_minutes=payload.time_limit_minutes,
            idempotency_key=_idempotency_key(idempotency),
        )
        return _session_or_404(target, path.stem)

    @app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_session)])
    def get_session_endpoint(session_id: str) -> dict[str, Any]:
        return _session_or_404(target, session_id)

    @app.post("/api/v1/sessions/{session_id}/transition", dependencies=[Depends(require_session)])
    def transition_endpoint(session_id: str, payload: SessionTransition) -> dict[str, Any]:
        session = _session_or_404(target, session_id)
        path = target / "sessions" / session["module"] / f"{session_id}.md"
        return transition_session(target, path, payload.status)

    @app.post("/api/v1/sessions/{session_id}/finish", dependencies=[Depends(require_session)])
    def finish_endpoint(session_id: str) -> dict[str, Any]:
        session = _session_or_404(target, session_id)
        path = target / "sessions" / session["module"] / f"{session_id}.md"
        return finish_session(target, path)

    @app.get("/api/v1/sessions/{session_id}/draft/{draft_kind}", dependencies=[Depends(require_session)])
    def get_draft_endpoint(session_id: str, draft_kind: str) -> dict[str, Any]:
        _session_or_404(target, session_id)
        return get_study_draft(target, session_id, draft_kind) or {
            "session_id": session_id,
            "draft_kind": draft_kind,
            "revision": 0,
            "payload": {},
            "updated_at": None,
        }

    @app.put("/api/v1/sessions/{session_id}/draft", dependencies=[Depends(require_session)])
    def save_draft_endpoint(session_id: str, payload: DraftSave) -> dict[str, Any]:
        _session_or_404(target, session_id)
        with runtime_lock(target, f"draft:{session_id}:{payload.draft_kind}"):
            return save_study_draft(
                target,
                session_id,
                payload.draft_kind,
                payload.payload,
                expected_revision=payload.expected_revision,
            )

    @app.post("/api/v1/writing/{session_id}/versions", dependencies=[Depends(require_session)])
    def writing_version_endpoint(
        session_id: str,
        payload: WritingVersionSubmit,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return submit_writing_version(
            target,
            session_id,
            label=payload.label,
            content=payload.content,
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.post("/api/v1/reading/{session_id}/hints", dependencies=[Depends(require_session)])
    def reading_hint_endpoint(
        session_id: str,
        payload: ReadingHintSubmit,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return record_reading_hint(
            target,
            session_id,
            level=payload.level,
            question_id=payload.question_id,
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.post("/api/v1/reading/{session_id}/answers", dependencies=[Depends(require_session)])
    def reading_answers_endpoint(
        session_id: str,
        payload: ReadingAnswersSubmit,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return submit_reading_answers(
            target,
            session_id,
            payload.answers,
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.get("/api/v1/listening/categories", dependencies=[Depends(require_session)])
    def listening_category_endpoint() -> list[dict[str, Any]]:
        return listening_categories(target)

    @app.get("/api/v1/listening/items", dependencies=[Depends(require_session)])
    def listening_items_endpoint(
        category: str | None = None,
        query: str | None = None,
        due_only: bool = False,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return browse_listening_items(
            target,
            category=category,
            query=query,
            due_only=due_only,
            limit=limit,
        )

    @app.post(
        "/api/v1/listening/{session_id}/attempts",
        dependencies=[Depends(require_session)],
    )
    def listening_attempt_endpoint(
        session_id: str,
        payload: ListeningAttemptSubmit,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        session = submit_listening_attempt(
            target,
            session_id,
            item_id=payload.item_id,
            user_answer=payload.user_answer,
            error_tags=payload.error_tags,
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )
        return {
            "session": session,
            "attempt": session.get("last_listening_result"),
            "item": listening_item(target, payload.item_id),
        }

    @app.get("/api/v1/speaking/questions", dependencies=[Depends(require_session)])
    def speaking_questions_endpoint(
        part: int | None = Query(default=None, ge=1, le=3),
        topic: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return speaking_questions(target, part=part, topic=topic, limit=limit)

    @app.post("/api/v1/speaking/handoffs", dependencies=[Depends(require_session)])
    def speaking_handoff_endpoint(
        payload: SpeakingHandoffCreate,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return create_speaking_handoff(
            target,
            mode=payload.mode,
            provider=payload.provider,
            question_ids=payload.question_ids,
            seed=payload.seed,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.post(
        "/api/v1/speaking/{session_id}/reports",
        dependencies=[Depends(require_session)],
    )
    def speaking_report_endpoint(
        session_id: str,
        payload: SpeakingReportImport,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        session = _session_or_404(target, session_id)
        if session.get("module") != "speaking":
            raise ValueError("This operation requires a Speaking Session")
        if payload.report is not None:
            report = dict(payload.report)
            report.setdefault("session_id", session_id)
            report.setdefault("mode", payload.mode)
            report.setdefault(
                "source",
                {"provider": payload.provider, "interaction_mode": "voice_or_live"},
            )
        elif payload.transcript and payload.transcript.strip():
            report = {
                "report_version": 2,
                "session_id": session_id,
                "mode": payload.mode,
                "source": {
                    "provider": payload.provider,
                    "interaction_mode": "voice_or_live",
                },
                "transcript": payload.transcript.strip(),
                "source_observations": {
                    "evidence_types": ["transcript"],
                    "transcript": payload.transcript.strip(),
                    "parts": [],
                },
                "source_model_estimate": {"criterion_scores": []},
                "local_evaluation": {"status": "pending", "criterion_scores": []},
            }
        else:
            raise ValueError("Provide a transcript or a structured Speaking report")
        return import_speaking_report_data(
            target,
            report,
            session_id=session_id,
            expected_revision=payload.expected_revision,
            idempotency_key=_idempotency_key(idempotency),
        )

    @app.get("/api/v1/speaking/stories", dependencies=[Depends(require_session)])
    def speaking_stories_endpoint() -> list[dict[str, Any]]:
        return list_stories(target)

    @app.post("/api/v1/speaking/stories", dependencies=[Depends(require_session)])
    def create_speaking_story_endpoint(payload: StoryCreate) -> dict[str, Any]:
        return save_story(target, payload.model_dump())

    @app.get("/api/v1/questions", dependencies=[Depends(require_session)])
    def questions(
        module: str | None = None,
        task: str | None = None,
        question_type: str | None = None,
        topic: str | None = None,
        passage_id: str | None = None,
        query: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        items = search_questions(
            target,
            module=module,
            task=task,
            question_type=question_type,
            topic=topic,
            passage_id=passage_id,
            query=query,
            limit=limit,
            offset=offset,
        )
        statuses = get_target_review_statuses(
            target,
            "question",
            [str(item["question_id"]) for item in items],
        )
        for item in items:
            item["local_review_status"] = statuses.get(
                str(item["question_id"]), "unreviewed"
            )
        return items

    @app.get("/api/v1/questions/{question_id}", dependencies=[Depends(require_session)])
    def question(question_id: str) -> dict[str, Any]:
        item = show_question(target, question_id, include_answer=False)
        if not item:
            raise HTTPException(status_code=404, detail="Question not found")
        return item

    @app.get("/api/v1/passages/{passage_id}", dependencies=[Depends(require_session)])
    def passage(passage_id: str) -> dict[str, Any]:
        item = show_reading_set(target, passage_id, include_answers=False)
        if not item:
            raise HTTPException(status_code=404, detail="Passage not found")
        return item

    @app.post("/api/v1/media", dependencies=[Depends(require_session)])
    async def media_upload(
        image: UploadFile = File(...),
        alt_text: str = Form("IELTS Task 1 visual"),
        owner_type: str | None = Form(None),
        owner_id: str | None = Form(None),
    ) -> dict[str, Any]:
        asset = import_image_bytes(
            target,
            await image.read(),
            alt_text=alt_text,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        return _public_media(asset)

    @app.post("/api/v1/media/audio", dependencies=[Depends(require_session)])
    async def audio_upload(
        audio: UploadFile = File(...),
        duration_seconds: float | None = Form(None),
        transcript: str | None = Form(None),
        timestamps_json: str = Form("[]"),
        owner_type: str | None = Form(None),
        owner_id: str | None = Form(None),
        privacy_status: str = Form("local_only"),
        allow_agent_processing: bool = Form(False),
    ) -> dict[str, Any]:
        try:
            timestamps = json.loads(timestamps_json)
        except json.JSONDecodeError as exc:
            raise ValueError("timestamps_json must be valid JSON") from exc
        if not isinstance(timestamps, list):
            raise ValueError("timestamps_json must contain a list")
        asset = import_audio_bytes(
            target,
            await audio.read(),
            filename=audio.filename or "listening-audio",
            mime_type=audio.content_type or "application/octet-stream",
            duration_seconds=duration_seconds,
            transcript=transcript,
            timestamps=timestamps,
            owner_type=owner_type,
            owner_id=owner_id,
            privacy_status=privacy_status,
            allow_agent_processing=allow_agent_processing,
        )
        return _public_media(asset)

    @app.get("/api/v1/media", dependencies=[Depends(require_session)])
    def media_list() -> list[dict[str, Any]]:
        return [_public_media(item) for item in list_media_assets(target)]

    @app.get("/api/v1/media/{media_id}/content", dependencies=[Depends(require_session)])
    def media_content(media_id: str) -> FileResponse:
        asset, path = resolve_media_file(target, media_id)
        if asset["media_type"] == "audio":
            raise HTTPException(
                status_code=403,
                detail="Listening audio is only available through an authorised AssessmentRun",
            )
        return FileResponse(path, media_type=asset["mime_type"], filename=path.name)

    @app.get("/api/v1/progress/summary", dependencies=[Depends(require_session)])
    def progress_summary(days: int = Query(14, ge=1, le=365)) -> dict[str, Any]:
        return {
            "summary": build_summary(target, days),
            "profile": build_learning_profile(target),
        }

    @app.get("/api/v1/progress/trends", dependencies=[Depends(require_session)])
    def progress_trends(limit: int = Query(10, ge=2, le=100)) -> dict[str, Any]:
        return {"report": build_trend_report(target, limit=limit)}

    @app.get("/api/v1/progress/errors", dependencies=[Depends(require_session)])
    def progress_errors(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return [dict(row) for row in list_error_profile(target, limit=limit)]

    @app.get("/api/v1/progress/allocation", dependencies=[Depends(require_session)])
    def progress_allocation() -> dict[str, Any]:
        result = recommend_allocation(target, persist=False)
        return {"allocation": result.allocation, "reasons": result.reasons}

    @app.get("/api/v1/progress/dashboard", dependencies=[Depends(require_session)])
    def progress_dashboard(days: int = Query(90, ge=7, le=730)) -> dict[str, Any]:
        return build_progress_dashboard(target, days=days)

    @app.get("/api/v1/coaching-artifacts", dependencies=[Depends(require_session)])
    def coaching_artifacts(
        artifact_type: str | None = None,
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_coaching_artifacts(
            target, artifact_type=artifact_type, limit=limit
        )

    @app.get("/api/v1/agents", dependencies=[Depends(require_session)])
    def agents() -> list[dict[str, Any]]:
        return adapter_descriptors()

    @app.get("/api/v1/agent-runs", dependencies=[Depends(require_session)])
    def agent_runs(
        study_session_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_agent_runs(
            target,
            study_session_id=study_session_id,
            limit=limit,
        )

    @app.post("/api/v1/agent-runs", dependencies=[Depends(require_session)])
    def agent_run_create(
        payload: AgentRunCreate,
        idempotency: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        idempotency = _idempotency_key(idempotency)
        scope = (
            f"agent-run:{payload.study_session_id}:{payload.adapter_id}:"
            f"{payload.output_contract}:{payload.action}"
        )
        replay = get_idempotency_record(target, scope, idempotency)
        if replay:
            existing = get_agent_run(target, str(replay["response"]["run_id"]))
            if existing:
                return existing
        session = _session_or_404(target, payload.study_session_id)
        adapter = get_adapter(payload.adapter_id)
        capabilities = adapter.probe()
        adapter_identity = adapter.identity()
        permission = check_processing_permission(
            target,
            remote_processing=capabilities.remote_processing,
            explicit_consent=payload.explicit_consent,
            source_type=payload.source_type or ("personal" if capabilities.remote_processing else None),
            question_id=session.get("question_id"),
        )
        if not permission["allowed"]:
            raise PrivateProcessingBlockedError(
                "Private material requires one-time consent before Agent handoff.",
                details=permission,
            )
        media_refs = _agent_media_refs(
            target,
            payload.study_session_id,
            adapter_id=payload.adapter_id,
            image_input=capabilities.image_input,
            audio_input=capabilities.audio_input,
        )
        canonical_session = dict(session)
        canonical_session["registered_media"] = media_refs
        canonical_session["media_evidence_sufficient"] = not media_refs or all(
            item["available_to_agent"] for item in media_refs
        )
        run_id = f"run_{uuid.uuid4().hex}"
        request_envelope = {
            "request_version": 1,
            "request_id": run_id,
            "study_session_id": payload.study_session_id,
            "skill": CONTRACT_SKILLS[payload.output_contract],
            "action": payload.action,
            "context_ref": f"session:{payload.study_session_id}:revision:{session.get('revision', 0)}",
            "payload_refs": [
                f"session:{payload.study_session_id}",
                *([f"question:{session['question_id']}"] if session.get("question_id") else []),
                *[f"media:{item['media_id']}" for item in media_refs],
            ],
            "output_contract": payload.output_contract,
            "privacy_decision": permission,
            "agent_identity": {
                "adapter_id": payload.adapter_id,
                "agent_provider": payload.agent_provider or adapter_identity.agent_provider,
                "agent_version": payload.agent_version or adapter_identity.agent_version,
                "model_id": payload.model_id or adapter_identity.model_id,
                "model_display_name": payload.model_display_name or adapter_identity.model_display_name,
                "agent_session_id": payload.agent_session_id,
                "launcher_kind": adapter_identity.launcher_kind,
            },
            "media_refs": media_refs,
            "canonical_session": canonical_session if payload.adapter_id != "mock" else None,
        }
        run = create_agent_run(
            target,
            {
                "run_id": run_id,
                "study_session_id": payload.study_session_id,
                "adapter_id": payload.adapter_id,
                "agent_provider": payload.agent_provider or adapter_identity.agent_provider,
                "agent_version": payload.agent_version or adapter_identity.agent_version,
                "model_id": payload.model_id or adapter_identity.model_id,
                "model_display_name": payload.model_display_name or adapter_identity.model_display_name,
                "agent_session_id": payload.agent_session_id,
                "launcher_kind": adapter_identity.launcher_kind,
                "capabilities": capabilities.__dict__,
                "calibration_status": adapter_identity.calibration_status,
                "action": payload.action,
                "output_contract": payload.output_contract,
                "base_revision": int(session.get("revision", 0)),
                "status": "queued",
                "request": request_envelope,
                "timeout_seconds": payload.timeout_seconds,
            },
        )
        append_agent_run_event(target, run_id, "status", {"stage": "queued", "label": "Preparing feedback"})
        save_idempotency_record(
            target,
            scope,
            idempotency,
            "agent_run_create",
            {"run_id": run_id},
        )
        app.state.agent_jobs.enqueue(run_id)
        return run

    @app.post("/api/v1/agent-runs/{run_id}/import", dependencies=[Depends(require_session)])
    def agent_result_import(run_id: str, payload: AgentResultImport) -> dict[str, Any]:
        run = get_agent_run(target, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        if run["adapter_id"] != "manual" or run["status"] != "awaiting_import":
            raise ValueError("This Agent run is not waiting for a manual result")
        append_agent_run_event(target, run_id, "status", {"stage": "validating", "label": "Checking feedback format"})
        update_agent_run(target, run_id, status="validating", heartbeat_at=datetime.now(timezone.utc).isoformat())
        try:
            canonical = persist_agent_contract(target, run, payload.result)
        except Exception as exc:
            update_agent_run(
                target,
                run_id,
                status="invalid_output",
                error_code="INVALID_AGENT_OUTPUT",
                recovery_action="correct_and_import",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            append_agent_run_event(
                target,
                run_id,
                "failed",
                {
                    "code": "INVALID_AGENT_OUTPUT",
                    "message": str(exc),
                    "recovery_action": "correct_and_import",
                },
            )
            raise
        update_agent_run(target, run_id, status="persisting")
        append_agent_run_event(
            target,
            run_id,
            "status",
            {"stage": "persisting", "label": "Saving authoritative result"},
        )
        identity_changes = {
            key: value
            for key, value in {
                "agent_provider": payload.agent_provider,
                "agent_version": payload.agent_version,
                "model_id": payload.model_id,
                "model_display_name": payload.model_display_name,
                "agent_session_id": payload.agent_session_id,
            }.items()
            if value is not None
        }
        updated = update_agent_run(
            target,
            run_id,
            status="persisted",
            result=payload.result,
            usage=payload.usage,
            **identity_changes,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        append_agent_run_event(
            target, run_id, "completed", {"session_id": run["study_session_id"], "revision": canonical["revision"]}
        )
        return updated

    @app.get("/api/v1/agent-runs/{run_id}", dependencies=[Depends(require_session)])
    def agent_run_get(run_id: str) -> dict[str, Any]:
        run = get_agent_run(target, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        return run

    @app.post("/api/v1/agent-runs/{run_id}/cancel", dependencies=[Depends(require_session)])
    def agent_run_cancel(run_id: str) -> dict[str, Any]:
        try:
            return app.state.agent_jobs.cancel(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/agent-runs/{run_id}/retry", dependencies=[Depends(require_session)])
    def agent_run_retry(run_id: str) -> dict[str, Any]:
        try:
            return app.state.agent_jobs.retry(run_id)
        except ValueError as exc:
            if "not found" in str(exc).lower():
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise

    @app.get("/api/v1/agent-runs/{run_id}/events", dependencies=[Depends(require_session)])
    async def agent_run_events(
        run_id: str,
        request: Request,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        if not get_agent_run(target, run_id):
            raise HTTPException(status_code=404, detail="Agent run not found")

        async def stream() -> AsyncIterator[str]:
            try:
                cursor = max(after, int(last_event_id or 0))
            except ValueError:
                cursor = after
            while True:
                if await request.is_disconnected():
                    return
                events = list_agent_run_events(target, run_id, after=cursor)
                for event in events:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                run = get_agent_run(target, run_id)
                if run and run["status"] in TERMINAL_RUN_STATUSES and not events:
                    return
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.75)

        return StreamingResponse(stream(), media_type="text/event-stream")

    selected_static = static_dir or Path(__file__).with_name("static")
    assets = selected_static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        index = selected_static / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "UI_ASSETS_MISSING", "message": "Frontend assets are not built."}},
        )

    return app
