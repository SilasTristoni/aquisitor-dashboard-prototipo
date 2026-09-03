from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
backend = root / "backend"
datas = [
    (str(root / "VERSION.txt"), "."),
    (str(root / "frontend" / "dist"), "frontend"),
    (str(backend / "alembic"), "alembic"),
    (str(backend / "alembic.ini"), "."),
]
datas += [
    item
    for item in collect_data_files("matplotlib")
    if "sample_data" not in item[0].replace("\\", "/")
    and "sample_data" not in item[1].replace("\\", "/")
]
hiddenimports = [
    "app.main",
    "matplotlib.backends.backend_agg",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

analysis = Analysis(
    [str(backend / "app" / "windows_launcher.py")],
    pathex=[str(backend)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ThermoPowerMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="ThermoPowerMonitor",
)
