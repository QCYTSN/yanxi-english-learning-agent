# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"

datas = [
    (str(ROOT / "src" / "ielts_coach" / "web" / "static"), "ielts_coach/web/static"),
    (str(ROOT / "src" / "ielts_coach" / "resources" / "schemas"), "ielts_coach/resources/schemas"),
    (str(ROOT / "src" / "ielts_coach" / "resources" / "assets"), "ielts_coach/resources/assets"),
    (str(ROOT / "skills-source"), "ielts_coach/resources/skills"),
    *copy_metadata("ielts-ai-coach"),
    *collect_data_files("rapidocr_onnxruntime"),
]

hiddenimports = collect_submodules("uvicorn") + [
    "multipart",
    "pypdfium2",
    "rapidocr_onnxruntime",
    "onnxruntime",
]

a = Analysis(
    [str(SRC / "ielts_coach" / "desktop.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "playwright",
        "matplotlib",
        "pandas",
        "scipy",
        "sklearn",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Yanxi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ROOT / "src" / "ielts_coach" / "resources" / "assets" / "app-icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Yanxi",
)
