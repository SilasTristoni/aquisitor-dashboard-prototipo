import hashlib
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows packaging uses PowerShell")
def test_package_manifest_preserves_unicode_filenames(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/build-windows-engineering.ps1").read_text(encoding="utf-8-sig")
    # Execute the production manifest stage with real files, without rebuilding the application.
    stage = script.split('$ManifestPath = Join-Path $StagingRoot "SHA256SUMS.txt"', 1)[1]
    stage = stage.split("if (Test-Path -LiteralPath $ValidatedZip)", 1)[0]
    stage = '$ManifestPath = Join-Path $StagingRoot "SHA256SUMS.txt"' + stage
    expected = {}
    for relative in ("Manual do Usuário - ThermoPower Monitor.pdf", "subpasta/Relatório α.txt"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = relative.encode("utf-8")
        target.write_bytes(content)
        expected[relative] = hashlib.sha256(content).hexdigest().upper()
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference = 'Stop'\n"
            "$StagingRoot = $env:THERMOPOWER_MANIFEST_TEST_ROOT\n" + stage,
        ],
        env={**os.environ, "THERMOPOWER_MANIFEST_TEST_ROOT": str(tmp_path)},
        check=True, capture_output=True, timeout=30,
    )
    actual = {}
    for line in (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        actual[relative] = digest
    assert actual == expected
