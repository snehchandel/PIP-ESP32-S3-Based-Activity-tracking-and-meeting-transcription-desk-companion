# PyInstaller spec for PIP.exe (ADR-034) - built by tools/build_exe.ps1, not by hand.
# One-folder build: dist/PIP/PIP.exe + _internal/. The CUDA DLLs are NOT bundled (GPU speech add-on,
# host/service/speech/gpu_pack.py); Whisper models are downloaded into the user's data folder on first use.
# ruff: noqa
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
HOST = ROOT / "host"
VERSION = os.environ.get("PIP_APP_VERSION", "0.0.0")

datas = [
    (str(HOST / "desktop_ui" / "dist"), "ui"),
    (str(HOST / "service" / "storage" / "migrations"), "service/storage/migrations"),
    (str(ROOT / "tools" / "pip.ico"), "."),
]
fw = ROOT / "firmware" / "build" / "pip_firmware.bin"
if fw.exists():
    datas.append((str(fw), "firmware"))
for pkg in ("faster_whisper", "piper", "tzdata", "webview"):
    datas += collect_data_files(pkg)

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

hiddenimports = (
    collect_submodules("service")
    + collect_submodules("uvicorn")
    + collect_submodules("webview.platforms", filter=lambda n: n.endswith(("winforms", "edgechromium", "mshtml")))
    + ["pystray._win32", "keyring.backends.Windows", "clr", "websockets", "httptools", "watchfiles"]
)

# Development-only or huge packages that must never end up in the app.
excludes = ["nvidia", "torch", "tensorflow", "matplotlib", "playwright", "pytest", "IPython", "tkinter",
            "ziglang", "cmake", "ninja", "esptool", "mypy", "ruff", "tests", "support"]

a = Analysis(
    [str(HOST / "pip_app.py")],
    pathex=[str(HOST)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

version_file = Path(workpath) / "pip_version.txt"
nums = (VERSION.split("-")[0].split(".") + ["0", "0", "0", "0"])[:4]
vt = ", ".join(n if n.isdigit() else "0" for n in nums)
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({vt}), prodvers=({vt})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('ProductName', 'PIP Companion'), StringStruct('FileDescription', 'PIP Companion'),
    StringStruct('FileVersion', '{VERSION}'), StringStruct('ProductVersion', '{VERSION}'),
    StringStruct('OriginalFilename', 'PIP.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PIP",
    console=False,
    icon=str(ROOT / "tools" / "pip.ico"),
    version=str(version_file),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PIP")
