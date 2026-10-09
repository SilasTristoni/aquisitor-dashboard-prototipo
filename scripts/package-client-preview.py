"""Package an already validated client candidate; preserve all earlier artifacts."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, env=None):
    with log.open("w", encoding="utf-8") as output:
        subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates", type=Path, required=True)
    args = parser.parse_args()
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    required = {
        "backend",
        "ruff",
        "lint",
        "typecheck",
        "vitest",
        "frontend_build",
        "sqlite_migrations",
        "compose",
        "visual",
        "physical_core_unchanged",
    }
    if not required <= gates["checks"].keys() or any(
        gates["checks"][key] != "passed" for key in required
    ):
        raise RuntimeError("Required gates are not all green")
    sources = gates["source_sha256"]

    def verify_sources():
        for name, expected in sources.items():
            if digest(ROOT / name) != expected:
                raise RuntimeError(f"Changed after validation: {name}")

    verify_sources()
    version = (ROOT / "VERSION.txt").read_text().strip()
    name = f"ThermoPower-{version}"
    destination = ROOT / "release" / name
    archive = Path(str(destination) + ".zip")
    if destination.exists() or archive.exists():
        raise FileExistsError("Candidate already exists; preserve previous packages")
    work = ROOT / "build" / (name + "-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True, exist_ok=False)
    manifest = json.dumps(sources, sort_keys=True, indent=2)
    metadata = {
        "version": version,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "build_date": datetime.now(UTC).isoformat(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "source_manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "physical_validation": "AT4532_pending_bench_validation",
    }
    info = work / "build-info.json"
    info.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    # Reviewable source diff stays with internal validation, outside the client ZIP.
    (work / "SOURCE-DIFF.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    )
    run([sys.executable, "scripts/build-user-guide.py"], work / "user-guide.log")
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(work / "dist"),
            "--workpath",
            str(work / "pyinstaller"),
            "thermopower.spec",
        ],
        work / "build.log",
        {**os.environ, "THERMOPOWER_PACKAGE_BUILD_INFO": str(info)},
    )
    # Inspect bundled Python modules as well as loose files.
    from PyInstaller.archive.readers import ZlibArchiveReader

    bundled = ZlibArchiveReader(str(work / "pyinstaller/thermopower/PYZ-00.pyz"))
    if any(module.startswith("app.engineering") for module in bundled.toc):
        raise RuntimeError("Engineering modules entered the client application")
    staging = work / "dist/ThermoPowerMonitor"
    samples = staging / "_internal/matplotlib/mpl-data/sample_data"
    if samples.exists():
        if samples.resolve() != (
            staging.resolve() / "_internal/matplotlib/mpl-data/sample_data"
        ):
            raise RuntimeError("Unexpected sample-data directory")
        shutil.rmtree(samples)
    shutil.copy2(info, staging / "build-info.json")
    shutil.copy2(ROOT / "docs/RELEASE_070_CLIENT_PREVIEW.md", staging / "LEIA-ME.md")
    shutil.copy2(ROOT / "build/user-guide.pdf", staging / "Manual do Usuario.pdf")
    (staging / "SOURCE-SHA256.json").write_text(manifest, encoding="utf-8")
    run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/smoke-windows-package.ps1"),
            "-Executable",
            str(staging / "ThermoPowerMonitor.exe"),
        ],
        work / "smoke.log",
    )
    for p in staging.rglob("*"):
        if p.is_file() and (
            p.suffix.lower() in {".db", ".csv", ".xlsx"}
            or p.name in {".env", "PRIMEIRO-ACESSO.txt"}
            or "characteriz" in p.name
            or "seed-ux-demo" in p.name
        ):
            raise RuntimeError(f"Unexpected client data/tool: {p.name}")
    packaged = {
        p.relative_to(staging).as_posix(): digest(p)
        for p in sorted(staging.rglob("*"))
        if p.is_file()
    }
    (staging / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {name}\n" for name, value in packaged.items()),
        encoding="utf-8",
    )
    temporary = work / "verified.zip"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zipped:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zipped.write(p, p.relative_to(staging).as_posix())
    extracted = work / "extracted"
    with zipfile.ZipFile(temporary) as zipped:
        if set(zipped.namelist()) != set(packaged) | {"SHA256SUMS.txt"}:
            raise RuntimeError("ZIP file set differs")
        for name in zipped.namelist():
            if not (extracted / name).resolve().is_relative_to(extracted.resolve()):
                raise RuntimeError("Unsafe ZIP path")
        zipped.extractall(extracted)
    for name, expected in packaged.items():
        if digest(extracted / name) != expected:
            raise RuntimeError(f"Extracted file hash mismatch: {name}")
    verify_sources()
    shutil.copytree(staging, destination)
    shutil.copy2(temporary, archive)
    checksum = digest(archive)
    Path(str(archive) + ".sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="utf-8"
    )
    result = {
        "zip": str(archive),
        "bytes": archive.stat().st_size,
        "sha256": checksum,
        "metadata": metadata,
        "smoke": str(work / "smoke.log"),
        "extracted": str(extracted),
    }
    (work / "package-result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
