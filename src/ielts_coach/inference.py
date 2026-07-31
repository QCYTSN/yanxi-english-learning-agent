from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_gateway import get_adapter, shutdown_adapters
from .agent_gateway.base import AgentAdapter
from .execution_profiles import (
    get_execution_profile,
    list_execution_profiles,
    resolve_execution_profile,
)
from .external_agents import list_external_agent_profiles
from .model_providers import (
    ModelProviderChainAdapter,
    active_model_route,
    get_model_provider,
    list_model_providers,
)


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    profile: dict[str, Any]
    adapter: AgentAdapter
    model_route: tuple[dict[str, Any], ...] = ()

    @property
    def capabilities(self) -> dict[str, Any]:
        return asdict(self.adapter.probe())

    @property
    def identity(self) -> dict[str, Any]:
        return asdict(self.adapter.identity())

    @property
    def primary_model_provider(self) -> dict[str, Any] | None:
        return self.model_route[0] if self.model_route else None


class InferenceBroker:
    """Resolve an IELTS Capability onto the active model provider route.

    Teaching inference and External Agents are deliberately separate.  The
    compatibility execution profile table remains readable for old records,
    pipeline tests and Manual handoff, but a CLI Agent cannot become the active
    IELTS teaching model.
    """

    def __init__(self, home: Path) -> None:
        self.home = home

    def prepare(
        self,
        *,
        model_provider_id: str | None = None,
        execution_profile_id: str | None = None,
        legacy_adapter_id: str | None = None,
    ) -> PreparedExecution:
        if model_provider_id:
            return self._prepare_model_route(
                active_model_route(self.home, provider_id=model_provider_id)
            )
        if execution_profile_id or legacy_adapter_id:
            profile = resolve_execution_profile(
                self.home,
                profile_id=execution_profile_id,
                legacy_adapter_id=legacy_adapter_id,
            )
            if profile["backend_kind"] == "managed_runtime":
                return self._prepare_model_route(
                    active_model_route(
                        self.home,
                        provider_id="openai-codex-oauth",
                    )
                )
            if profile["backend_kind"] == "external_agent":
                raise ValueError(
                    "External CLI Agents cannot evaluate IELTS learning tasks. "
                    "Choose a primary model provider; use External Agents only "
                    "for material and developer workflows."
                )
            if profile["backend_kind"] in {"mock", "manual"}:
                return PreparedExecution(
                    profile=profile,
                    adapter=get_adapter(str(profile["backend_id"])),
                )
            raise ValueError(
                f"Legacy execution backend {profile['backend_kind']} is not "
                "eligible for teaching inference"
            )
        return self._prepare_model_route(active_model_route(self.home))

    def _prepare_model_route(
        self,
        route: list[dict[str, Any]],
    ) -> PreparedExecution:
        primary = route[0]
        profile = {
            "profile_id": f"model-route:{primary['provider_id']}",
            "display_name": primary["display_name"],
            "backend_kind": "model_provider",
            "backend_id": "model-provider-chain",
            "transport": primary["transport"],
            "auth_mode": primary["auth_mode"],
            "model_id": primary.get("model_id"),
            "reasoning_effort": primary.get("reasoning_effort"),
            "is_enabled": primary["is_enabled"],
            "is_default": primary["role"] == "primary",
            "config": {},
        }
        return PreparedExecution(
            profile=profile,
            adapter=ModelProviderChainAdapter(route),
            model_route=tuple(route),
        )

    def for_run(self, run: dict[str, Any]) -> PreparedExecution:
        route_ids = [
            str(item)
            for item in (run.get("inference_route") or [])
            if item
        ]
        if route_ids:
            route = [
                provider
                for provider_id in route_ids
                if (provider := get_model_provider(self.home, provider_id))
                and provider["is_enabled"]
            ]
            if route:
                return self._prepare_model_route(route)
        return self.prepare(
            model_provider_id=run.get("model_provider_id"),
            execution_profile_id=run.get("execution_profile_id"),
            legacy_adapter_id=run.get("adapter_id"),
        )

    def model_providers(
        self,
        *,
        include_diagnostics: bool = True,
    ) -> list[dict[str, Any]]:
        return list_model_providers(
            self.home,
            diagnostics=include_diagnostics,
        )

    def external_agents(
        self,
        *,
        include_diagnostics: bool = True,
    ) -> list[dict[str, Any]]:
        return list_external_agent_profiles(
            self.home,
            diagnostics=include_diagnostics,
        )

    def profiles(self, *, include_diagnostics: bool = True) -> list[dict[str, Any]]:
        """Compatibility view for old clients and persisted runs."""
        profiles = []
        for profile in list_execution_profiles(self.home):
            adapter = get_adapter(str(profile["backend_id"]))
            descriptor = {
                **profile,
                "capabilities": asdict(adapter.probe()),
                "identity": asdict(adapter.identity()),
                "available": True,
                "teaching_model_eligible": profile["backend_kind"]
                in {"managed_runtime", "mock", "manual"},
                "deprecated_for_teaching": profile["backend_kind"]
                == "external_agent",
            }
            if include_diagnostics:
                diagnostics = getattr(adapter, "diagnostics", None)
                if callable(diagnostics):
                    try:
                        descriptor["diagnostics"] = diagnostics(
                            self.home, profile
                        )
                    except TypeError:
                        descriptor["diagnostics"] = diagnostics()
                    descriptor["available"] = bool(
                        descriptor["diagnostics"].get(
                            "available", descriptor["available"]
                        )
                    )
            else:
                descriptor["available"] = bool(
                    getattr(adapter, "available", lambda: True)()
                )
            profiles.append(descriptor)
        return profiles

    def profile(self, profile_id: str) -> dict[str, Any]:
        profile = get_execution_profile(self.home, profile_id)
        if not profile:
            raise ValueError(f"Unknown execution profile: {profile_id}")
        return profile

    def managed_codex(
        self,
        profile_id: str = "codex-managed",
    ) -> tuple[Any, dict[str, Any]]:
        del profile_id
        provider = get_model_provider(self.home, "openai-codex-oauth")
        if not provider:
            raise ValueError("The OpenAI OAuth provider bridge is unavailable")
        profile = {
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
        return get_adapter("codex-managed"), profile

    def shutdown(self) -> None:
        shutdown_adapters()
