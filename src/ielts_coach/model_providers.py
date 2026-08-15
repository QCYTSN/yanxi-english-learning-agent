from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from collections.abc import Callable

from .agent_gateway import get_adapter
from .agent_gateway.base import AgentCapabilities, AgentIdentity
from .agent_contracts import (
    AgentContractValidationError,
    validate_agent_contract_domain,
    validate_agent_contract_schema,
)
from .credential_store import (
    credential_protection,
    delete_credential,
    get_credential,
    has_credential,
    set_credential,
)
from .media import resolve_media_file
from .skill_policy import (
    build_provider_prompt,
    provider_output_schema,
    strip_json_fence,
)
from .storage import (
    connect,
    create_provider_attempt,
    initialise_database,
    update_provider_attempt,
)


ProviderEvent = Callable[[dict[str, Any]], None]

BUILTIN_MODEL_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "openai-codex-oauth",
        "display_name": "OpenAI · ChatGPT 登录",
        "provider_kind": "codex_oauth_bridge",
        "transport": "codex_app_server",
        "auth_mode": "oauth",
        "base_url": None,
        "config": {},
    },
)

class ModelProviderError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MODEL_PROVIDER_ERROR",
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_builtin_model_providers(home: Path) -> None:
    initialise_database(home)
    now = _now()
    with connect(home) as conn:
        legacy = conn.execute(
            "SELECT * FROM execution_profiles WHERE profile_id='codex-managed'"
        ).fetchone()
        for provider in BUILTIN_MODEL_PROVIDERS:
            legacy_config = (
                json.loads(legacy["config_json"])
                if legacy and provider["provider_id"] == "openai-codex-oauth"
                else {}
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO model_providers(
                  provider_id,display_name,provider_kind,transport,auth_mode,
                  base_url,model_id,reasoning_effort,role,fallback_order,
                  is_enabled,credential_ref,config_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    provider["provider_id"],
                    provider["display_name"],
                    provider["provider_kind"],
                    provider["transport"],
                    provider["auth_mode"],
                    provider.get("base_url"),
                    legacy["model_id"] if legacy else None,
                    legacy["reasoning_effort"] if legacy else None,
                    "primary" if legacy and legacy["is_default"] else "disabled",
                    None,
                    1,
                    None,
                    json.dumps(
                        {**provider.get("config", {}), **legacy_config},
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                ),
            )


def _provider_row(row: Any) -> dict[str, Any]:
    return {
        "provider_id": row["provider_id"],
        "display_name": row["display_name"],
        "provider_kind": row["provider_kind"],
        "transport": row["transport"],
        "auth_mode": row["auth_mode"],
        "base_url": row["base_url"],
        "model_id": row["model_id"],
        "reasoning_effort": row["reasoning_effort"],
        "role": row["role"],
        "fallback_order": row["fallback_order"],
        "is_enabled": bool(row["is_enabled"]),
        "credential_ref": row["credential_ref"],
        "config": json.loads(row["config_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_model_providers(
    home: Path,
    *,
    diagnostics: bool = False,
) -> list[dict[str, Any]]:
    ensure_builtin_model_providers(home)
    with connect(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM model_providers
            ORDER BY
              CASE role WHEN 'primary' THEN 0 WHEN 'fallback' THEN 1 ELSE 2 END,
              COALESCE(fallback_order,9999),
              display_name
            """
        ).fetchall()
    result = []
    for row in rows:
        provider = _provider_row(row)
        provider["credential_configured"] = has_credential(
            home, provider.get("credential_ref")
        )
        provider["credential_protection"] = credential_protection(
            home, provider.get("credential_ref")
        )
        provider["available"] = provider_available(home, provider)
        if diagnostics:
            provider["diagnostics"] = provider_diagnostics(home, provider)
        result.append(provider)
    return result


def get_model_provider(home: Path, provider_id: str) -> dict[str, Any] | None:
    ensure_builtin_model_providers(home)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM model_providers WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
    if not row:
        return None
    provider = _provider_row(row)
    provider["credential_configured"] = has_credential(
        home, provider.get("credential_ref")
    )
    provider["credential_protection"] = credential_protection(
        home, provider.get("credential_ref")
    )
    provider["available"] = provider_available(home, provider)
    return provider


def create_model_provider(
    home: Path,
    *,
    provider_id: str,
    display_name: str,
    provider_kind: str,
    base_url: str,
    model_id: str,
    auth_mode: str = "api_key",
    api_key: str | None = None,
    role: str = "disabled",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider_kind not in {"openai_compatible", "local_http"}:
        raise ValueError("Only HTTP model providers can be created by the user")
    if auth_mode not in {"api_key", "none"}:
        raise ValueError("HTTP providers support api_key or none authentication")
    _validate_provider_id(provider_id)
    if get_model_provider(home, provider_id):
        raise ValueError(f"Model provider already exists: {provider_id}")
    clean_url = _validate_base_url(base_url, provider_kind=provider_kind)
    clean_name = display_name.strip()
    if not clean_name:
        raise ValueError("Provider display name is required")
    clean_model = model_id.strip()
    if not clean_model:
        raise ValueError("Model ID is required")
    now = _now()
    credential_ref = (
        f"model-provider:{provider_id}:api-key" if auth_mode == "api_key" else None
    )
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO model_providers(
              provider_id,display_name,provider_kind,transport,auth_mode,
              base_url,model_id,reasoning_effort,role,fallback_order,
              is_enabled,credential_ref,config_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                provider_id,
                clean_name,
                provider_kind,
                "http",
                auth_mode,
                clean_url,
                clean_model,
                None,
                "disabled",
                None,
                1,
                credential_ref,
                json.dumps(_clean_config(config or {}), ensure_ascii=False),
                now,
                now,
            ),
        )
    if api_key:
        set_credential(home, str(credential_ref), api_key)
    if role != "disabled":
        update_model_provider(home, provider_id, role=role)
    provider = get_model_provider(home, provider_id)
    if not provider:  # pragma: no cover
        raise RuntimeError("Model provider disappeared during creation")
    return provider


def update_model_provider(
    home: Path,
    provider_id: str,
    *,
    display_name: str | None = None,
    base_url: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
    role: str | None = None,
    fallback_order: int | None = None,
    is_enabled: bool | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = get_model_provider(home, provider_id)
    if not current:
        raise ValueError(f"Unknown model provider: {provider_id}")
    if role is not None and role not in {"primary", "fallback", "disabled"}:
        raise ValueError("Provider role must be primary, fallback or disabled")
    enabled = current["is_enabled"] if is_enabled is None else bool(is_enabled)
    selected_role = current["role"] if role is None else role
    if selected_role in {"primary", "fallback"} and not enabled:
        raise ValueError("A disabled provider cannot be in the active model route")
    if (
        selected_role in {"primary", "fallback"}
        and current["auth_mode"] == "api_key"
        and not api_key
        and not has_credential(home, current.get("credential_ref"))
    ):
        raise ValueError(
            "Configure the provider API key before adding it to the active route"
        )
    clean_url = current["base_url"]
    if base_url is not None:
        clean_url = _validate_base_url(
            base_url,
            provider_kind=str(current["provider_kind"]),
        )
    clean_config = dict(current["config"])
    if config is not None:
        clean_config.update(_clean_config(config))
    clean_display_name = (
        display_name.strip()
        if display_name is not None
        else str(current["display_name"])
    )
    clean_model_id = (
        model_id.strip()
        if model_id is not None
        else current.get("model_id")
    )
    if not clean_display_name:
        raise ValueError("Provider display name is required")
    if current["provider_kind"] != "codex_oauth_bridge" and not clean_model_id:
        raise ValueError("Model ID is required")
    with connect(home) as conn:
        if selected_role == "primary":
            existing_primary = conn.execute(
                """
                SELECT provider_id FROM model_providers
                WHERE role='primary' AND is_enabled=1 AND provider_id<>?
                """,
                (provider_id,),
            ).fetchone()
            if existing_primary:
                maximum = conn.execute(
                    "SELECT COALESCE(MAX(fallback_order),0) AS value FROM model_providers"
                ).fetchone()["value"]
                conn.execute(
                    """
                    UPDATE model_providers
                    SET role='fallback',fallback_order=?,updated_at=?
                    WHERE provider_id=?
                    """,
                    (int(maximum) + 1, _now(), existing_primary["provider_id"]),
                )
        conn.execute(
            """
            UPDATE model_providers
            SET display_name=?,base_url=?,model_id=?,reasoning_effort=?,
                role=?,fallback_order=?,is_enabled=?,config_json=?,updated_at=?
            WHERE provider_id=?
            """,
            (
                clean_display_name,
                clean_url,
                clean_model_id,
                (
                    reasoning_effort
                    if reasoning_effort is not None
                    else current.get("reasoning_effort")
                ),
                selected_role,
                (
                    None
                    if selected_role != "fallback"
                    else fallback_order
                    if fallback_order is not None
                    else current.get("fallback_order")
                    or 1
                ),
                int(enabled),
                json.dumps(clean_config, ensure_ascii=False),
                _now(),
                provider_id,
            ),
        )
    credential_ref = current.get("credential_ref")
    if current["auth_mode"] == "api_key" and not credential_ref:
        credential_ref = f"model-provider:{provider_id}:api-key"
        with connect(home) as conn:
            conn.execute(
                "UPDATE model_providers SET credential_ref=? WHERE provider_id=?",
                (credential_ref, provider_id),
            )
    if api_key:
        set_credential(home, str(credential_ref), api_key)
    if clear_api_key:
        delete_credential(home, credential_ref)
    updated = get_model_provider(home, provider_id)
    if not updated:  # pragma: no cover
        raise RuntimeError("Model provider disappeared during update")
    return updated


def delete_model_provider(home: Path, provider_id: str) -> None:
    if provider_id == "openai-codex-oauth":
        raise ValueError("The built-in OpenAI login bridge cannot be deleted")
    provider = get_model_provider(home, provider_id)
    if not provider:
        raise ValueError(f"Unknown model provider: {provider_id}")
    if provider["role"] == "primary":
        raise ValueError("Select another primary model before deleting this one")
    with connect(home) as conn:
        conn.execute(
            "DELETE FROM model_providers WHERE provider_id=?",
            (provider_id,),
        )
    delete_credential(home, provider.get("credential_ref"))


def active_model_route(
    home: Path,
    *,
    provider_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_builtin_model_providers(home)
    if provider_id:
        selected = get_model_provider(home, provider_id)
        if (
            not selected
            or not selected["is_enabled"]
            or not provider_available(home, selected)
        ):
            raise ModelProviderError(
                "The selected model provider is unavailable",
                code="MODEL_PROVIDER_UNAVAILABLE",
            )
        return [selected]
    providers = list_model_providers(home)
    primary = next(
        (
            item
            for item in providers
            if item["role"] == "primary" and item["is_enabled"]
        ),
        None,
    )
    if not primary:
        raise ModelProviderError(
            "No primary model is configured. Choose an AI service in Settings.",
            code="MODEL_PROVIDER_REQUIRED",
        )
    fallbacks = [
        item
        for item in providers
        if item["role"] == "fallback" and item["is_enabled"]
    ]
    return [primary, *fallbacks]


def provider_available(home: Path, provider: dict[str, Any]) -> bool:
    if not provider["is_enabled"]:
        return False
    if provider["provider_kind"] == "codex_oauth_bridge":
        adapter = get_adapter("codex-managed")
        return bool(adapter.diagnostics(home, _codex_profile(provider)).get("available"))
    if not provider.get("base_url") or not provider.get("model_id"):
        return False
    if provider["auth_mode"] == "api_key":
        return has_credential(home, provider.get("credential_ref"))
    return True


def provider_diagnostics(home: Path, provider: dict[str, Any]) -> dict[str, Any]:
    if provider["provider_kind"] == "codex_oauth_bridge":
        result = get_adapter("codex-managed").diagnostics(
            home, _codex_profile(provider)
        )
        return {
            **result,
            "capabilities": asdict(_provider_capabilities(provider)),
            "health": provider_health_status(home, str(provider["provider_id"])),
        }
    return {
        "available": provider_available(home, provider),
        "base_url": provider.get("base_url"),
        "model_id": provider.get("model_id"),
        "credential_configured": has_credential(
            home, provider.get("credential_ref")
        ),
        "credential_protection": credential_protection(
            home, provider.get("credential_ref")
        ),
        "capabilities": asdict(_provider_capabilities(provider)),
        "health": provider_health_status(home, str(provider["provider_id"])),
        "boundary": (
            "This is a configuration check only. Use Test connection for a "
            "live provider request."
        ),
    }


def provider_health_status(home: Path, provider_id: str) -> dict[str, Any]:
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM provider_health WHERE provider_id=?", (provider_id,)
        ).fetchone()
    if row is None:
        return {
            "status": "unknown",
            "consecutive_failures": 0,
            "circuit_open_until": None,
        }
    open_until = row["circuit_open_until"]
    status = "healthy" if int(row["consecutive_failures"]) == 0 else "degraded"
    if open_until:
        try:
            parsed = datetime.fromisoformat(str(open_until))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > datetime.now(timezone.utc):
                status = "circuit_open"
        except ValueError:
            pass
    return {
        "status": status,
        "consecutive_failures": int(row["consecutive_failures"]),
        "circuit_open_until": open_until,
        "last_success_at": row["last_success_at"],
        "last_failure_at": row["last_failure_at"],
        "last_error_code": row["last_error_code"],
    }


def test_model_provider(home: Path, provider_id: str) -> dict[str, Any]:
    provider = get_model_provider(home, provider_id)
    if not provider:
        raise ValueError(f"Unknown model provider: {provider_id}")
    if provider["provider_kind"] == "codex_oauth_bridge":
        adapter = get_adapter("codex-managed")
        account = adapter.account(home, _codex_profile(provider))
        return {
            "ok": bool(account.get("account")) or not account.get("requiresOpenaiAuth"),
            "provider_id": provider_id,
            "account": account.get("account"),
            "model_id": provider.get("model_id"),
            "test_kind": "account_status",
        }
    models = _http_models(home, provider)
    configured_model = provider.get("model_id")
    model_ids = {
        str(item.get("id"))
        for item in models
        if isinstance(item, dict) and item.get("id")
    }
    return {
        "ok": True,
        "provider_id": provider_id,
        "model_id": configured_model,
        "model_visible": not model_ids or configured_model in model_ids,
        "model_count": len(models),
        "test_kind": "models_endpoint",
    }


def list_provider_models(home: Path, provider_id: str) -> list[dict[str, Any]]:
    provider = get_model_provider(home, provider_id)
    if not provider:
        raise ValueError(f"Unknown model provider: {provider_id}")
    if provider["provider_kind"] == "codex_oauth_bridge":
        result = get_adapter("codex-managed").models(
            home, _codex_profile(provider)
        )
        return list(result.get("data") or result.get("models") or [])
    return _http_models(home, provider)


class ModelProviderChainAdapter:
    """AgentAdapter-compatible facade for a primary model and fallbacks."""

    id = "model-provider-chain"
    label = "IELTS model provider route"

    def __init__(self, route: list[dict[str, Any]]) -> None:
        if not route:
            raise ValueError("Model provider route cannot be empty")
        self.route = route
        self._identity: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, dict[str, Any]] = {}
        self._validation: dict[str, dict[str, Any]] = {}
        self._active_adapter: dict[str, Any] = {}

    def probe(self) -> AgentCapabilities:
        capabilities = [_provider_capabilities(item) for item in self.route]
        return AgentCapabilities(
            structured_output=any(item.structured_output for item in capabilities),
            streaming=any(item.streaming for item in capabilities),
            session_resume=False,
            image_input=any(item.image_input for item in capabilities),
            audio_input=any(item.audio_input for item in capabilities),
            tool_execution=False,
            remote_processing=any(item.remote_processing for item in capabilities),
            cancellation=any(item.cancellation for item in capabilities),
            timeout_control=True,
        )

    def identity(self) -> AgentIdentity:
        primary = self.route[0]
        return AgentIdentity(
            agent_provider=_provider_name(primary),
            agent_version=None,
            model_id=primary.get("model_id"),
            model_display_name=primary.get("model_id"),
            launcher_kind="model_provider",
            calibration_status="unknown",
        )

    def start(self, home: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._start(home, request, emit=None)

    def start_with_events(
        self,
        home: Path,
        request: dict[str, Any],
        emit: ProviderEvent,
    ) -> dict[str, Any]:
        return self._start(home, request, emit=emit)

    def _start(
        self,
        home: Path,
        request: dict[str, Any],
        *,
        emit: ProviderEvent | None,
    ) -> dict[str, Any]:
        execution_ref = str(request["request_id"])
        contract = str(request.get("output_contract") or "")
        failures: list[dict[str, Any]] = []
        for index, provider in enumerate(self.route):
            if emit and index > 0:
                emit(
                    {
                        "stage": "fallback_started",
                        "label": "Trying fallback model",
                        "provider_id": provider["provider_id"],
                        "fallback_index": index,
                    }
                )
            if emit:
                emit(
                    {
                        "stage": "connecting_model",
                        "label": (
                            "Connecting primary model"
                            if index == 0
                            else "Trying fallback model"
                        ),
                        "provider_id": provider["provider_id"],
                    }
                )
            attempt = create_provider_attempt(
                home,
                run_id=execution_ref,
                provider_id=str(provider["provider_id"]),
                provider_kind=str(provider.get("provider_kind") or ""),
                model_id=provider.get("model_id"),
                fallback_index=index,
            )
            candidate: dict[str, Any] | None = None
            identity: dict[str, Any] = {}
            usage: dict[str, Any] = {}
            try:
                unsupported = _unsupported_media_types(provider, request)
                if unsupported:
                    names = ", ".join(sorted(unsupported))
                    exc = ModelProviderError(
                        f"Provider does not support required media: {names}",
                        code="MODEL_PROVIDER_CAPABILITY_MISMATCH",
                    )
                    exc.stage = "capability"
                    raise exc
                if provider["provider_kind"] == "codex_oauth_bridge":
                    adapter = get_adapter("codex-managed")
                    self._active_adapter[execution_ref] = adapter
                    provider_request = {
                        **request,
                        "execution_profile": _effective_codex_profile(provider, request),
                    }
                    start_with_events = getattr(adapter, "start_with_events", None)
                    candidate = (
                        start_with_events(home, provider_request, emit)
                        if callable(start_with_events) and emit
                        else adapter.start(home, provider_request)
                    )
                    identity = getattr(adapter, "execution_identity", lambda _: {})(
                        execution_ref
                    )
                    usage = getattr(adapter, "execution_usage", lambda _: {})(
                        execution_ref
                    )
                else:
                    candidate, usage = _http_invoke(
                        home, provider, request, emit=emit
                    )
                    identity = {
                        "agent_provider": _provider_name(provider),
                        "model_id": provider.get("model_id"),
                        "model_display_name": provider.get("model_id"),
                        "launcher_kind": "model_provider_http",
                    }
                if emit:
                    emit(
                        {
                            "stage": "schema_validation",
                            "label": "Checking structured response",
                            "provider_id": provider["provider_id"],
                        }
                    )
                structured = validate_agent_contract_schema(contract, candidate)
                if emit:
                    emit(
                        {
                            "stage": "domain_validation",
                            "label": "Checking IELTS teaching rules",
                            "provider_id": provider["provider_id"],
                        }
                    )
                validated = validate_agent_contract_domain(contract, structured)
                self._identity[execution_ref] = {
                    **identity,
                    "model_provider_id": provider["provider_id"],
                }
                self._usage[execution_ref] = {
                    **(usage or {}),
                    "model_provider_id": provider["provider_id"],
                    "fallback_index": index,
                }
                self._validation[execution_ref] = {
                    "validated": True,
                    "contract": contract,
                    "provider_attempt_id": attempt["attempt_id"],
                }
                update_provider_attempt(
                    home,
                    str(attempt["attempt_id"]),
                    status="validated",
                    result_hash=_result_hash(validated),
                    identity=identity,
                    usage=usage,
                    completed_at=_now(),
                )
                if emit:
                    emit(
                        {
                            "stage": "provider_validated",
                            "label": "Model response accepted",
                            "provider_id": provider["provider_id"],
                            "provider_attempt_id": attempt["attempt_id"],
                        }
                    )
                return validated
            except Exception as exc:
                code = str(getattr(exc, "code", "MODEL_PROVIDER_FAILED"))
                failure_stage = str(getattr(exc, "stage", "invocation"))
                status = (
                    "rejected"
                    if isinstance(exc, AgentContractValidationError)
                    else "skipped"
                    if failure_stage == "capability"
                    else "failed"
                )
                failures.append(
                    {
                        "provider_id": str(provider["provider_id"]),
                        "code": code,
                        "stage": failure_stage,
                        "message": str(exc)[-500:],
                        "status_code": getattr(exc, "status_code", None),
                        "retryable": bool(getattr(exc, "retryable", False)),
                    }
                )
                update_provider_attempt(
                    home,
                    str(attempt["attempt_id"]),
                    status=status,
                    failure_stage=failure_stage,
                    error_code=code,
                    error_message=str(exc)[-2000:],
                    result_hash=(
                        _result_hash(candidate) if candidate is not None else None
                    ),
                    identity=identity,
                    usage=usage,
                    completed_at=_now(),
                )
                if emit:
                    emit(
                        {
                            "stage": (
                                "provider_rejected"
                                if status == "rejected"
                                else "provider_skipped"
                                if status == "skipped"
                                else "provider_failed"
                            ),
                            "label": (
                                "Model response rejected"
                                if status == "rejected"
                                else "Model cannot handle this material"
                                if status == "skipped"
                                else "Model connection failed"
                            ),
                            "provider_id": provider["provider_id"],
                            "provider_attempt_id": attempt["attempt_id"],
                            "failure_stage": failure_stage,
                            "code": code,
                            "retryable": bool(getattr(exc, "retryable", False)),
                            "retry_after_seconds": getattr(
                                exc, "retry_after_seconds", None
                            ),
                            "will_try_fallback": index + 1 < len(self.route),
                        }
                    )
            finally:
                self._active_adapter.pop(execution_ref, None)
        detail = "; ".join(
            f"{item['provider_id']}: {item['message']}" for item in failures
        )
        raise ModelProviderError(
            f"Every configured model provider failed. {detail}",
            code="MODEL_ROUTE_FAILED",
            retryable=bool(failures)
            and all(bool(item.get("retryable")) for item in failures),
        )

    def stream(self, home: Path, execution_ref: str) -> list[dict[str, Any]]:
        return []

    def cancel(self, home: Path, execution_ref: str) -> bool:
        adapter = self._active_adapter.get(execution_ref)
        return bool(adapter and adapter.cancel(home, execution_ref))

    def resume(
        self,
        home: Path,
        execution_ref: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self.start(home, request)

    def execution_identity(self, execution_ref: str) -> dict[str, Any]:
        return dict(self._identity.pop(execution_ref, {}))

    def execution_usage(self, execution_ref: str) -> dict[str, Any]:
        return dict(self._usage.pop(execution_ref, {}))

    def execution_validation(self, execution_ref: str) -> dict[str, Any]:
        return dict(self._validation.pop(execution_ref, {}))

    def shutdown(self) -> None:
        get_adapter("codex-managed").shutdown()


def _unsupported_media_types(
    provider: dict[str, Any],
    request: dict[str, Any],
) -> set[str]:
    capabilities = _provider_capabilities(provider)
    required = {
        str(item.get("media_type"))
        for item in (request.get("media_refs") or [])
        if item.get("available_to_agent")
    }
    unsupported: set[str] = set()
    if "image" in required and not capabilities.image_input:
        unsupported.add("image")
    if "audio" in required and not capabilities.audio_input:
        unsupported.add("audio")
    return unsupported


def _result_hash(result: dict[str, Any]) -> str:
    payload = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _provider_capabilities(provider: dict[str, Any]) -> AgentCapabilities:
    if provider["provider_kind"] == "codex_oauth_bridge":
        return get_adapter("codex-managed").probe()
    config = provider.get("config") or {}
    return AgentCapabilities(
        structured_output=True,
        streaming=bool(config.get("streaming", False)),
        session_resume=False,
        image_input=bool(config.get("image_input", False)),
        audio_input=False,
        tool_execution=False,
        remote_processing=provider["provider_kind"] != "local_http",
        cancellation=bool(config.get("streaming", False)),
        timeout_control=True,
    )


def _http_models(home: Path, provider: dict[str, Any]) -> list[dict[str, Any]]:
    response = _http_json(
        home,
        provider,
        method="GET",
        endpoint="models",
        payload=None,
        timeout=20,
    )
    values = response.get("data") or response.get("models") or []
    return [item for item in values if isinstance(item, dict)]


def _http_invoke(
    home: Path,
    provider: dict[str, Any],
    request: dict[str, Any],
    *,
    emit: ProviderEvent | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system, user = build_provider_prompt(request)
    use_caching = bool(provider.get("config", {}).get("prompt_caching", False))
    system_content: str | list[dict[str, Any]] = (
        [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if use_caching
        else system
    )
    user_content: str | list[dict[str, Any]] = user
    if provider.get("config", {}).get("image_input"):
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for media in request.get("media_refs") or []:
            if (
                media.get("available_to_agent")
                and media.get("media_type") == "image"
            ):
                _, path = resolve_media_file(home, str(media["media_id"]))
                mime = media.get("mime_type") or mimetypes.guess_type(path.name)[0]
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime or 'image/png'};base64,{encoded}"
                        },
                    }
                )
        user_content = content
    schema = provider_output_schema(
        dict((request.get("skill_envelope") or {}).get("output_schema") or {})
    )
    use_streaming = bool(provider.get("config", {}).get("streaming", False))
    payload: dict[str, Any] = {
        "model": provider["model_id"],
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        "stream": use_streaming,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ielts_capability_result",
                "strict": True,
                "schema": schema,
            },
        },
    }
    if provider.get("config", {}).get("temperature") is not None:
        payload["temperature"] = provider["config"]["temperature"]
    if emit:
        emit({"stage": "generating", "label": "Model is producing feedback"})
    invoke = _http_stream_completion if use_streaming else _http_json
    try:
        response = invoke(
            home,
            provider,
            method="POST",
            endpoint="chat/completions",
            payload=payload,
            timeout=int(provider.get("config", {}).get("timeout_seconds", 300)),
            **({"emit": emit} if use_streaming else {}),
        )
    except ModelProviderError as exc:
        if exc.code != "MODEL_PROVIDER_BAD_REQUEST":
            raise
        payload["response_format"] = {"type": "json_object"}
        response = invoke(
            home,
            provider,
            method="POST",
            endpoint="chat/completions",
            payload=payload,
            timeout=int(provider.get("config", {}).get("timeout_seconds", 300)),
            **({"emit": emit} if use_streaming else {}),
        )
    choices = response.get("choices") or []
    if not choices:
        raise ModelProviderError(
            "The model provider returned no completion",
            code="MODEL_PROVIDER_INVALID_RESPONSE",
        )
    content_value = (choices[0].get("message") or {}).get("content")
    if isinstance(content_value, list):
        content_value = "".join(
            str(item.get("text") or "")
            for item in content_value
            if isinstance(item, dict)
        )
    if not isinstance(content_value, str):
        raise ModelProviderError(
            "The model provider returned no JSON text",
            code="MODEL_PROVIDER_INVALID_RESPONSE",
        )
    try:
        result = json.loads(strip_json_fence(content_value))
    except json.JSONDecodeError as exc:
        raise ModelProviderError(
            "The model provider response is not valid JSON",
            code="MODEL_PROVIDER_INVALID_JSON",
        ) from exc
    if not isinstance(result, dict):
        raise ModelProviderError(
            "The model provider must return one JSON object",
            code="MODEL_PROVIDER_INVALID_JSON",
        )
    return result, dict(response.get("usage") or {})


def _http_json(
    home: Path,
    provider: dict[str, Any],
    *,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    response = _open_provider_response(
        home,
        provider,
        method=method,
        endpoint=endpoint,
        payload=payload,
        timeout=timeout,
    )
    try:
        with response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _record_provider_failure(
            home,
            str(provider["provider_id"]),
            "MODEL_PROVIDER_CONNECTION_FAILED",
            retryable=True,
        )
        raise ModelProviderError(
            f"Model provider connection was interrupted: {exc}",
            code="MODEL_PROVIDER_CONNECTION_FAILED",
            retryable=True,
        ) from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        _record_provider_failure(
            home,
            str(provider["provider_id"]),
            "MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
        raise ModelProviderError(
            "The provider returned a non-JSON response",
            code="MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        ) from exc
    if not isinstance(result, dict):
        _record_provider_failure(
            home,
            str(provider["provider_id"]),
            "MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
        raise ModelProviderError(
            "The provider returned an invalid response object",
            code="MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
    _record_provider_success(home, str(provider["provider_id"]))
    return result


def _http_stream_completion(
    home: Path,
    provider: dict[str, Any],
    *,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None,
    timeout: int,
    emit: ProviderEvent | None,
) -> dict[str, Any]:
    response = _open_provider_response(
        home,
        provider,
        method=method,
        endpoint=endpoint,
        payload=payload,
        timeout=timeout,
    )
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    model_id = provider.get("model_id")
    last_emitted_chars = 0
    last_emit_at = time.monotonic()
    try:
        with response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = dict(event["usage"])
                if event.get("model"):
                    model_id = event["model"]
                choices = event.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    value = delta.get("content") if isinstance(delta, dict) else None
                    if value is None:
                        message = choice.get("message") or {}
                        value = (
                            message.get("content")
                            if isinstance(message, dict)
                            else None
                        )
                    if isinstance(value, str):
                        content_parts.append(value)
                    elif isinstance(value, list):
                        content_parts.extend(
                            str(item.get("text") or "")
                            for item in value
                            if isinstance(item, dict)
                        )
                char_count = sum(len(part) for part in content_parts)
                now = time.monotonic()
                if emit and (
                    char_count - last_emitted_chars >= 320
                    or now - last_emit_at >= 1.0
                ):
                    emit(
                        {
                            "stage": "streaming",
                            "label": "Model is drafting the response",
                            "characters_received": char_count,
                        }
                    )
                    last_emitted_chars = char_count
                    last_emit_at = now
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _record_provider_failure(
            home,
            str(provider["provider_id"]),
            "MODEL_PROVIDER_STREAM_INTERRUPTED",
            retryable=True,
        )
        raise ModelProviderError(
            f"The streaming model response was interrupted: {exc}",
            code="MODEL_PROVIDER_STREAM_INTERRUPTED",
            retryable=True,
        ) from exc
    content = "".join(content_parts)
    if not content:
        _record_provider_failure(
            home,
            str(provider["provider_id"]),
            "MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
        raise ModelProviderError(
            "The streaming provider returned no completion text",
            code="MODEL_PROVIDER_INVALID_RESPONSE",
            retryable=True,
        )
    _record_provider_success(home, str(provider["provider_id"]))
    return {
        "model": model_id,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage,
    }


def _open_provider_response(
    home: Path,
    provider: dict[str, Any],
    *,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None,
    timeout: int,
) -> Any:
    provider_id = str(provider["provider_id"])
    _guard_provider_circuit(home, provider_id)
    base_url = str(provider["base_url"]).rstrip("/") + "/"
    url = urllib.parse.urljoin(base_url, endpoint)
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if provider["auth_mode"] == "api_key":
        api_key = get_credential(home, provider.get("credential_ref"))
        if not api_key:
            raise ModelProviderError(
                "The provider API key is not configured",
                code="MODEL_PROVIDER_AUTH_REQUIRED",
            )
        headers["Authorization"] = f"Bearer {api_key}"
    retries = int(provider.get("config", {}).get("max_retries", 2))
    retries = max(0, min(retries, 3))
    last_error: ModelProviderError | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            return urllib.request.urlopen(request, timeout=max(1, timeout))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[-1200:]
            if provider["auth_mode"] == "api_key":
                message = message.replace(str(api_key), "[redacted]")
            retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            code = (
                "MODEL_PROVIDER_AUTH_FAILED"
                if exc.code in {401, 403}
                else "MODEL_PROVIDER_RATE_LIMITED"
                if exc.code == 429
                else "MODEL_PROVIDER_BAD_REQUEST"
                if exc.code in {400, 404, 405, 422}
                else "MODEL_PROVIDER_UNAVAILABLE"
                if retryable
                else "MODEL_PROVIDER_HTTP_ERROR"
            )
            last_error = ModelProviderError(
                f"Provider HTTP {exc.code}: {message}",
                code=code,
                status_code=int(exc.code),
                retry_after_seconds=retry_after,
                retryable=retryable,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = ModelProviderError(
                f"Cannot connect to model provider: {exc}",
                code="MODEL_PROVIDER_CONNECTION_FAILED",
                retryable=True,
            )
        if last_error.retryable and attempt < retries:
            delay = (
                last_error.retry_after_seconds
                if last_error.retry_after_seconds is not None
                else 0.5 * (2**attempt) + random.uniform(0.0, 0.25)
            )
            time.sleep(max(0.0, min(float(delay), 30.0)))
            continue
        _record_provider_failure(
            home,
            provider_id,
            last_error.code,
            retryable=last_error.retryable,
            retry_after_seconds=last_error.retry_after_seconds,
        )
        raise last_error
    raise RuntimeError("Unreachable provider retry state")  # pragma: no cover


def _guard_provider_circuit(home: Path, provider_id: str) -> None:
    with connect(home) as conn:
        row = conn.execute(
            "SELECT circuit_open_until FROM provider_health WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
    if not row or not row["circuit_open_until"]:
        return
    try:
        open_until = datetime.fromisoformat(str(row["circuit_open_until"]))
        if open_until.tzinfo is None:
            open_until = open_until.replace(tzinfo=timezone.utc)
    except ValueError:
        return
    now = datetime.now(timezone.utc)
    if open_until > now:
        raise ModelProviderError(
            "The model provider circuit is temporarily open after repeated failures.",
            code="MODEL_PROVIDER_CIRCUIT_OPEN",
            retry_after_seconds=(open_until - now).total_seconds(),
            retryable=True,
        )


def _record_provider_success(home: Path, provider_id: str) -> None:
    now = _now()
    with connect(home) as conn:
        conn.execute(
            """
            INSERT INTO provider_health(
              provider_id,consecutive_failures,circuit_open_until,last_success_at,
              last_failure_at,last_error_code,updated_at
            ) VALUES(?,0,NULL,?,NULL,NULL,?)
            ON CONFLICT(provider_id) DO UPDATE SET
              consecutive_failures=0,circuit_open_until=NULL,
              last_success_at=excluded.last_success_at,last_error_code=NULL,
              updated_at=excluded.updated_at
            """,
            (provider_id, now, now),
        )


def _record_provider_failure(
    home: Path,
    provider_id: str,
    error_code: str,
    *,
    retryable: bool,
    retry_after_seconds: float | None = None,
) -> None:
    now_value = datetime.now(timezone.utc)
    with connect(home) as conn:
        row = conn.execute(
            "SELECT consecutive_failures FROM provider_health WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
        previous = int(row["consecutive_failures"]) if row else 0
        failures = previous + 1 if retryable else previous
        open_until = None
        if retryable and failures >= 3:
            cooldown = max(60.0, float(retry_after_seconds or 0.0))
            open_until = (now_value + timedelta(seconds=min(cooldown, 900))).isoformat()
        conn.execute(
            """
            INSERT INTO provider_health(
              provider_id,consecutive_failures,circuit_open_until,last_success_at,
              last_failure_at,last_error_code,updated_at
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(provider_id) DO UPDATE SET
              consecutive_failures=excluded.consecutive_failures,
              circuit_open_until=excluded.circuit_open_until,
              last_failure_at=excluded.last_failure_at,
              last_error_code=excluded.last_error_code,
              updated_at=excluded.updated_at
            """,
            (
                provider_id,
                failures,
                open_until,
                None,
                now_value.isoformat(),
                error_code,
                now_value.isoformat(),
            ),
        )


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _codex_profile(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": provider["provider_id"],
        "display_name": provider["display_name"],
        "backend_kind": "model_provider",
        "backend_id": "codex-managed",
        "transport": provider["transport"],
        "auth_mode": provider["auth_mode"],
        "model_id": provider.get("model_id"),
        "reasoning_effort": provider.get("reasoning_effort"),
        "config": provider.get("config") or {},
    }


def _effective_codex_profile(
    provider: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    profile = _codex_profile(provider)
    requested = (request.get("runtime_hints") or {}).get("reasoning_effort")
    if requested in {"minimal", "low", "medium", "high", "xhigh"}:
        profile["reasoning_effort"] = requested
    return profile


def _provider_name(provider: dict[str, Any]) -> str:
    if provider["provider_kind"] == "codex_oauth_bridge":
        return "openai"
    host = urllib.parse.urlparse(str(provider.get("base_url") or "")).hostname
    return host or str(provider["display_name"])


def _clean_config(config: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "image_input",
        "temperature",
        "timeout_seconds",
        "max_retries",
        "streaming",
        "executable_path",
    }
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(
            "Unsupported model provider setting: " + ", ".join(sorted(unknown))
        )
    clean = {key: value for key, value in config.items() if value is not None}
    if "timeout_seconds" in clean:
        clean["timeout_seconds"] = max(5, min(int(clean["timeout_seconds"]), 1800))
    if "temperature" in clean:
        clean["temperature"] = max(0.0, min(float(clean["temperature"]), 2.0))
    if "image_input" in clean:
        clean["image_input"] = bool(clean["image_input"])
    if "streaming" in clean:
        clean["streaming"] = bool(clean["streaming"])
    if "max_retries" in clean:
        clean["max_retries"] = max(0, min(int(clean["max_retries"]), 3))
    return clean


def _validate_provider_id(provider_id: str) -> None:
    if not provider_id or len(provider_id) > 120:
        raise ValueError("Provider ID must contain 1 to 120 characters")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in provider_id):
        raise ValueError(
            "Provider ID may contain lowercase letters, numbers, hyphens and underscores"
        )


def _validate_base_url(value: str, *, provider_kind: str) -> str:
    clean = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must be an absolute HTTP or HTTPS URL")
    if provider_kind == "openai_compatible" and parsed.scheme != "https":
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "Remote OpenAI-compatible providers must use HTTPS"
            )
    if (
        provider_kind == "local_http"
        and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("Local HTTP providers must use a loopback address")
    return clean
