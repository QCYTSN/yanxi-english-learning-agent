from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..agent_gateway import adapter_descriptors, get_adapter
from ..allocation import recommend_allocation
from ..config import load_profile
from ..errors import CoachError, PrivateProcessingBlockedError, SessionNotFoundError
from ..locking import runtime_lock
from ..media import import_image_bytes, resolve_media_file
from ..onboarding import onboarding_status
from ..paths import resolve_home
from ..privacy import check_processing_permission
from ..profiles import build_learning_profile
from ..question_bank import search_questions, show_question, show_reading_set
from ..reports import build_summary, build_trend_report
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
    get_study_draft,
    list_agent_run_events,
    list_error_profile,
    list_media_assets,
    list_sessions,
    save_study_draft,
    update_agent_run,
)
from ..study_context import build_study_context
from ..study_runtime import (
    apply_reading_review,
    apply_writing_review,
    record_reading_hint,
    submit_reading_answers,
    submit_writing_version,
)
from .auth import AuthState, COOKIE_NAME, require_session
from .models import (
    AgentResultImport,
    AgentRunCreate,
    AuthExchange,
    DraftSave,
    ReadingAnswersSubmit,
    ReadingHintSubmit,
    SessionCreate,
    SessionTransition,
    WritingVersionSubmit,
)


TERMINAL_RUN_STATUSES = {"persisted", "cancelled", "failed", "invalid_output"}


class LoopbackSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, allowed_origin: str, test_mode: bool = False) -> None:
        super().__init__(app)
        self.allowed_origin = allowed_origin.rstrip("/")
        self.test_mode = test_mode

    async def dispatch(self, request: Request, call_next: Any) -> Response:
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
    return {key: value for key, value in asset.items() if key != "local_path"}


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
) -> FastAPI:
    target = resolve_home(home)
    app = FastAPI(title="IELTS AI Coach Local UI", version=__version__, docs_url=None, redoc_url=None)
    app.state.home = target
    app.state.auth = auth or AuthState.create()
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
            }
        profile = load_profile(target)
        active = next(
            (
                dict(row)
                for row in list_sessions(target, limit=100)
                if row["status"] not in {"completed", "cancelled"}
            ),
            None,
        )
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
            },
            "active_session": active,
            "health": {"database": True, "configuration": True},
            "agents": adapter_descriptors(),
        }

    @app.get("/api/v1/today", dependencies=[Depends(require_session)])
    def today() -> dict[str, Any]:
        return build_study_context(target)

    @app.get("/api/v1/sessions", dependencies=[Depends(require_session)])
    def sessions(module: str | None = None, limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return [dict(row) for row in list_sessions(target, module=module, limit=limit)]

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

    @app.get("/api/v1/questions", dependencies=[Depends(require_session)])
    def questions(
        module: str | None = None,
        task: str | None = None,
        question_type: str | None = None,
        topic: str | None = None,
        passage_id: str | None = None,
        query: str | None = None,
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return search_questions(
            target,
            module=module,
            task=task,
            question_type=question_type,
            topic=topic,
            passage_id=passage_id,
            query=query,
            limit=limit,
        )

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

    @app.get("/api/v1/media", dependencies=[Depends(require_session)])
    def media_list() -> list[dict[str, Any]]:
        return [_public_media(item) for item in list_media_assets(target)]

    @app.get("/api/v1/media/{media_id}/content", dependencies=[Depends(require_session)])
    def media_content(media_id: str) -> FileResponse:
        asset, path = resolve_media_file(target, media_id)
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

    @app.get("/api/v1/agents", dependencies=[Depends(require_session)])
    def agents() -> list[dict[str, Any]]:
        return adapter_descriptors()

    def apply_agent_result(run: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if run["output_contract"] == "writing-review@1":
            return apply_writing_review(
                target,
                run["study_session_id"],
                result,
                expected_revision=run["base_revision"],
                idempotency_key=f"agent:{run['run_id']}",
            )
        return apply_reading_review(
            target,
            run["study_session_id"],
            result,
            expected_revision=run["base_revision"],
            idempotency_key=f"agent:{run['run_id']}",
        )

    @app.post("/api/v1/agent-runs", dependencies=[Depends(require_session)])
    def agent_run_create(payload: AgentRunCreate) -> dict[str, Any]:
        session = _session_or_404(target, payload.study_session_id)
        adapter = get_adapter(payload.adapter_id)
        permission = check_processing_permission(
            target,
            remote_processing=adapter.probe().remote_processing,
            explicit_consent=payload.explicit_consent,
            source_type=payload.source_type or ("personal" if adapter.probe().remote_processing else None),
            question_id=session.get("question_id"),
        )
        if not permission["allowed"]:
            raise PrivateProcessingBlockedError(
                "Private material requires one-time consent before Agent handoff.",
                details=permission,
            )
        run_id = f"run_{uuid.uuid4().hex}"
        request_envelope = {
            "request_version": 1,
            "request_id": run_id,
            "study_session_id": payload.study_session_id,
            "skill": "ielts-writing" if payload.output_contract.startswith("writing") else "ielts-reading",
            "action": payload.action,
            "context_ref": f"session:{payload.study_session_id}:revision:{session.get('revision', 0)}",
            "payload_refs": [
                f"session:{payload.study_session_id}",
                *([f"question:{session['question_id']}"] if session.get("question_id") else []),
            ],
            "output_contract": payload.output_contract,
            "privacy_decision": permission,
            "canonical_session": session if payload.adapter_id == "manual" else None,
        }
        run = create_agent_run(
            target,
            {
                "run_id": run_id,
                "study_session_id": payload.study_session_id,
                "adapter_id": payload.adapter_id,
                "action": payload.action,
                "output_contract": payload.output_contract,
                "base_revision": int(session.get("revision", 0)),
                "status": "queued",
                "request": request_envelope,
            },
        )
        append_agent_run_event(target, run_id, "status", {"stage": "queued", "label": "Preparing feedback"})
        if payload.adapter_id == "manual":
            manual = adapter.run(target, request_envelope)
            run = update_agent_run(target, run_id, status="awaiting_import", result=manual)
            append_agent_run_event(
                target, run_id, "status", {"stage": "awaiting_import", "label": "Waiting for structured result"}
            )
            return run
        try:
            update_agent_run(target, run_id, status="running", started_at=datetime.now(timezone.utc).isoformat())
            append_agent_run_event(target, run_id, "status", {"stage": "running", "label": "Reviewing response"})
            result = adapter.run(target, request_envelope)
            append_agent_run_event(target, run_id, "status", {"stage": "validating", "label": "Checking feedback format"})
            canonical = apply_agent_result(run, result)
            run = update_agent_run(
                target,
                run_id,
                status="persisted",
                result=result,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            append_agent_run_event(
                target,
                run_id,
                "completed",
                {"session_id": payload.study_session_id, "revision": canonical["revision"]},
            )
            return run
        except Exception as exc:
            update_agent_run(
                target,
                run_id,
                status="failed",
                error_code=getattr(exc, "code", "AGENT_RUN_FAILED"),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            append_agent_run_event(target, run_id, "failed", {"message": str(exc)})
            raise

    @app.post("/api/v1/agent-runs/{run_id}/import", dependencies=[Depends(require_session)])
    def agent_result_import(run_id: str, payload: AgentResultImport) -> dict[str, Any]:
        run = get_agent_run(target, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        if run["adapter_id"] != "manual" or run["status"] != "awaiting_import":
            raise ValueError("This Agent run is not waiting for a manual result")
        append_agent_run_event(target, run_id, "status", {"stage": "validating", "label": "Checking feedback format"})
        canonical = apply_agent_result(run, payload.result)
        updated = update_agent_run(
            target,
            run_id,
            status="persisted",
            result=payload.result,
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
        run = get_agent_run(target, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Agent run not found")
        if run["status"] in TERMINAL_RUN_STATUSES:
            return run
        updated = update_agent_run(
            target,
            run_id,
            status="cancelled",
            error_code="AGENT_RUN_CANCELLED",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        append_agent_run_event(target, run_id, "cancelled", {})
        return updated

    @app.get("/api/v1/agent-runs/{run_id}/events", dependencies=[Depends(require_session)])
    async def agent_run_events(run_id: str, request: Request) -> StreamingResponse:
        if not get_agent_run(target, run_id):
            raise HTTPException(status_code=404, detail="Agent run not found")

        async def stream() -> AsyncIterator[str]:
            cursor = 0
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
