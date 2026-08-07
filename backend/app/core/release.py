from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseConfiguration:
    version: str
    homologation_email: str
    homologation_password: str


def _configuration_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "release-config.json"
    candidates = [
        Path.cwd() / "release-config.json",
        Path(__file__).resolve().parents[3] / "release-config.json",
    ]
    try:
        candidates.insert(1, Path(__file__).resolve().parents[2] / "release-config.json")
    except IndexError:
        pass
    return next((path for path in candidates if path.is_file()), candidates[0])


def load_release_configuration() -> ReleaseConfiguration:
    path = _configuration_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    homologation = payload["homologation"]
    return ReleaseConfiguration(
        version=str(payload["version"]),
        homologation_email=str(homologation["email"]),
        homologation_password=str(homologation["password"]),
    )


release_configuration = load_release_configuration()
