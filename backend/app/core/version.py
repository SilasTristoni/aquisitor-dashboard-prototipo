from __future__ import annotations

import sys
from pathlib import Path


def load_application_version() -> str:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "VERSION.txt")
    candidates.extend(
        [
            Path.cwd() / "VERSION.txt",
            Path(__file__).resolve().parents[3] / "VERSION.txt",
        ]
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("VERSION.txt não foi encontrado")
    return path.read_text(encoding="utf-8-sig").strip()


APPLICATION_VERSION = load_application_version()
