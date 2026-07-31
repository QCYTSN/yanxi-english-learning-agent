from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import hashlib
import urllib.request
import venv
from uuid import uuid4
from pathlib import Path
from typing import Any


OCR_RUNTIME_VERSION = "rapidocr-1.4.4-v1"
OCR_PACKAGES = (
    "numpy>=2,<2.3",
    "Pillow>=10,<13",
    "pypdfium2==5.10.1",
    "rapidocr-onnxruntime==1.4.4",
)
OCR_ENGLISH_MODEL_URL = (
    "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/"
    "v3.5.0/onnx/PP-OCRv5/rec/en_PP-OCRv5_rec_mobile_infer.onnx"
)
OCR_ENGLISH_MODEL_SHA256 = (
    "c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8"
)


def ocr_runtime_status(home: Path) -> dict[str, Any]:
    root = _runtime_root(home)
    state = _read_state(root)
    python = _runtime_python(root)
    installed = python.is_file()
    available = installed and state.get("status") == "ready"
    return {
        "engine_id": "rapidocr-local",
        "display_name": "RapidOCR 隔离本地引擎",
        "runtime_version": OCR_RUNTIME_VERSION,
        "status": state.get("status", "not_installed"),
        "available": available,
        "local_only": True,
        "isolated": True,
        "runtime_path": str(root),
        "packages": list(OCR_PACKAGES),
        "english_model_ready": _english_model_path(home).is_file(),
        "error_message": state.get("error_message"),
        "recovery_action": state.get("recovery_action"),
    }


def queue_ocr_runtime_install(home: Path) -> dict[str, Any]:
    root = _runtime_root(home)
    state = _read_state(root)
    if state.get("status") in {"queued", "installing", "ready"}:
        return ocr_runtime_status(home)
    _write_state(root, {
        "status": "queued",
        "runtime_version": OCR_RUNTIME_VERSION,
        "error_message": None,
        "recovery_action": None,
    })
    return ocr_runtime_status(home)


def install_ocr_runtime(home: Path) -> dict[str, Any]:
    root = _runtime_root(home)
    _write_state(root, {
        "status": "installing",
        "runtime_version": OCR_RUNTIME_VERSION,
        "error_message": None,
        "recovery_action": None,
    })
    try:
        if not _runtime_python(root).is_file():
            venv.EnvBuilder(with_pip=True, clear=False).create(root)
        python = _runtime_python(root)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *OCR_PACKAGES,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        probe = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import PIL, pypdfium2, rapidocr_onnxruntime; "
                    "from rapidocr_onnxruntime import RapidOCR; "
                    "RapidOCR(); print('ready')"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if "ready" not in probe.stdout:
            raise RuntimeError("OCR runtime probe did not report ready")
        _ensure_english_model(home)
        _write_state(root, {
            "status": "ready",
            "runtime_version": OCR_RUNTIME_VERSION,
            "error_message": None,
            "recovery_action": None,
        })
    except Exception as exc:
        _write_state(root, {
            "status": "failed",
            "runtime_version": OCR_RUNTIME_VERSION,
            "error_message": str(exc),
            "recovery_action": "retry_install",
        })
        raise
    return ocr_runtime_status(home)


def recover_ocr_runtime_install(home: Path) -> bool:
    root = _runtime_root(home)
    state = _read_state(root)
    if state.get("status") not in {"queued", "installing"}:
        return False
    _write_state(root, {
        "status": "failed",
        "runtime_version": OCR_RUNTIME_VERSION,
        "error_message": "The local service stopped before OCR installation completed.",
        "recovery_action": "retry_install",
    })
    return True


def execute_ocr(
    home: Path,
    input_path: Path,
    pages: list[int],
    *,
    timeout_seconds: int = 1800,
    render_scale: float = 2.2,
) -> dict[int, dict[str, Any]]:
    status = ocr_runtime_status(home)
    if not status["available"]:
        raise RuntimeError("The isolated local OCR runtime is not ready")
    root = _runtime_root(home)
    output = input_path.parent / f".ocr-result-{uuid4().hex}.json"
    worker = Path(__file__).with_name("ocr_worker.py").resolve()
    english_model = _english_model_path(home)
    command = [
        str(_runtime_python(root)),
        str(worker),
        "--input",
        str(input_path),
        "--output",
        str(output),
        "--pages",
        ",".join(str(page) for page in pages),
        "--scale",
        str(max(1.0, min(float(render_scale), 4.0))),
    ]
    if english_model.is_file():
        command.extend(["--rec-model", str(english_model)])
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0
            ),
            start_new_session=os.name != "nt",
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process)
            stdout, stderr = process.communicate()
            raise TimeoutError(
                f"OCR worker exceeded the {timeout_seconds}s timeout"
            ) from exc
        if process.returncode:
            detail = (stderr or stdout or "").strip()
            raise RuntimeError(
                f"OCR worker failed with exit code {process.returncode}"
                + (f": {detail[-1200:]}" if detail else "")
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
        return {
            int(page): {
                "text": str(result.get("text") or ""),
                "confidence": result.get("confidence"),
                "layout_lines": list(result.get("layout_lines") or []),
            }
            for page, result in (payload.get("pages") or {}).items()
        }
    finally:
        output.unlink(missing_ok=True)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _runtime_root(home: Path) -> Path:
    return home / "runtime" / "ocr" / OCR_RUNTIME_VERSION


def _english_model_path(home: Path) -> Path:
    return home / "runtime" / "ocr" / "models" / (
        "en_PP-OCRv5_rec_mobile_infer.onnx"
    )


def _ensure_english_model(home: Path) -> Path:
    target = _english_model_path(home)
    if target.is_file() and _file_sha256(target) == OCR_ENGLISH_MODEL_SHA256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".download")
    temp.unlink(missing_ok=True)
    urllib.request.urlretrieve(OCR_ENGLISH_MODEL_URL, temp)
    if _file_sha256(temp) != OCR_ENGLISH_MODEL_SHA256:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Downloaded English OCR model failed checksum validation")
    temp.replace(target)
    return target


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_python(root: Path) -> Path:
    return (
        root / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else root / "bin" / "python"
    )


def _state_path(root: Path) -> Path:
    return root / "runtime-state.json"


def _read_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "failed",
            "error_message": "OCR runtime state is unreadable.",
            "recovery_action": "retry_install",
        }


def _write_state(root: Path, state: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = _state_path(root)
    temp = root / ".runtime-state.tmp"
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
