# backend.spec
from pathlib import Path

block_cipher = None

datas = []
if Path("Required_files").exists():
    datas.append(("Required_files", "Required_files"))

a = Analysis(
    ["backend_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.middleware.proxy_headers",
        "fastapi",
        "starlette",
        "starlette.middleware",
        "starlette.middleware.cors",
        "anyio",
        "anyio._backends._asyncio",
        "email.mime.multipart",
        "email.mime.text",
        "openpyxl",
        "openpyxl.cell",
        "openpyxl.chart",
        "openpyxl.drawing",
        "openpyxl.styles",
        "openpyxl.utils",
        "openpyxl.worksheet",
        "pandas",
        "pandas._libs.tslibs.base",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.timedeltas",
        "pandas._libs.tslibs.timestamps",
        "numpy",
        "multipart",
        "python_multipart",
        "dateutil",
        "dateutil.parser",
        "polars",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="backend",
)