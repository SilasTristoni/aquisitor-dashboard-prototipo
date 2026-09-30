"""Package an internal experiment after explicit focused-test evidence; no release actions."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.6-engineering-at4532-characterization"


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
    parser.add_argument(
        "--evidence",
        type=Path,
        nargs="+",
        required=True,
        help="JUnit results ordered oldest to newest; reruns replace same test",
    )
    args = parser.parse_args()
    results = {}
    for evidence in args.evidence:
        for case in ET.parse(evidence).iter("testcase"):
            results[(case.get("classname"), case.get("name"))] = not any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            )
    if not results or not all(results.values()):
        raise RuntimeError(
            "Focused tests contain unresolved failures/skips; packaging blocked"
        )
    date = datetime.now(UTC).strftime("%Y%m%d")
    name = f"ThermoPower-{VERSION}-{date}"
    destination = ROOT / "engineering" / name
    archive = Path(str(destination) + ".zip")
    work = ROOT / "build" / (name + "-" + datetime.now(UTC).strftime("%H%M%S"))
    if destination.exists() or archive.exists() or work.exists():
        raise FileExistsError(
            "Preserve previous artifacts: choose a new dated build directory"
        )
    work.mkdir(parents=True)
    metadata = work / "metadata"
    metadata.mkdir()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    allowed = [
        p
        for p in paths
        if p
        and (
            p.startswith(
                (
                    "backend/app/",
                    "backend/tests/",
                    "backend/alembic/",
                    "scripts/",
                    "docs/",
                )
            )
            or p
            in {
                "thermopower.spec",
                ".gitignore",
                "VERSION.txt",
                "backend/requirements.txt",
                "backend/pyproject.toml",
            }
        )
    ]
    source_hashes = {
        p: digest(ROOT / p) for p in sorted(set(allowed)) if (ROOT / p).is_file()
    }
    frontend_hashes = {
        p.relative_to(ROOT).as_posix(): digest(p)
        for p in sorted((ROOT / "frontend/dist").rglob("*"))
        if p.is_file()
    }
    if not frontend_hashes:
        raise RuntimeError("Previously built frontend absent")
    manifest = json.dumps(
        {**source_hashes, **frontend_hashes}, sort_keys=True, indent=2
    )
    build = {
        "version": VERSION,
        "commit": commit,
        "source_dirty": True,
        "build_date": datetime.now(UTC).isoformat(),
        "build_id": name,
        "purpose": "internal_engineering_only",
        "physical_validation": "failed_pending_investigation",
        "source_manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "focused_tests_passed": len(results),
        "full_backend_gate_run": False,
        "frontend": "reused unchanged from previous validated build",
        "excluded_local_file": "iniciar-windows.bat",
    }
    (metadata / "VERSION.txt").write_text(VERSION, encoding="utf-8")
    (metadata / "build-info.json").write_text(
        json.dumps(build, indent=2), encoding="utf-8"
    )
    env = {
        **os.environ,
        "THERMOPOWER_PACKAGE_VERSION_FILE": str(metadata / "VERSION.txt"),
        "THERMOPOWER_PACKAGE_BUILD_INFO": str(metadata / "build-info.json"),
    }
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
        env,
    )
    staging = work / "dist/ThermoPowerMonitor"
    # Only the known, unneeded Matplotlib demo directory inside this new staging tree.
    samples = staging / "_internal/matplotlib/mpl-data/sample_data"
    if samples.exists():
        if not samples.resolve().is_relative_to(staging.resolve()):
            raise RuntimeError("Invalid sample-data path")
        shutil.rmtree(samples)
    shutil.copy2(metadata / "build-info.json", staging / "build-info.json")
    shutil.copy2(ROOT / "scripts/characterize-at4532.ps1", staging)
    shutil.copy2(ROOT / "docs/AT4532_CHARACTERIZATION.md", staging / "LEIA-ME.md")
    shutil.copy2(ROOT / "docs/AT4532_066_CURRENT_STATE.md", staging)
    (staging / "SOURCE-SHA256.json").write_text(manifest, encoding="utf-8")
    # HEAD alone does not describe dirty sources. Include the exact reviewable overlay.
    patch = subprocess.check_output(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
            "backend",
            "scripts",
            "docs",
            "thermopower.spec",
            ".gitignore",
        ],
        cwd=ROOT,
    )
    (staging / "SOURCE-DIFF.patch").write_bytes(patch)
    untracked = (
        subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    for relative in untracked:
        if relative in source_hashes:
            target = staging / "source-overlay" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
    for index, evidence in enumerate(args.evidence):
        shutil.copy2(evidence, staging / f"FOCUSED-{index + 1}.xml")
    (staging / "FOCUSED-RESULTS.json").write_text(
        json.dumps(
            {
                "passed": len(results),
                "failed": 0,
                "rerun_policy": "latest result per classname/name; original failures retained in XML",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
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
            "-PackageVersion",
            VERSION,
        ],
        work / "smoke.log",
    )
    shutil.copy2(work / "smoke.log", staging / "SMOKE-RESULTS.txt")
    # Load the bundled engineering module without touching any real serial port.
    smoke_capture = work / "tool-smoke"
    process = subprocess.run(
        [
            str(staging / "ThermoPowerMonitor.exe"),
            "--characterize-at4532",
            "--port",
            "COM_THERMOPOWER_SMOKE_NONEXISTENT",
            "--output",
            str(smoke_capture),
        ],
        timeout=30,
        env={
            **os.environ,
            "THERMOPOWER_NO_BROWSER": "1",
            "THERMOPOWER_APP_DATA_DIR": str(work / "tool-runtime"),
            "THERMOPOWER_LOG_DIRECTORY": str(work / "tool-runtime/logs"),
        },
    )
    events = [
        json.loads(line)
        for line in (smoke_capture / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    if process.returncode == 0 or not any(e["event"] == "error" for e in events):
        raise RuntimeError(
            "Engineering entrypoint did not reject nonexistent serial port"
        )
    if any(e["event"] == "write" for e in events):
        raise RuntimeError("Unexpected TX in tool smoke")
    if not (smoke_capture / "SHA256SUMS.txt").is_file():
        raise RuntimeError("Failed capture did not retain its manifest")
    (staging / "TOOL-SMOKE.txt").write_text(
        "Passed: bundled module exports failure evidence for nonexistent port; no physical TX.\n",
        encoding="utf-8",
    )
    # Do not package local data, credentials, or the user's locally modified launcher.
    for path in staging.rglob("*"):
        if path.is_file() and (
            path.suffix in {".db", ".csv", ".xlsx"}
            or path.name in {"iniciar-windows.bat", "PRIMEIRO-ACESSO.txt"}
        ):
            raise RuntimeError(f"Unexpected local data in package: {path}")
    hashes = {
        p.relative_to(staging).as_posix(): digest(p)
        for p in sorted(staging.rglob("*"))
        if p.is_file()
    }
    (staging / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {key}\n" for key, value in hashes.items()), encoding="utf-8"
    )
    temp_zip = work / "verified.zip"
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(staging).as_posix())
    with zipfile.ZipFile(temp_zip) as zipped:
        if set(zipped.namelist()) != set(hashes) | {"SHA256SUMS.txt"}:
            raise RuntimeError("ZIP file set differs")
        for relative, expected in hashes.items():
            if hashlib.sha256(zipped.read(relative)).hexdigest() != expected:
                raise RuntimeError(f"ZIP hash mismatch: {relative}")
    # Detect source drift while building; never label different sources as tested.
    if any(digest(ROOT / p) != h for p, h in source_hashes.items()):
        raise RuntimeError("Sources changed while building")
    shutil.copytree(staging, destination)
    shutil.copy2(temp_zip, archive)
    checksum = digest(archive)
    Path(str(archive) + ".sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "zip": str(archive),
                "bytes": archive.stat().st_size,
                "sha256": checksum,
                "build": build,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
