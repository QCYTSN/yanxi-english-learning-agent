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
    active_model_route,
    create_model_provider,
    list_model_providers,
    update_model_provider,
)
from ielts_coach.skill_policy import compile_skill_envelope, provider_output_schema
from ielts_coach.storage import connect, create_agent_run, get_agent_run
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
