from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STORE_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(home: Path) -> Path:
    path = home / "private" / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    return path


def _load(home: Path) -> dict[str, Any]:
    path = _store_path(home)
    if not path.is_file():
        return {"store_version": STORE_VERSION, "items": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Local credential store is unreadable: {exc}") from exc
    if payload.get("store_version") != STORE_VERSION:
        raise ValueError("Unsupported local credential store version")
    payload.setdefault("items", {})
    return payload


def _save(home: Path, payload: dict[str, Any]) -> None:
    path = _store_path(home)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_credential(home: Path, credential_ref: str, secret: str) -> None:
    clean = secret.strip()
    if not clean:
        raise ValueError("Credential cannot be empty")
    payload = _load(home)
    if os.name != "nt" and _set_keyring_credential(home, credential_ref, clean):
        payload["items"][credential_ref] = {
            "ciphertext": "",
            "protection": "system_keyring",
            "updated_at": _now(),
        }
        _save(home, payload)
        return
    encrypted, protection = _protect(home, clean.encode("utf-8"))
    payload["items"][credential_ref] = {
        "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        "protection": protection,
        "updated_at": _now(),
    }
    _save(home, payload)


def get_credential(home: Path, credential_ref: str | None) -> str | None:
    if not credential_ref:
        return None
    item = _load(home).get("items", {}).get(credential_ref)
    if not item:
        return None
    if item.get("protection") == "system_keyring":
        value = _get_keyring_credential(home, credential_ref)
        if value is None:
            raise ValueError(
                f"Credential {credential_ref!r} is missing from the system keyring"
            )
        return value
    try:
        ciphertext = base64.b64decode(item["ciphertext"])
        clear = _unprotect(home, ciphertext, str(item["protection"]))
        return clear.decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"Credential {credential_ref!r} cannot be decrypted on this device"
        ) from exc


def has_credential(home: Path, credential_ref: str | None) -> bool:
    if not credential_ref:
        return False
    item = _load(home).get("items", {}).get(credential_ref)
    if not item:
        return False
    if item.get("protection") == "system_keyring":
        return _get_keyring_credential(home, credential_ref) is not None
    return True


def delete_credential(home: Path, credential_ref: str | None) -> None:
    if not credential_ref:
        return
    payload = _load(home)
    removed = payload.get("items", {}).pop(credential_ref, None)
    if removed and removed.get("protection") == "system_keyring":
        _delete_keyring_credential(home, credential_ref)
    if removed is not None:
        _save(home, payload)


def credential_protection(
    home: Path | None = None, credential_ref: str | None = None
) -> str:
    if home is not None and credential_ref:
        item = _load(home).get("items", {}).get(credential_ref)
        if item and item.get("protection"):
            return str(item["protection"])
    if os.name == "nt":
        return "windows_dpapi"
    return "system_keyring" if _keyring_module() is not None else "owner_only_file"


def _keyring_module() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]

        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0) or 0) <= 0:
            return None
        return keyring
    except (ImportError, RuntimeError, ValueError):
        return None


def _keyring_service(home: Path) -> str:
    digest = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:20]
    return f"ielts-ai-coach:{digest}"


def _set_keyring_credential(home: Path, credential_ref: str, secret: str) -> bool:
    keyring = _keyring_module()
    if keyring is None:
        return False
    try:
        keyring.set_password(_keyring_service(home), credential_ref, secret)
        return True
    except Exception:
        return False


def _get_keyring_credential(home: Path, credential_ref: str) -> str | None:
    keyring = _keyring_module()
    if keyring is None:
        return None
    try:
        return keyring.get_password(_keyring_service(home), credential_ref)
    except Exception:
        return None


def _delete_keyring_credential(home: Path, credential_ref: str) -> None:
    keyring = _keyring_module()
    if keyring is None:
        return
    try:
        keyring.delete_password(_keyring_service(home), credential_ref)
    except Exception:
        return


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _entropy(home: Path) -> bytes:
    return (
        "ielts-ai-coach|"
        + str(home.resolve())
        + "|"
        + platform.node()
    ).encode("utf-8")


def _protect(home: Path, value: bytes) -> tuple[bytes, str]:
    if os.name != "nt":
        return value, "owner_only_file"
    data_blob, data_buffer = _blob(value)
    entropy_blob, entropy_buffer = _blob(_entropy(home))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(data_blob),
        "Yanxi provider credential",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output),
    )
    if not ok:
        raise ctypes.WinError()
    del data_buffer, entropy_buffer
    try:
        return ctypes.string_at(output.pbData, output.cbData), "windows_dpapi"
    finally:
        kernel32.LocalFree(output.pbData)


def _unprotect(home: Path, value: bytes, protection: str) -> bytes:
    if protection == "owner_only_file":
        return value
    if protection != "windows_dpapi" or os.name != "nt":
        raise ValueError("Credential protection is unavailable on this platform")
    data_blob, data_buffer = _blob(value)
    entropy_blob, entropy_buffer = _blob(_entropy(home))
    output = _DataBlob()
    description = wintypes.LPWSTR()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output),
    )
    if not ok:
        raise ctypes.WinError()
    del data_buffer, entropy_buffer
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        if description:
            kernel32.LocalFree(description)
