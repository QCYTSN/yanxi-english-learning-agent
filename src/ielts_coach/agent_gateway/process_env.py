from __future__ import annotations

import os


_PROXY_ENVIRONMENT_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _normalise_proxy_url(value: str, *, socks: bool = False) -> str:
    value = value.strip()
    if not value or "://" in value:
        return value
    return f"{'socks5' if socks else 'http'}://{value}"


def _proxy_environment_from_windows_value(value: str) -> dict[str, str]:
    """Translate the WinINET ProxyServer value into CLI-friendly variables."""
    value = value.strip()
    if not value:
        return {}
    proxies: dict[str, str] = {}
    if "=" not in value:
        proxy = _normalise_proxy_url(value)
        proxies.update({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy})
    else:
        entries = {}
        for item in value.split(";"):
            protocol, separator, endpoint = item.partition("=")
            if separator and endpoint.strip():
                entries[protocol.strip().lower()] = endpoint.strip()
        if entries.get("http"):
            proxies["HTTP_PROXY"] = _normalise_proxy_url(entries["http"])
        if entries.get("https"):
            proxies["HTTPS_PROXY"] = _normalise_proxy_url(entries["https"])
        if entries.get("socks"):
            proxies["ALL_PROXY"] = _normalise_proxy_url(
                entries["socks"], socks=True
            )
    for key, proxy in list(proxies.items()):
        proxies[key.lower()] = proxy
    return proxies


def _windows_system_proxy_environment() -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            value = str(winreg.QueryValueEx(key, "ProxyServer")[0])
    except (ImportError, OSError, TypeError, ValueError):
        return {}
    return _proxy_environment_from_windows_value(value) if enabled else {}


def process_environment(overrides: dict[str, str]) -> dict[str, str]:
    """Subprocess environment for the managed Codex runtime, honouring the
    Windows system proxy so the app-server bridge can reach OpenAI."""
    environment = dict(os.environ)
    system_proxy = _windows_system_proxy_environment()
    for key in _PROXY_ENVIRONMENT_KEYS:
        if system_proxy.get(key):
            environment.setdefault(key, system_proxy[key])
    environment.update(overrides)
    return environment
