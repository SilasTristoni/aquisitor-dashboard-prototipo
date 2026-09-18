"""Exercise real packaged renderers with isolated synthetic sessions, never serial ports."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    data = args.data_dir.resolve()
    # Refuse to seed the operator's application database.
    if not data.is_relative_to(ROOT / "build") or not data.name.startswith("smoke-runtime-"):
        raise ValueError("Export smoke requires an isolated build/smoke-runtime-* directory")
    os.environ["THERMOPOWER_DATABASE_URL"] = f"sqlite:///{(data / 'data/thermopower.db').as_posix()}"
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
    from test_support_exports import seed_source_session

    access = (data / "PRIMEIRO-ACESSO.txt").read_text(encoding="utf-8-sig").splitlines()
    email = next(line.split(":", 1)[1].strip() for line in access if line.startswith("E-mail:"))
    password = next(line.split(":", 1)[1].strip() for line in access if line.startswith("Senha tempor"))
    results = []
    with httpx.Client(base_url=args.url, timeout=90) as client:
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        for mode in ("electrical", "thermal", "combined"):
            payload = seed_source_session(mode)
            for kind in ("executive.pdf", "executive.png", "pdf", "xlsx"):
                response = client.post(f"/api/v1/reports/period/{kind}", json=payload)
                if response.status_code != 200:
                    raise RuntimeError(f"Packaged export failed: {mode}/{kind}: {response.text}")
                signature = b"%PDF" if kind.endswith("pdf") else b"\x89PNG" if kind.endswith("png") else b"PK"
                assert response.content.startswith(signature), (mode, kind)
                (data / f"{mode}-{kind}").write_bytes(response.content)
                results.append({"mode": mode, "format": kind, "bytes": len(response.content)})
        guide = client.get("/api/v1/help/user-guide")
        assert guide.status_code == 200 and guide.content.startswith(b"%PDF")
        support = client.get("/api/v1/support/package")
        assert support.status_code == 200
        with zipfile.ZipFile(io.BytesIO(support.content)) as archive:
            assert archive.testzip() is None
            assert "logs/errors.log" in archive.namelist()
            for name in archive.namelist():
                assert password.encode() not in archive.read(name)
        (data / "export-smoke.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Packaged exports: 12 passed; user manual and support ZIP: passed")


if __name__ == "__main__":
    main()
