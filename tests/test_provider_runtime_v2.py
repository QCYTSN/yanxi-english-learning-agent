from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ielts_coach.capabilities import get_capability
from ielts_coach.credential_store import get_credential
from ielts_coach.inference import InferenceBroker
from ielts_coach.init_home import initialise_home
from ielts_coach.model_providers import (
    ModelProviderChainAdapter,
    _effective_codex_profile,
    active_model_route,
    create_model_provider,
    list_model_providers,
    update_model_provider,
)
from ielts_coach.skill_policy import compile_skill_envelope, provider_output_schema
from ielts_coach.storage import (
    connect,
    create_agent_run,
    get_agent_run,
    list_provider_attempts,
)
from ielts_coach.web.app import create_app
from ielts_coach.web.auth import AuthState


def _client(home: Path) -> TestClient:
    app = create_app(
        home=home,
        auth=AuthState(launch_token="test-launch-token-that-is-long-enough"),
        allowed_origin="http://testserver",
        test_mode=True,
    )
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})
    response = client.post(
        "/api/auth/exchange",
        json={"token": "test-launch-token-that-is-long-enough"},
    )
    assert response.status_code == 200
    return client


def test_unknown_api_route_never_falls_through_to_spa_html(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        response = client.get("/api/v1/not-a-real-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "API_ENDPOINT_NOT_FOUND"


def test_model_provider_secret_is_outside_sqlite_and_route_is_explicit(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="custom-test",
        display_name="Custom test",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="test-secret",
        role="primary",
    )

    assert provider["credential_configured"] is True
    assert get_credential(home, provider["credential_ref"]) == "test-secret"
    assert active_model_route(home)[0]["provider_id"] == "custom-test"
    with connect(home) as conn:
        row = conn.execute(
            "SELECT * FROM model_providers WHERE provider_id='custom-test'"
        ).fetchone()
        database_dump = json.dumps(dict(row))
    assert "test-secret" not in database_dump


def test_external_agents_cannot_become_teaching_inference(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    broker = InferenceBroker(home)

    with pytest.raises(ValueError, match="cannot evaluate IELTS"):
        broker.prepare(execution_profile_id="claude-cli")

    external = broker.external_agents(include_diagnostics=False)
    assert external
    assert all(item["teaching_model_eligible"] is False for item in external)


def test_skill_compiler_includes_full_policy_references_and_schema():
    envelope = compile_skill_envelope(get_capability("writing_review"))
    descriptor = envelope.descriptor()

    assert descriptor["skill"] == "ielts-writing"
    assert len(descriptor["source_hash"]) == 64
    assert "Workflow contract" in descriptor["instructions"]
    assert any(
        item["path"] == "references/scoring-policy.md"
        for item in descriptor["references"]
    )
    assert descriptor["allowed_tools"] == []
    assert descriptor["context_policy"]["persistence_owner"] == (
        "ielts_teaching_runtime"
    )
    assert descriptor["output_schema"]["type"] == "object"


def test_provider_schema_compiler_adds_strict_types_and_required_fields():
    envelope = compile_skill_envelope(get_capability("study_material_help"))
    schema = provider_output_schema(envelope.output_schema)

    assert "$schema" not in schema
    assert schema["properties"]["contract_version"]["type"] == "integer"
    assert schema["properties"]["module"]["type"] == "string"
    evidence_item = schema["properties"]["evidence"]["items"]
    assert evidence_item["required"] == ["claim", "source", "quote"]
    assert evidence_item["additionalProperties"] is False


def test_runtime_effort_override_does_not_mutate_provider_configuration():
    provider = {
        "provider_id": "openai-codex-oauth",
        "display_name": "OpenAI login",
        "transport": "app_server",
        "auth_mode": "oauth",
        "model_id": "gpt-test",
        "reasoning_effort": "high",
        "config": {},
    }

    effective = _effective_codex_profile(
        provider,
        {"runtime_hints": {"reasoning_effort": "low"}},
    )

    assert effective["reasoning_effort"] == "low"
    assert provider["reasoning_effort"] == "high"


def test_provider_and_learning_intent_endpoints_are_product_facing(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    with _client(home) as client:
        created = client.post(
            "/api/v1/model-providers",
            json={
                "provider_id": "api-endpoint-test",
                "display_name": "Endpoint test",
                "provider_kind": "openai_compatible",
                "base_url": "https://example.test/v1",
                "model_id": "model-test",
                "auth_mode": "api_key",
                "api_key": "endpoint-secret",
                "role": "primary",
                "config": {},
            },
        )
        providers = client.get("/api/v1/model-providers")
        bootstrap = client.get("/api/v1/bootstrap")
        external = client.get("/api/v1/external-agents")
        intent = client.post(
            "/api/v1/today/intent",
            json={"text": "我想练一篇阅读"},
        )

    assert created.status_code == 200
    assert "endpoint-secret" not in created.text
    assert providers.status_code == 200
    assert "endpoint-secret" not in providers.text
    assert bootstrap.json()["ai_setup_required"] is False
    assert all(
        item["teaching_model_eligible"] is False for item in external.json()
    )
    assert intent.json()["route"] == "/practice?module=reading"
    assert intent.json()["model_called"] is False


def test_builtin_provider_starts_disabled_on_a_clean_home(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    providers = list_model_providers(home)
    openai = next(
        item
        for item in providers
        if item["provider_id"] == "openai-codex-oauth"
    )
    assert openai["role"] == "disabled"


def test_agent_run_persists_provider_route_and_skill_provenance(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    create_model_provider(
        home,
        provider_id="run-provider",
        display_name="Run provider",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        api_key="test-secret",
        role="primary",
    )
    create_agent_run(
        home,
        {
            "run_id": "run-provider-provenance",
            "adapter_id": "model-provider-chain",
            "model_provider_id": "run-provider",
            "backend_kind": "model_provider",
            "action": "review",
            "output_contract": "writing-review@1",
            "status": "queued",
            "skill_hash": "a" * 64,
            "inference_route": ["run-provider"],
        },
    )

    run = get_agent_run(home, "run-provider-provenance")
    assert run is not None
    assert run["model_provider_id"] == "run-provider"
    assert run["skill_hash"] == "a" * 64
    assert run["inference_route"] == ["run-provider"]


def test_provider_route_requires_credentials_and_preserves_reasoning(
    tmp_path: Path,
):
    home = tmp_path / "home"
    initialise_home(home)
    provider = create_model_provider(
        home,
        provider_id="route-guard",
        display_name="Route guard",
        provider_kind="openai_compatible",
        base_url="https://example.test/v1",
        model_id="model-test",
        role="disabled",
    )

    with pytest.raises(ValueError, match="API key"):
        update_model_provider(home, provider["provider_id"], role="primary")

    updated = update_model_provider(
        home,
        provider["provider_id"],
        api_key="secret",
        role="primary",
        reasoning_effort="high",
    )
    assert updated["reasoning_effort"] == "high"
    updated = update_model_provider(
        home,
        provider["provider_id"],
        display_name="Renamed provider",
    )
    assert updated["reasoning_effort"] == "high"
    assert active_model_route(home)[0]["provider_id"] == provider["provider_id"]

    with pytest.raises(ValueError, match="loopback"):
        create_model_provider(
            home,
            provider_id="not-local",
            display_name="Not local",
            provider_kind="local_http",
            base_url="http://192.0.2.1:11434/v1",
            model_id="model-test",
            auth_mode="none",
        )


def _study_plan(*, valid: bool = True) -> dict[str, object]:
    return {
        "contract_version": 1,
        "period": "2026-W31",
        "allocation": {
            "listening": 0.25 if valid else 0.5,
            "reading": 0.25 if valid else 0.5,
            "writing": 0.25 if valid else 0.5,
            "speaking": 0.25 if valid else 0.5,
        },
        "tasks": [
            {
                "module": "reading",
                "title": "Evidence review",
                "minutes": 30,
                "reason": "Current priority",
            }
        ],
        "evidence_summary": ["One eligible Reading sample."],
    }


@pytest.mark.parametrize(
    ("invalid_candidate", "expected_stage"),
    [
        ({"contract_version": 1}, "schema"),
        (_study_plan(valid=False), "domain"),
    ],
)
def test_provider_route_falls_back_after_contract_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_candidate: dict[str, object],
    expected_stage: str,
):
    home = tmp_path / "home"
    initialise_home(home)
    create_model_provider(
        home,
        provider_id="invalid-primary",
        display_name="Invalid primary",
        provider_kind="openai_compatible",
        base_url="https://primary.example.test/v1",
        model_id="primary-model",
        api_key="primary-secret",
        role="primary",
    )
    create_model_provider(
        home,
        provider_id="valid-fallback",
        display_name="Valid fallback",
        provider_kind="openai_compatible",
        base_url="https://fallback.example.test/v1",
        model_id="fallback-model",
        api_key="fallback-secret",
        role="fallback",
    )
    run_id = f"run-validation-{expected_stage}"
    create_agent_run(
        home,
        {
            "run_id": run_id,
            "adapter_id": "model-provider-chain",
            "backend_kind": "model_provider",
            "action": "plan",
            "output_contract": "study-plan@1",
            "status": "running",
            "inference_route": ["invalid-primary", "valid-fallback"],
        },
    )
    calls: list[str] = []

    def fake_invoke(home_arg, provider, request, *, emit):
        del home_arg, request, emit
        calls.append(provider["provider_id"])
        if provider["provider_id"] == "invalid-primary":
            return invalid_candidate, {"input_tokens": 10}
        return _study_plan(), {"input_tokens": 12, "output_tokens": 18}

    monkeypatch.setattr(
        "ielts_coach.model_providers._http_invoke",
        fake_invoke,
    )
    route = active_model_route(home)
    adapter = ModelProviderChainAdapter(route)
    events: list[dict[str, object]] = []

    result = adapter.start_with_events(
        home,
        {
            "request_id": run_id,
            "output_contract": "study-plan@1",
            "media_refs": [],
        },
        events.append,
    )

    assert result == _study_plan()
    assert calls == ["invalid-primary", "valid-fallback"]
    attempts = list_provider_attempts(home, run_id)
    assert [item["status"] for item in attempts] == ["rejected", "validated"]
    assert attempts[0]["failure_stage"] == expected_stage
    assert attempts[0]["error_code"] == (
        "AGENT_OUTPUT_SCHEMA_INVALID"
        if expected_stage == "schema"
        else "AGENT_OUTPUT_DOMAIN_INVALID"
    )
    assert len(attempts[1]["result_hash"]) == 64
    assert adapter.execution_identity(run_id)["model_provider_id"] == (
        "valid-fallback"
    )
    assert adapter.execution_usage(run_id)["fallback_index"] == 1
    assert adapter.execution_validation(run_id)["validated"] is True
    assert any(item["stage"] == "provider_rejected" for item in events)
    assert any(item["stage"] == "fallback_started" for item in events)
    assert any(item["stage"] == "provider_validated" for item in events)


def test_provider_route_skips_media_incompatible_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    home = tmp_path / "home"
    initialise_home(home)
    create_model_provider(
        home,
        provider_id="text-primary",
        display_name="Text primary",
        provider_kind="openai_compatible",
        base_url="https://text.example.test/v1",
        model_id="text-model",
        api_key="text-secret",
        role="primary",
    )
    create_model_provider(
        home,
        provider_id="vision-fallback",
        display_name="Vision fallback",
        provider_kind="openai_compatible",
        base_url="https://vision.example.test/v1",
        model_id="vision-model",
        api_key="vision-secret",
        role="fallback",
        config={"image_input": True},
    )
    run_id = "run-media-capability"
    create_agent_run(
        home,
        {
            "run_id": run_id,
            "adapter_id": "model-provider-chain",
            "backend_kind": "model_provider",
            "action": "plan",
            "output_contract": "study-plan@1",
            "status": "running",
        },
    )
    calls: list[str] = []

    def fake_invoke(home_arg, provider, request, *, emit):
        del home_arg, request, emit
        calls.append(provider["provider_id"])
        return _study_plan(), {}

    monkeypatch.setattr(
        "ielts_coach.model_providers._http_invoke",
        fake_invoke,
    )
    adapter = ModelProviderChainAdapter(active_model_route(home))
    assert adapter.probe().image_input is True
    adapter.start(
        home,
        {
            "request_id": run_id,
            "output_contract": "study-plan@1",
            "media_refs": [
                {
                    "media_id": "image-1",
                    "media_type": "image",
                    "available_to_agent": True,
                }
            ],
        },
    )

    assert calls == ["vision-fallback"]
    attempts = list_provider_attempts(home, run_id)
    assert attempts[0]["status"] == "skipped"
    assert attempts[0]["failure_stage"] == "capability"
    assert attempts[1]["status"] == "validated"
