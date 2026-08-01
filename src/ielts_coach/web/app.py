from __future__ import annotations

import asyncio
import hmac
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..agent_contracts import persist_agent_contract
from ..agent_gateway import adapter_descriptors, adapter_diagnostics
from ..agent_jobs import AgentJobManager
from ..capabilities import capability_descriptors, capability_for_contract
from ..capability_evaluation import (
    list_capability_evaluations,
    provider_reliability_report,
)
from ..assessment_builder import assemble_assessment_pack
from ..assessment_runtime import (
    create_speaking_handoff as create_assessment_speaking_handoff,
    get_assessment_run,
    list_assessment_runs,
    pause_assessment_run,
    record_writing_score,
    register_speaking_source_report,
    renew_audio_playback_lease,
    resume_assessment_run,
    save_navigation,
    save_response,
    start_assessment_run,
    start_audio_playback,
    submit_assessment_run,
    update_audio_playback,
    validate_audio_playback_lease,
)
from ..allocation import recommend_allocation
from ..backups import create_backup, list_backups, restore_backup, verify_backup
from ..config import load_profile
from ..conformance import standard_profile
from ..content_imports import (
    build_import_review_draft,
    content_storage_status,
    create_import,
    delete_imports,
    get_content_import_job,
    import_file_path,
    imports as list_content_imports,
    ocr_capability,
    prepare_import,
    process_import,
    queue_import_ocr,
    queue_import_preparation,
    read_import_review_draft,
    recover_interrupted_imports,
    run_import_ocr,
    update_import_page_plan,
    update_import_review_segment,
)
from ..content_audio import read_audio_review, update_audio_review
from ..content_inventory import build_content_readiness, content_requirements
from ..content_reviews import (
    get_target_review,
    get_target_review_statuses,
    list_content_reviews,
    list_review_queue,
    record_content_review,
)
from ..errors import CoachError, PrivateProcessingBlockedError, SessionNotFoundError
from ..execution_profiles import update_execution_profile
from ..external_agents import list_external_agent_profiles
from ..model_providers import (
    create_model_provider,
    delete_model_provider,
    list_model_providers,
    list_provider_models,
    provider_presets,
    test_model_provider,
    update_model_provider,
)
from ..ocr_runtime import (
    install_ocr_runtime,
    queue_ocr_runtime_install,
    recover_ocr_runtime_install,
)
from ..private_corpus_builder import build_private_corpus_package
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
from ..learning_orchestration import (
    bind_practice_unit,
    complete_practice_unit,
    complete_review_task,
    get_practice_unit,
    list_practice_units,
    list_review_tasks,
    materialise_today_unit,
    materialise_progress_action,
    start_review_task,
    sync_review_tasks,
)
from ..init_home import initialise_home
from ..onboarding import complete_onboarding, onboarding_status, update_profile
from ..paths import resolve_home
from ..privacy import build_privacy_receipt, check_processing_permission
from ..performance import RequestPerformanceMonitor, database_performance_status
from ..profiles import build_learning_profile
from ..progress_dashboard import (
    build_progress_dashboard,
    build_structured_weekly_report,
    list_weekly_reports,
)
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
    create_learner_memory,
    create_agent_run,
    db_path,
    get_agent_run,
    get_idempotency_record,
    get_media_asset,
    get_study_draft,
    list_agent_run_events,
    list_agent_runs,
    list_audit_events,
    list_learner_memories,
    list_coaching_artifacts,
    get_assessment_pack,
    list_error_profile,
    list_assessment_packs,
    list_media_assets,
    list_provider_attempts,
    list_sessions,
    latest_active_session,
    save_study_draft,
    record_audit_event,
    save_idempotency_record,
    delete_learner_memory,
    telemetry_summary,
    update_agent_run,
    update_learner_memory,
)
from ..study_threads import (
    add_user_message,
    create_study_thread,
    delete_study_thread,
    get_study_thread,
    list_study_threads,
    promote_study_thread,
    rename_study_thread,
    resolve_study_attachment,
    study_thread_agent_context,
    thread_media_ids,
)
from ..study_context import build_study_context
from ..tutor_orchestrator import TutorOrchestrator
from ..skill_policy import compile_skill_envelope
from ..study_runtime import (
    reconcile_session,
    record_reading_hint,
    submit_listening_attempt,
    submit_reading_answers,
    submit_writing_version,
)
from ..speaking_handoff import create_speaking_handoff, speaking_questions
from ..speaking_io import import_speaking_report_data
from ..story_bank import list_stories, save_story
from .auth import (
    AuthState,
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    require_session,
)
from .models import (
    AgentResultImport,
    AgentRunCreate,
    CodexLoginStart,
    ExecutionProfileUpdate,
    ModelProviderCreate,
    ModelProviderUpdate,
    AssessmentPackCreate,
    AssessmentNavigationSave,
    AssessmentResponseSave,
    AssessmentRunCreate,
    AudioPlaybackUpdate,
    AuthExchange,
    BackupRestore,
    ContentReviewCreate,
    ContentImportPagePlanUpdate,
    ContentImportDraftSegmentUpdate,
    ContentImportAudioReviewUpdate,
    ContentImportBatchDelete,
    ContentImportOcrRequest,
    DiagnosticAttach,
    DiagnosticStart,
    DraftSave,
    ListeningAttemptSubmit,
    LearnerMemoryCreate,
    LearnerMemoryUpdate,
    ReadingAnswersSubmit,
    ReadingHintSubmit,
    ProfileUpdate,
    SessionCreate,
    SessionTransition,
    SpeakingHandoffCreate,
    SpeakingReportImport,
    StoryCreate,
    StudyThreadCreate,
    StudyThreadUpdate,
    TodayMaterialise,
    TodayIntent,
    TutorContextRequest,
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
            elif (
                request.url.path.startswith("/api/v1/")
                and request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and not self.test_mode
                and not request.app.state.auth.valid_csrf(
                    request.cookies.get(COOKIE_NAME),
                    request.cookies.get(CSRF_COOKIE_NAME),
                    request.headers.get(CSRF_HEADER_NAME),
                )
            ):
                response = _error_response(
                    403,
                    "CSRF_TOKEN_REQUIRED",
                    "The local UI request is missing its session-bound CSRF token.",
                )
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
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
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
    session_id: str | None,
    *,
    adapter_id: str,
    image_input: bool,
    audio_input: bool,
    media_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    refs = []
    assets = (
        [
            asset
            for media_id in (media_ids or [])
            if (asset := get_media_asset(home, media_id)) is not None
        ]
        if media_ids is not None
        else list_media_assets(
            home,
            limit=20,
            owner_type="session",
            owner_id=session_id,
        )
    )
    for asset in assets:
        supported = (
            asset["media_type"] == "image" and image_input
        ) or (
            asset["media_type"] == "audio" and audio_input
        )
        delivery = (
            "manual_package"
            if supported and adapter_id == "manual"
            else "adapter_input"
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


def _resolve_learning_intent(
    text: str,
    active_session: dict[str, Any] | None,
) -> dict[str, Any]:
    query = " ".join(text.strip().lower().split())
    continue_words = ("继续", "上次", "昨天", "接着", "修改", "resume", "continue")
    if active_session and any(word in query for word in continue_words):
        module = str(active_session["module"])
        session_id = str(active_session["session_id"])
        route = (
            f"/practice/speaking?session={session_id}"
            if module == "speaking"
            else f"/practice/listening/{session_id}"
            if module == "listening"
            else f"/practice/{module}/{session_id}"
        )
        return {
            "intent_version": 1,
            "intent_kind": "resume",
            "module": module,
            "route": route,
            "title": "继续上次学习",
            "message": "已找到未完成练习，继续从上次位置开始。",
            "resolved_by": "teaching_runtime",
            "model_called": False,
        }
    modules = (
        ("listening", ("听力", "听写", "listening", "听辨")),
        ("reading", ("阅读", "passage", "reading", "判断题", "填空题")),
        ("writing", ("写作", "作文", "task 1", "task1", "task 2", "task2", "writing")),
        ("speaking", ("口语", "part 1", "part1", "part 2", "part2", "part 3", "part3", "speaking")),
    )
    for module, words in modules:
        if any(word in query for word in words):
            return {
                "intent_version": 1,
                "intent_kind": "open_module",
                "module": module,
                "route": f"/practice?module={module}",
                "title": f"打开{_module_title(module)}练习",
                "message": "先选择材料和练习模式，再由 Runtime 建立正式 Session。",
                "resolved_by": "teaching_runtime",
                "model_called": False,
            }
    if any(word in query for word in ("错题", "复习", "错误", "review")):
        return {
            "intent_version": 1,
            "intent_kind": "review",
            "module": None,
            "route": "/history?view=review",
            "title": "打开待复习内容",
            "message": "优先处理到期错误和需要二次修改的学习记录。",
            "resolved_by": "teaching_runtime",
            "model_called": False,
        }
    if active_session:
        return _resolve_learning_intent("继续", active_session)
    return {
        "intent_version": 1,
        "intent_kind": "choose_practice",
        "module": None,
        "route": "/practice",
        "title": "选择今天的练习",
        "message": "暂未识别到具体科目，请从四科学习台选择。",
        "resolved_by": "teaching_runtime",
        "model_called": False,
    }


def _module_title(module: str) -> str:
    return {
        "listening": "听力",
        "reading": "阅读",
        "writing": "写作",
        "speaking": "口语",
    }[module]


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
    tutor_orchestrator = TutorOrchestrator(target)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # A native first launch can enter the server process directly. Ensure
        # schema and runtime resources exist before any recovery query.
        initialise_home(target)
        agent_jobs.recover()
        recover_interrupted_imports(target)
        recover_ocr_runtime_install(target)
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
    app.state.tutor_orchestrator = tutor_orchestrator
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
        csrf_token = request.app.state.auth.csrf_token(session)
        response.set_cookie(
            COOKIE_NAME,
            session,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_token,
            httponly=False,
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
                "capabilities": capability_descriptors(),
                "execution_profiles": [],
                "model_providers": [],
                "external_agents": [],
                "ai_setup_required": True,
                "storage": {
                    "data_home": str(target),
                    "database_path": str(db_path(target)),
                    "backups_path": str(target / "backups"),
                },
            }
        profile = load_profile(target)
        active_row = latest_active_session(target)
        active = dict(active_row) if active_row else None
        model_providers = list_model_providers(target)
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
            "capabilities": capability_descriptors(),
            "execution_profiles": agent_jobs.broker.profiles(
                include_diagnostics=False
            ),
            "model_providers": model_providers,
            "external_agents": list_external_agent_profiles(
                target, diagnostics=False
            ),
            "ai_setup_required": not any(
                item["role"] == "primary"
                and item["is_enabled"]
                and item["available"]
                for item in model_providers
            ),
            "storage": {
                "data_home": str(target),
                "database_path": str(db_path(target)),
                "backups_path": str(target / "backups"),
            },
        }

    @app.get("/api/v1/today", dependencies=[Depends(require_session)])
    def today() -> dict[str, Any]:
        context = build_study_context(target)
        context["review_queue"] = {
            "counts": sync_review_tasks(target),
            "items": list_review_tasks(target, limit=3),
        }
        context["practice_units"] = list_practice_units(
            target, scheduled_for=datetime.now().date().isoformat(), limit=10
        )
        return context

    @app.post("/api/v1/today/materialise", dependencies=[Depends(require_session)])
    def today_materialise(payload: TodayMaterialise) -> dict[str, Any]:
        return materialise_today_unit(target, payload.slot)

    @app.post("/api/v1/today/intent", dependencies=[Depends(require_session)])
    def today_intent(payload: TodayIntent) -> dict[str, Any]:
        active_row = latest_active_session(target)
        active_session = dict(active_row) if active_row else None
        return _resolve_learning_intent(payload.text, active_session)

    @app.get("/api/v1/practice-units", dependencies=[Depends(require_session)])
    def practice_units(
        scheduled_for: str | None = None,
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_practice_units(
            target, scheduled_for=scheduled_for, limit=limit
        )

    @app.get(
        "/api/v1/practice-units/{unit_id}",
        dependencies=[Depends(require_session)],
    )
    def practice_unit(unit_id: str) -> dict[str, Any]:
        return get_practice_unit(target, unit_id)

    @app.get("/api/v1/review-tasks", dependencies=[Depends(require_session)])
    def review_tasks(
        status: str = Query("pending"),
        module: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        return list_review_tasks(
            target, status=status, module=module, limit=limit, offset=offset
        )

    @app.post(
        "/api/v1/review-tasks/{review_task_id}/start",
        dependencies=[Depends(require_session)],
    )
    def review_task_start(review_task_id: str) -> dict[str, Any]:
        return start_review_task(target, review_task_id)

    @app.post(
        "/api/v1/review-tasks/{review_task_id}/complete",
        dependencies=[Depends(require_session)],
    )
    def review_task_complete(review_task_id: str) -> dict[str, Any]:
        return complete_review_task(target, review_task_id)

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

    @app.get("/api/v1/system/reliability", dependencies=[Depends(require_session)])
    def system_reliability_endpoint(
        days: int = Query(default=30, ge=1, le=365),
    ) -> dict[str, Any]:
        return provider_reliability_report(target, days=days)

    @app.get("/api/v1/system/evaluations", dependencies=[Depends(require_session)])
    def system_evaluations_endpoint(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return list_capability_evaluations(target, limit=limit)

    @app.get("/api/v1/system/audit", dependencies=[Depends(require_session)])
    def system_audit_endpoint(
        category: str | None = None,
        run_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_audit_events(
            target,
            category=category,
            run_id=run_id,
            limit=limit,
        )

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
        diagnostic = start_diagnostic(target, payload.mode)
        if payload.practice_unit_id:
            bind_practice_unit(
                target,
                payload.practice_unit_id,
                diagnostic_id=str(diagnostic["diagnostic_id"]),
            )
        return diagnostic

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
        result = complete_diagnostic(target, diagnostic_id)
        complete_practice_unit(target, diagnostic_id=diagnostic_id)
        return result

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

    @app.get(
        "/api/v1/content/storage",
        dependencies=[Depends(require_session)],
    )
    def content_storage_endpoint() -> dict[str, Any]:
        return content_storage_status(target)

    @app.post(
        "/api/v1/content/imports/batch-delete",
        dependencies=[Depends(require_session)],
    )
    def content_imports_batch_delete_endpoint(
        payload: ContentImportBatchDelete,
    ) -> dict[str, Any]:
        return delete_imports(
            target,
            payload.import_ids,
            confirmed=payload.confirmed,
        )

    @app.get("/api/v1/content/imports/{import_id}", dependencies=[Depends(require_session)])
    def content_import_endpoint(import_id: str) -> dict[str, Any]:
        job = get_content_import_job(target, import_id)
        if not job:
            raise HTTPException(status_code=404, detail="Content import not found")
        return job

    @app.get(
        "/api/v1/content/ocr-runtime",
        dependencies=[Depends(require_session)],
    )
    def content_ocr_runtime_endpoint() -> dict[str, Any]:
        return ocr_capability(target)

    @app.post(
        "/api/v1/content/ocr-runtime/install",
        dependencies=[Depends(require_session)],
    )
    def content_ocr_runtime_install_endpoint(
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        status = queue_ocr_runtime_install(target)
        if status["status"] == "queued":
            background_tasks.add_task(install_ocr_runtime, target)
        return status

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

    @app.post(
        "/api/v1/content/imports/{import_id}/structured-package",
        dependencies=[Depends(require_session)],
    )
    def build_content_import_package_endpoint(import_id: str) -> dict[str, Any]:
        return build_private_corpus_package(target, import_id)

    @app.post("/api/v1/content/imports/{import_id}/prepare", dependencies=[Depends(require_session)])
    def prepare_content_import_endpoint(
        import_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = queue_import_preparation(target, import_id)
        if job["status"] == "queued":
            background_tasks.add_task(prepare_import, target, import_id)
        return job

    @app.patch("/api/v1/content/imports/{import_id}/page-plan", dependencies=[Depends(require_session)])
    def update_content_import_page_plan_endpoint(
        import_id: str,
        payload: ContentImportPagePlanUpdate,
    ) -> dict[str, Any]:
        return update_import_page_plan(
            target,
            import_id,
            stored_name=payload.stored_name,
            pages=payload.pages,
        )

    @app.post(
        "/api/v1/content/imports/{import_id}/ocr",
        dependencies=[Depends(require_session)],
    )
    def content_import_ocr_endpoint(
        import_id: str,
        payload: ContentImportOcrRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = queue_import_ocr(
            target,
            import_id,
            stored_name=payload.stored_name,
            pages=payload.pages,
        )
        if job["status"] == "ocr_queued":
            background_tasks.add_task(
                run_import_ocr,
                target,
                import_id,
                stored_name=payload.stored_name,
                pages=payload.pages,
            )
        return job

    @app.post(
        "/api/v1/content/imports/{import_id}/review-draft",
        dependencies=[Depends(require_session)],
    )
    def content_import_review_draft_create_endpoint(
        import_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        job = get_content_import_job(target, import_id)
        if not job:
            raise HTTPException(status_code=404, detail="Content import not found")
        if job["status"] != "draft_building":
            background_tasks.add_task(build_import_review_draft, target, import_id)
        return job

    @app.get(
        "/api/v1/content/imports/{import_id}/review-draft",
        dependencies=[Depends(require_session)],
    )
    def content_import_review_draft_endpoint(import_id: str) -> dict[str, Any]:
        return read_import_review_draft(target, import_id)

    @app.patch(
        "/api/v1/content/imports/{import_id}/review-draft/segments/{segment_id}",
        dependencies=[Depends(require_session)],
    )
    def content_import_review_draft_segment_endpoint(
        import_id: str,
        segment_id: str,
        payload: ContentImportDraftSegmentUpdate,
    ) -> dict[str, Any]:
        return update_import_review_segment(
            target,
            import_id,
            segment_id=segment_id,
            text=payload.text,
            review_status=payload.review_status,
            expected_revision=payload.expected_revision,
        )

    @app.get(
        "/api/v1/content/imports/{import_id}/audio-review/{stored_name}",
        dependencies=[Depends(require_session)],
    )
    def content_import_audio_review_endpoint(
        import_id: str,
        stored_name: str,
    ) -> dict[str, Any]:
        return read_audio_review(target, import_id, stored_name)

    @app.put(
        "/api/v1/content/imports/{import_id}/audio-review",
        dependencies=[Depends(require_session)],
    )
    def content_import_audio_review_update_endpoint(
        import_id: str,
        payload: ContentImportAudioReviewUpdate,
    ) -> dict[str, Any]:
        return update_audio_review(
            target,
            import_id,
            stored_name=payload.stored_name,
            transcript=payload.transcript,
            cues=[cue.model_dump() for cue in payload.cues],
            duration_seconds=payload.duration_seconds,
            review_status=payload.review_status,
            expected_revision=payload.expected_revision,
        )

    @app.get(
        "/api/v1/content/imports/{import_id}/files/{stored_name}/content",
        dependencies=[Depends(require_session)],
    )
    def content_import_file_endpoint(import_id: str, stored_name: str) -> Response:
        job = get_content_import_job(target, import_id)
        if not job:
            raise HTTPException(status_code=404, detail="Content import not found")
        path = import_file_path(target, job, stored_name)
        file_record = next(
            item
            for item in job["files"]
            if item["stored_name"] == stored_name
        )
        display_name = str(file_record.get("original_name") or stored_name)
        media_type = file_record.get("mime_type") or {
            "pdf": "application/pdf",
            "audio": "application/octet-stream",
            "image": "application/octet-stream",
        }.get(file_record.get("file_kind"), "application/octet-stream")
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    "inline; filename*=UTF-8''"
                    f"{quote(display_name, safe='')}"
                ),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

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
        review_mode: bool = False,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        items = list_assessment_packs(
            target,
            module=module,
            practice_mode=practice_mode,
            conformance_status=conformance_status,
            learner_ready=not review_mode,
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
        run = start_assessment_run(
            target,
            payload.pack_id,
            idempotency_key=_idempotency_key(idempotency),
        )
        if payload.practice_unit_id:
            bind_practice_unit(
                target,
                payload.practice_unit_id,
                assessment_run_id=str(run["run_id"]),
            )
            run = get_assessment_run(target, str(run["run_id"]))
        return run

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
        result = submit_assessment_run(
            target,
            run_id,
            idempotency_key=_idempotency_key(idempotency),
        )
        complete_practice_unit(target, assessment_run_id=run_id)
        return result

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

    @app.post(
        "/api/v1/assessment-runs/{run_id}/audio/{media_id}/lease",
        dependencies=[Depends(require_session)],
    )
    def assessment_audio_lease_endpoint(
        run_id: str, media_id: str
    ) -> dict[str, Any]:
        return renew_audio_playback_lease(target, run_id, media_id)

    @app.get(
        "/api/v1/assessment-runs/{run_id}/audio/{media_id}/content",
        dependencies=[Depends(require_session)],
    )
    def assessment_audio_content_endpoint(
        run_id: str,
        media_id: str,
        lease: str = Query(min_length=20, max_length=512),
    ) -> FileResponse:
        validate_audio_playback_lease(target, run_id, media_id, lease)
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
        return register_speaking_source_report(target, run_id, imported)

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
        if payload.question_id:
            selected_question = show_question(target, payload.question_id)
            if not selected_question:
                raise ValueError(f"Unknown question: {payload.question_id}")
            if (
                selected_question.get("review_status") != "reviewed"
                or selected_question.get("conformance_status") != "verified"
            ):
                raise ValueError(
                    "This question has not completed local review and cannot enter learner practice"
                )
        if payload.assessment_pack_id:
            selected_pack = get_assessment_pack(target, payload.assessment_pack_id)
            if not selected_pack:
                raise ValueError(f"Unknown assessment pack: {payload.assessment_pack_id}")
            if (
                selected_pack.get("review_status") != "reviewed"
                or selected_pack.get("conformance_status") != "verified"
            ):
                raise ValueError(
                    "This assessment pack has not completed local review and cannot start"
                )
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
        if payload.practice_unit_id:
            bind_practice_unit(
                target, payload.practice_unit_id, session_id=path.stem
            )
        return _session_or_404(target, path.stem)

    @app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_session)])
    def get_session_endpoint(session_id: str) -> dict[str, Any]:
        return _session_or_404(target, session_id)

    @app.post("/api/v1/sessions/{session_id}/reconcile", dependencies=[Depends(require_session)])
    def reconcile_session_endpoint(
        session_id: str,
        prefer: str = Query("auto", pattern="^(auto|markdown|sqlite)$"),
    ) -> dict[str, Any]:
        _session_or_404(target, session_id)
        return reconcile_session(target, session_id, prefer=prefer)

    @app.post("/api/v1/sessions/{session_id}/transition", dependencies=[Depends(require_session)])
    def transition_endpoint(session_id: str, payload: SessionTransition) -> dict[str, Any]:
        session = _session_or_404(target, session_id)
        path = target / "sessions" / session["module"] / f"{session_id}.md"
        return transition_session(target, path, payload.status)

    @app.post("/api/v1/sessions/{session_id}/finish", dependencies=[Depends(require_session)])
    def finish_endpoint(session_id: str) -> dict[str, Any]:
        session = _session_or_404(target, session_id)
        path = target / "sessions" / session["module"] / f"{session_id}.md"
        result = finish_session(target, path)
        complete_practice_unit(target, session_id=session_id)
        return result

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
        session = create_speaking_handoff(
            target,
            mode=payload.mode,
            provider=payload.provider,
            question_ids=payload.question_ids,
            seed=payload.seed,
            idempotency_key=_idempotency_key(idempotency),
        )
        if payload.practice_unit_id:
            bind_practice_unit(
                target,
                payload.practice_unit_id,
                session_id=str(session["session_id"]),
            )
        return session

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
        part: int | None = Query(default=None, ge=1, le=3),
        question_type: str | None = None,
        topic: str | None = None,
        passage_id: str | None = None,
        query: str | None = None,
        review_mode: bool = False,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, Any]]:
        items = search_questions(
            target,
            module=module,
            task=task,
            part=part,
            question_type=question_type,
            topic=topic,
            passage_id=passage_id,
            query=query,
            learner_ready=not review_mode,
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

    @app.get("/api/v1/progress/weekly", dependencies=[Depends(require_session)])
    def progress_weekly() -> dict[str, Any]:
        return build_structured_weekly_report(target, persist=True)

    @app.get(
        "/api/v1/progress/weekly/history",
        dependencies=[Depends(require_session)],
    )
    def progress_weekly_history(
        limit: int = Query(12, ge=1, le=104),
    ) -> list[dict[str, Any]]:
        return list_weekly_reports(target, limit=limit)

    @app.post(
        "/api/v1/progress/actions/{action_id}/start",
        dependencies=[Depends(require_session)],
    )
    def progress_action_start(action_id: str) -> dict[str, Any]:
        return materialise_progress_action(target, action_id)

    @app.get("/api/v1/coaching-artifacts", dependencies=[Depends(require_session)])
    def coaching_artifacts(
        artifact_type: str | None = None,
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return list_coaching_artifacts(
            target, artifact_type=artifact_type, limit=limit
        )

    @app.get("/api/v1/tutor/domain-tools", dependencies=[Depends(require_session)])
    def tutor_domain_tools() -> list[dict[str, Any]]:
        return tutor_orchestrator.registry.descriptors()

    @app.post("/api/v1/tutor/context", dependencies=[Depends(require_session)])
    def tutor_context(payload: TutorContextRequest) -> dict[str, Any]:
        return tutor_orchestrator.prepare(payload.text, module=payload.module)

    @app.get("/api/v1/learner-memories", dependencies=[Depends(require_session)])
    def learner_memories(
        status: str = Query("active", pattern="^(active|dismissed)$"),
        memory_type: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return list_learner_memories(
            target,
            status=status,
            memory_type=memory_type,
            limit=limit,
        )

    @app.post("/api/v1/learner-memories", dependencies=[Depends(require_session)])
    def learner_memory_create(payload: LearnerMemoryCreate) -> dict[str, Any]:
        memory = create_learner_memory(
            target,
            memory_type=payload.memory_type,
            statement=payload.statement,
            confidence=payload.confidence,
            evidence_refs=payload.evidence_refs,
            scope=payload.scope,
            source_thread_id=payload.source_thread_id,
            source_session_id=payload.source_session_id,
        )
        record_audit_event(
            target,
            category="learner_memory",
            action="created",
            outcome="succeeded",
            subject_type="learner_memory",
            subject_id=str(memory["memory_id"]),
            payload={"statement": payload.statement},
            metadata={"memory_type": payload.memory_type, "scope": payload.scope},
        )
        return memory

    @app.patch(
        "/api/v1/learner-memories/{memory_id}",
        dependencies=[Depends(require_session)],
    )
    def learner_memory_update(
        memory_id: str,
        payload: LearnerMemoryUpdate,
    ) -> dict[str, Any]:
        memory = update_learner_memory(
            target,
            memory_id,
            statement=payload.statement,
            confidence=payload.confidence,
            status=payload.status,
            scope=payload.scope,
        )
        record_audit_event(
            target,
            category="learner_memory",
            action="updated",
            outcome="succeeded",
            subject_type="learner_memory",
            subject_id=memory_id,
            payload={"statement": payload.statement} if payload.statement else None,
            metadata={"status": memory["status"], "scope": memory["scope"]},
        )
        return memory

    @app.delete(
        "/api/v1/learner-memories/{memory_id}",
        dependencies=[Depends(require_session)],
    )
    def learner_memory_delete(memory_id: str) -> dict[str, Any]:
        if not delete_learner_memory(target, memory_id):
            raise HTTPException(status_code=404, detail="Learner memory not found")
        record_audit_event(
            target,
            category="learner_memory",
            action="deleted",
            outcome="succeeded",
            subject_type="learner_memory",
            subject_id=memory_id,
        )
        return {"memory_id": memory_id, "deleted": True}

    @app.get("/api/v1/study-threads", dependencies=[Depends(require_session)])
    def study_threads_endpoint(
        limit: int = Query(30, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return list_study_threads(target, limit=limit)

    @app.post("/api/v1/study-threads", dependencies=[Depends(require_session)])
    def study_thread_create_endpoint(
        payload: StudyThreadCreate,
    ) -> dict[str, Any]:
        return create_study_thread(
            target,
            title=payload.title,
            module=payload.module,
            model_provider_id=payload.model_provider_id,
            source_context=payload.source_context,
        )

    @app.get(
        "/api/v1/study-threads/{thread_id}",
        dependencies=[Depends(require_session)],
    )
    def study_thread_endpoint(thread_id: str) -> dict[str, Any]:
        return get_study_thread(target, thread_id)

    @app.patch(
        "/api/v1/study-threads/{thread_id}",
        dependencies=[Depends(require_session)],
    )
    def study_thread_update_endpoint(
        thread_id: str,
        payload: StudyThreadUpdate,
    ) -> dict[str, Any]:
        return rename_study_thread(target, thread_id, title=payload.title)

    @app.delete(
        "/api/v1/study-threads/{thread_id}",
        dependencies=[Depends(require_session)],
    )
    def study_thread_delete_endpoint(thread_id: str) -> dict[str, Any]:
        return delete_study_thread(target, thread_id)

    @app.post(
        "/api/v1/study-threads/{thread_id}/messages",
        dependencies=[Depends(require_session)],
    )
    async def study_thread_message_endpoint(
        thread_id: str,
        content: str = Form(..., min_length=1, max_length=20_000),
        context_json: str = Form("{}"),
        files: list[UploadFile] | None = File(default=None),
    ) -> dict[str, Any]:
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError as exc:
            raise ValueError("context_json must be valid JSON") from exc
        if not isinstance(context, dict):
            raise ValueError("context_json must contain an object")
        payloads: list[tuple[str, bytes, str | None]] = []
        for item in files or []:
            payloads.append(
                (
                    item.filename or "attachment",
                    await item.read(),
                    item.content_type,
                )
            )
            await item.close()
        return add_user_message(
            target,
            thread_id,
            content=content,
            files=payloads,
            context=context,
        )

    @app.get(
        "/api/v1/study-threads/{thread_id}/attachments/{attachment_id}/content",
        dependencies=[Depends(require_session)],
    )
    def study_thread_attachment_endpoint(
        thread_id: str,
        attachment_id: str,
    ) -> FileResponse:
        thread = get_study_thread(target, thread_id)
        attachment = next(
            (
                item
                for item in thread["attachments"]
                if item["attachment_id"] == attachment_id
            ),
            None,
        )
        if not attachment:
            raise HTTPException(status_code=404, detail="Attachment not found")
        path = resolve_study_attachment(target, attachment)
        return FileResponse(
            path,
            media_type=attachment.get("mime_type") or "application/octet-stream",
            filename=str(attachment["original_name"]),
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post(
        "/api/v1/study-threads/{thread_id}/promote",
        dependencies=[Depends(require_session)],
    )
    def study_thread_promote_endpoint(
        thread_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        created = promote_study_thread(target, thread_id)
        queued = queue_import_preparation(target, str(created["import_id"]))
        if queued["status"] == "queued":
            background_tasks.add_task(
                prepare_import, target, str(created["import_id"])
            )
        return queued

    @app.get("/api/v1/agents", dependencies=[Depends(require_session)])
    def agents() -> list[dict[str, Any]]:
        return adapter_descriptors()

    @app.get("/api/v1/capabilities", dependencies=[Depends(require_session)])
    def capabilities() -> list[dict[str, Any]]:
        return capability_descriptors()

    @app.get(
        "/api/v1/model-provider-presets",
        dependencies=[Depends(require_session)],
    )
    def model_provider_presets() -> list[dict[str, Any]]:
        return provider_presets()

    @app.get(
        "/api/v1/model-providers",
        dependencies=[Depends(require_session)],
    )
    def model_providers(
        diagnostics: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        return list_model_providers(target, diagnostics=diagnostics)

    @app.post(
        "/api/v1/model-providers",
        dependencies=[Depends(require_session)],
    )
    def model_provider_create(
        payload: ModelProviderCreate,
    ) -> dict[str, Any]:
        values = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        return create_model_provider(target, **values)

    @app.patch(
        "/api/v1/model-providers/{provider_id}",
        dependencies=[Depends(require_session)],
    )
    def model_provider_update(
        provider_id: str,
        payload: ModelProviderUpdate,
    ) -> dict[str, Any]:
        fields_set = set(
            getattr(
                payload,
                "model_fields_set",
                getattr(payload, "__fields_set__", set()),
            )
        )
        raw_values = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        values = {
            key: value
            for key, value in raw_values.items()
            if key in fields_set or key == "clear_api_key"
        }
        return update_model_provider(target, provider_id, **values)

    @app.delete(
        "/api/v1/model-providers/{provider_id}",
        dependencies=[Depends(require_session)],
    )
    def model_provider_delete(provider_id: str) -> dict[str, bool]:
        delete_model_provider(target, provider_id)
        return {"deleted": True}

    @app.post(
        "/api/v1/model-providers/{provider_id}/test",
        dependencies=[Depends(require_session)],
    )
    def model_provider_test(provider_id: str) -> dict[str, Any]:
        return test_model_provider(target, provider_id)

    @app.get(
        "/api/v1/model-providers/{provider_id}/models",
        dependencies=[Depends(require_session)],
    )
    def model_provider_models(provider_id: str) -> list[dict[str, Any]]:
        return list_provider_models(target, provider_id)

    @app.get(
        "/api/v1/external-agents",
        dependencies=[Depends(require_session)],
    )
    def external_agents(
        diagnostics: bool = Query(default=False),
    ) -> list[dict[str, Any]]:
        return list_external_agent_profiles(target, diagnostics=diagnostics)

    @app.get(
        "/api/v1/execution-profiles",
        dependencies=[Depends(require_session)],
    )
    def execution_profiles(
        diagnostics: bool = Query(default=True),
    ) -> list[dict[str, Any]]:
        return agent_jobs.broker.profiles(
            include_diagnostics=diagnostics
        )

    @app.patch(
        "/api/v1/execution-profiles/{profile_id}",
        dependencies=[Depends(require_session)],
    )
    def execution_profile_update(
        profile_id: str, payload: ExecutionProfileUpdate
    ) -> dict[str, Any]:
        current = agent_jobs.broker.profile(profile_id)
        fields_set = set(
            getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
        )
        return update_execution_profile(
            target,
            profile_id,
            model_id=(
                payload.model_id
                if "model_id" in fields_set
                else current.get("model_id")
            ),
            reasoning_effort=(
                payload.reasoning_effort
                if "reasoning_effort" in fields_set
                else current.get("reasoning_effort")
            ),
            is_enabled=payload.is_enabled,
            is_default=payload.is_default,
            config=payload.config,
        )

    @app.get(
        "/api/v1/execution-profiles/codex-managed/runtime",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_runtime() -> dict[str, Any]:
        adapter, _ = agent_jobs.broker.managed_codex()
        return adapter.runtime_status(target)

    @app.post(
        "/api/v1/execution-profiles/codex-managed/runtime/install",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_runtime_install() -> dict[str, Any]:
        adapter, _ = agent_jobs.broker.managed_codex()
        return adapter.install_runtime(target)

    @app.get(
        "/api/v1/execution-profiles/codex-managed/account",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_account() -> dict[str, Any]:
        adapter, profile = agent_jobs.broker.managed_codex()
        return adapter.account(target, profile)

    @app.get(
        "/api/v1/execution-profiles/codex-managed/models",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_models() -> dict[str, Any]:
        adapter, profile = agent_jobs.broker.managed_codex()
        return adapter.models(target, profile)

    @app.get(
        "/api/v1/execution-profiles/codex-managed/rate-limits",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_rate_limits() -> dict[str, Any]:
        adapter, profile = agent_jobs.broker.managed_codex()
        return adapter.rate_limits(target, profile)

    @app.post(
        "/api/v1/execution-profiles/codex-managed/login",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_login(payload: CodexLoginStart) -> dict[str, Any]:
        adapter, profile = agent_jobs.broker.managed_codex()
        # The key is passed directly to the isolated Codex runtime. It is never
        # persisted in the IELTS database, settings or Agent run envelope.
        return adapter.login(
            target,
            profile,
            login_type=payload.login_type,
            api_key=payload.api_key,
        )

    @app.post(
        "/api/v1/execution-profiles/codex-managed/logout",
        dependencies=[Depends(require_session)],
    )
    def codex_managed_logout() -> dict[str, Any]:
        adapter, profile = agent_jobs.broker.managed_codex()
        return adapter.logout(target, profile)

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
        prepared = agent_jobs.broker.prepare(
            model_provider_id=payload.model_provider_id,
            execution_profile_id=payload.execution_profile_id,
            legacy_adapter_id=payload.adapter_id,
        )
        profile = prepared.profile
        adapter = prepared.adapter
        adapter_id = str(profile["backend_id"])
        primary_provider = prepared.primary_model_provider
        capability = capability_for_contract(payload.output_contract)
        skill_envelope = compile_skill_envelope(capability)
        is_study_help = payload.output_contract == "study-help@1"
        if is_study_help and (
            not payload.study_thread_id or not payload.user_message_id
        ):
            raise ValueError(
                "Study help requires a learning thread and user message"
            )
        if not is_study_help and not payload.study_session_id:
            raise ValueError("This IELTS capability requires a Study Session")
        context_identity = (
            f"thread:{payload.study_thread_id}:message:{payload.user_message_id}"
            if is_study_help
            else f"session:{payload.study_session_id}"
        )
        scope = (
            f"agent-run:{context_identity}:{profile['profile_id']}:"
            f"{payload.output_contract}:{payload.action}"
        )
        replay = get_idempotency_record(target, scope, idempotency)
        if replay:
            existing = get_agent_run(target, str(replay["response"]["run_id"]))
            if existing:
                return existing
        session = (
            _session_or_404(target, str(payload.study_session_id))
            if payload.study_session_id
            else None
        )
        thread_context = (
            study_thread_agent_context(
                target,
                thread_id=str(payload.study_thread_id),
                message_id=str(payload.user_message_id),
            )
            if is_study_help
            else None
        )
        if thread_context is not None:
            thread_context["tutor_orchestration"] = tutor_orchestrator.prepare(
                str(thread_context["user_request"]),
                module=(
                    str(thread_context["module"])
                    if thread_context.get("module") != "mixed"
                    else None
                ),
            )
        capabilities = adapter.probe()
        adapter_identity = adapter.identity()
        selected_model_id = (
            profile.get("model_id")
            or payload.model_id
            or adapter_identity.model_id
        )
        selected_model_name = (
            payload.model_display_name
            or selected_model_id
            or adapter_identity.model_display_name
        )
        run_id = f"run_{uuid.uuid4().hex}"
        permission = check_processing_permission(
            target,
            remote_processing=capabilities.remote_processing,
            explicit_consent=payload.explicit_consent,
            source_type=payload.source_type or ("personal" if capabilities.remote_processing else None),
            question_id=session.get("question_id") if session else None,
        )
        if not permission["allowed"]:
            raise PrivateProcessingBlockedError(
                "Private material requires one-time consent before Agent handoff.",
                details=permission,
            )
        media_refs = _agent_media_refs(
            target,
            payload.study_session_id,
            adapter_id=adapter_id,
            image_input=capabilities.image_input,
            audio_input=capabilities.audio_input,
            media_ids=(
                thread_media_ids(
                    target,
                    str(payload.study_thread_id),
                    message_id=str(payload.user_message_id),
                )
                if is_study_help
                else None
            ),
        )
        canonical_session = dict(session or thread_context or {})
        canonical_session["registered_media"] = media_refs
        canonical_session["media_evidence_sufficient"] = not media_refs or all(
            item["available_to_agent"] for item in media_refs
        )
        if (
            payload.output_contract == "writing-mock-review@1"
            and session
            and session.get("assessment_run_id")
        ):
            assessment = get_assessment_run(
                target, str(session["assessment_run_id"])
            )
            canonical_session["assessment_context"] = {
                "assessment_run_id": assessment["run_id"],
                "pack_id": assessment["pack_id"],
                "practice_mode": assessment["practice_mode"],
                "tasks": [
                    {
                        key: question.get(key)
                        for key in (
                            "question_id",
                            "task",
                            "content",
                            "task_data",
                            "media_id",
                            "media_ids",
                            "minimum_words",
                        )
                        if question.get(key) is not None
                    }
                    for question in assessment["pack_snapshot"].get("questions")
                    or []
                ],
                "responses": [
                    {
                        "question_id": item["question_id"],
                        "section_key": item["section_key"],
                        "response": item["response"],
                    }
                    for item in assessment["responses"]
                ],
                "aggregation_rule": "Runtime computes (Task 1 + 2 × Task 2) / 3",
            }
        provider_ids = [
            str(item["provider_id"]) for item in prepared.model_route
        ] or [str(profile.get("backend_id") or adapter_id)]
        privacy_receipt = build_privacy_receipt(
            run_id=run_id,
            decision=permission,
            provider_ids=provider_ids,
            scope={
                "capability_id": capability.capability_id,
                "output_contract": payload.output_contract,
                "context_ref": context_identity,
                "question_id": session.get("question_id") if session else None,
                "media": [
                    {
                        "media_id": item["media_id"],
                        "content_hash": item.get("content_hash"),
                    }
                    for item in media_refs
                ],
                "learner_memory_ids": [
                    item["memory_id"]
                    for item in (
                        thread_context.get("tutor_orchestration", {}).get(
                            "learner_memories", []
                        )
                        if thread_context
                        else []
                    )
                ],
                "history_refs": [
                    f"{item['source_type']}:{item['source_id']}"
                    for item in (
                        thread_context.get("tutor_orchestration", {}).get(
                            "history_evidence", []
                        )
                        if thread_context
                        else []
                    )
                ],
            },
        )
        permission = {
            **permission,
            "receipt_id": privacy_receipt["receipt_id"],
        }
        request_envelope = {
            "request_version": 3,
            "request_id": run_id,
            "study_session_id": payload.study_session_id,
            "study_thread_id": payload.study_thread_id,
            "user_message_id": payload.user_message_id,
            "capability_id": capability.capability_id,
            "skill": capability.skill,
            "skill_envelope": skill_envelope.descriptor(),
            "action": payload.action,
            "context_ref": (
                context_identity
                if is_study_help
                else f"{context_identity}:revision:{session.get('revision', 0) if session else 0}"
            ),
            "payload_refs": [
                context_identity,
                *(
                    [f"question:{session['question_id']}"]
                    if session and session.get("question_id")
                    else []
                ),
                *[f"media:{item['media_id']}" for item in media_refs],
            ],
            "output_contract": payload.output_contract,
            "material_evidence_sufficient": bool(
                thread_context
                and thread_context.get("material_evidence_sufficient")
            ),
            "privacy_decision": permission,
            "execution_profile": {
                "profile_id": profile["profile_id"],
                "display_name": profile["display_name"],
                "backend_kind": profile["backend_kind"],
                "backend_id": profile["backend_id"],
                "transport": profile["transport"],
                "auth_mode": profile["auth_mode"],
                "model_id": selected_model_id,
                "reasoning_effort": profile.get("reasoning_effort"),
                "config": profile.get("config") or {},
            },
            "model_provider_route": [
                {
                    "provider_id": item["provider_id"],
                    "display_name": item["display_name"],
                    "provider_kind": item["provider_kind"],
                    "transport": item["transport"],
                    "auth_mode": item["auth_mode"],
                    "model_id": item.get("model_id"),
                    "role": item["role"],
                }
                for item in prepared.model_route
            ],
            "agent_identity": {
                "adapter_id": adapter_id,
                "agent_provider": payload.agent_provider or adapter_identity.agent_provider,
                "agent_version": payload.agent_version or adapter_identity.agent_version,
                "model_id": selected_model_id,
                "model_display_name": selected_model_name,
                "agent_session_id": payload.agent_session_id,
                "launcher_kind": adapter_identity.launcher_kind,
            },
            "media_refs": media_refs,
            "canonical_session": (
                canonical_session if profile["backend_kind"] != "mock" else None
            ),
        }
        run = create_agent_run(
            target,
            {
                "run_id": run_id,
                "study_session_id": payload.study_session_id,
                "adapter_id": adapter_id,
                "capability_id": capability.capability_id,
                "execution_profile_id": (
                    None if primary_provider else profile["profile_id"]
                ),
                "model_provider_id": (
                    primary_provider["provider_id"]
                    if primary_provider
                    else None
                ),
                "backend_kind": profile["backend_kind"],
                "transport": profile["transport"],
                "auth_mode": profile["auth_mode"],
                "agent_provider": payload.agent_provider or adapter_identity.agent_provider,
                "agent_version": payload.agent_version or adapter_identity.agent_version,
                "model_id": selected_model_id,
                "model_display_name": selected_model_name,
                "agent_session_id": payload.agent_session_id,
                "launcher_kind": adapter_identity.launcher_kind,
                "capabilities": capabilities.__dict__,
                "calibration_status": adapter_identity.calibration_status,
                "action": payload.action,
                "output_contract": payload.output_contract,
                "base_revision": (
                    int(session.get("revision", 0)) if session else None
                ),
                "status": "queued",
                "request": request_envelope,
                "timeout_seconds": payload.timeout_seconds,
                "skill_hash": skill_envelope.source_hash,
                "inference_route": [
                    item["provider_id"] for item in prepared.model_route
                ],
                "privacy_receipt": privacy_receipt,
            },
        )
        append_agent_run_event(
            target,
            run_id,
            "status",
            {"stage": "queued", "label": "Preparing feedback"},
        )
        append_agent_run_event(
            target,
            run_id,
            "context_ready",
            {
                "stage": "context_ready",
                "payload_ref_count": len(request_envelope["payload_refs"]),
                "media_ref_count": len(media_refs),
            },
        )
        append_agent_run_event(
            target,
            run_id,
            "skill_compiled",
            {
                "stage": "skill_compiled",
                "skill_hash": skill_envelope.source_hash,
                "contract": payload.output_contract,
            },
        )
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
        return {**run, "provider_attempts": list_provider_attempts(target, run_id)}

    @app.get(
        "/api/v1/agent-runs/{run_id}/attempts",
        dependencies=[Depends(require_session)],
    )
    def agent_run_attempts(run_id: str) -> list[dict[str, Any]]:
        if not get_agent_run(target, run_id):
            raise HTTPException(status_code=404, detail="Agent run not found")
        return list_provider_attempts(target, run_id)

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
        if path == "api" or path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "API_ENDPOINT_NOT_FOUND",
                        "message": "API endpoint not found.",
                    }
                },
            )
        index = selected_static / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "UI_ASSETS_MISSING", "message": "Frontend assets are not built."}},
        )

    return app
