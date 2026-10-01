"""Build only the standalone internal experiment, with no application/release build."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    cases = list(ET.parse(args.evidence).iter("testcase"))
    if not cases or any(
        c.find(tag) is not None
        for c in cases
        for tag in ("failure", "error", "skipped")
    ):
        raise RuntimeError("Test evidence must contain only passing tests")
    if not any("test_at4532_repeated_celsius" in c.get("classname", "") for c in cases):
        raise RuntimeError("Repeated Celsius tests missing from evidence")
    name = "AT4532-repeated-celsius-engineering-" + datetime.now(UTC).strftime(
        "%Y%m%d-%H%M%S"
    )
    work = ROOT / "build" / name
    destination = ROOT / "engineering" / name
    archive = destination.with_suffix(".zip")
    if work.exists() or destination.exists() or archive.exists():
        raise FileExistsError("Preserve existing artifacts")
    work.mkdir(parents=True)
    sources = [
        *sorted((ROOT / "backend/app/adapters").glob("*.py")),
        ROOT / "backend/app/__init__.py",
        ROOT / "backend/app/engineering/__init__.py",
        ROOT / "backend/app/engineering/windows_serial.py",
        ROOT / "backend/app/engineering/at4532_characterization.py",
        ROOT / "backend/app/engineering/at4532_repeated_celsius.py",
        ROOT / "backend/tests/test_at4532_repeated_celsius.py",
        ROOT / "scripts/characterize-at4532-repeated-celsius.ps1",
        ROOT / "scripts/package-at4532-repeated-celsius.py",
        ROOT / "docs/AT4532_REPEATED_CELSIUS.md",
    ]
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
    metadata = {
        "purpose": "internal_engineering_only",
        "experiment": "passive_5s_three_celsius_5s",
        "build_id": name,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "source_sha256": hashes,
        "test_evidence_sha256": digest(args.evidence),
        "tests_passed": len(cases),
        "physical_validation": "not_performed",
    }
    info = work / "build-info.json"
    info.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--console",
        "--onedir",
        "--name",
        "AT4532RepeatedCelsius",
        "--paths",
        str(ROOT / "backend"),
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "pyinstaller"),
        "--specpath",
        str(work),
        "--add-data",
        f"{info};.",
        "--hidden-import",
        "encodings.cp936",
        "--collect-data",
        "tzdata",
        str(ROOT / "backend/app/engineering/at4532_repeated_celsius.py"),
    ]
    with (work / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True
        )
    staging = work / "dist/AT4532RepeatedCelsius"
    executable = staging / "AT4532RepeatedCelsius.exe"
    subprocess.run(
        [str(executable), "--help"], check=True, timeout=30, capture_output=True
    )
    # A deliberately nonexistent name: no physical COM is opened by the smoke.
    capture = work / "nonexistent-port-smoke"
    smoke = subprocess.run(
        [
            str(executable),
            "--port",
            "COM_THERMOPOWER_SMOKE_NONEXISTENT",
            "--output",
            str(capture),
        ],
        timeout=30,
        capture_output=True,
    )
    events = [
        json.loads(line) for line in (capture / "events.jsonl").read_text().splitlines()
    ]
    if smoke.returncode == 0 or not any(e["event"] == "error" for e in events):
        raise RuntimeError("Smoke did not retain failure evidence")
    if any(e["event"] in {"write", "open_completed"} for e in events):
        raise RuntimeError("Smoke unexpectedly opened a port")
    for line in (capture / "SHA256SUMS.txt").read_text().splitlines():
        expected, filename = line.split("  ")
        if digest(capture / filename) != expected:
            raise RuntimeError("Smoke evidence hash mismatch")
    shutil.copy2(info, staging / "build-info.json")
    shutil.copy2(args.evidence, staging / "TEST-RESULTS.xml")
    shutil.copy2(ROOT / "docs/AT4532_REPEATED_CELSIUS.md", staging / "LEIA-ME.md")
    shutil.copy2(ROOT / "scripts/characterize-at4532-repeated-celsius.ps1", staging)
    (staging / "SMOKE-RESULTS.txt").write_text(
        "Passed: --help and nonexistent-port failure with verified evidence hashes; no physical TX.\n",
        encoding="utf-8",
    )
    for p in sources:
        target = staging / "source" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    if any(digest(ROOT / p) != value for p, value in hashes.items()):
        raise RuntimeError("Source drift during packaging")
    packaged = {
        p.relative_to(staging).as_posix(): digest(p)
        for p in sorted(staging.rglob("*"))
        if p.is_file()
    }
    if any(Path(p).suffix in {".db", ".xlsx"} or "seed-ux-demo" in p for p in packaged):
        raise RuntimeError("Unexpected development data in package")
    (staging / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {p}\n" for p, value in packaged.items()), encoding="utf-8"
    )
    temporary = work / "verified.zip"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zipped:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zipped.write(p, p.relative_to(staging).as_posix())
    with zipfile.ZipFile(temporary) as zipped:
        if set(zipped.namelist()) != set(packaged) | {"SHA256SUMS.txt"}:
            raise RuntimeError("ZIP contents differ")
        for p, expected in packaged.items():
            if hashlib.sha256(zipped.read(p)).hexdigest() != expected:
                raise RuntimeError(f"ZIP hash mismatch: {p}")
    shutil.copytree(staging, destination)
    shutil.copy2(temporary, archive)
    checksum = digest(archive)
    archive.with_suffix(".zip.sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"zip": str(archive), "bytes": archive.stat().st_size, "sha256": checksum}
        )
    )


if __name__ == "__main__":
    main()
