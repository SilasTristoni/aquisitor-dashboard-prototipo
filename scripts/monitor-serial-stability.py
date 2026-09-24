"""Observe an existing acquisition over HTTP; this script never opens a COM port."""

import argparse
import getpass
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/v1")
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--gpm-id", type=int)
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.minutes < 30:
        parser.error("O ensaio de bancada deve durar pelo menos 30 minutos.")
    token = os.environ.get("THERMOPOWER_MONITOR_TOKEN") or getpass.getpass(
        "Token de acesso: "
    )

    def request(path):
        req = Request(
            args.url.rstrip("/") + path, headers={"Authorization": "Bearer " + token}
        )
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    summary = {
        "started_at": datetime.now(UTC).isoformat(),
        "requested_minutes": args.minutes,
        "physical_validation": "pending_operator_review",
        "http_errors": 0,
        "history_truncated": False,
        "session_ids": [],
        "samples": 0,
    }
    sequence = 0
    initial = None
    final = None
    interrupted = False
    try:
        with (args.output / "observations.jsonl").open("w", encoding="utf-8") as log:
            while time.monotonic() - started < args.minutes * 60:
                try:
                    report = request(
                        f"/devices/{args.device_id}/acquisition-diagnostics"
                        f"?after_sequence={sequence}&page_size=256"
                    )
                    report["observed_at"] = datetime.now(UTC).isoformat()
                    sequence = report["next_sequence"]
                    summary["history_truncated"] |= report["history_truncated"]
                    status = report["status"]
                    initial = initial or status
                    final = status
                    session = status.get("session_id")
                    if session not in summary["session_ids"]:
                        summary["session_ids"].append(session)
                    if args.gpm_id:
                        report["gpm_status"] = request(f"/devices/{args.gpm_id}/status")
                    log.write(json.dumps(report, ensure_ascii=False) + "\n")
                    log.flush()
                    summary["samples"] += 1
                    if report["has_more"]:
                        continue
                except (HTTPError, URLError, TimeoutError) as exc:
                    summary["http_errors"] += 1
                    log.write(
                        json.dumps(
                            {
                                "observed_at": datetime.now(UTC).isoformat(),
                                "error_type": type(exc).__name__,
                            }
                        )
                        + "\n"
                    )
                    log.flush()
                time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        summary.update(
            {
                "elapsed_seconds": time.monotonic() - started,
                "interrupted": interrupted,
                "initial_status": initial,
                "final_status": final,
            }
        )
        first_metrics = (initial or {}).get("acquisition_diagnostics") or {}
        last_metrics = (final or {}).get("acquisition_diagnostics") or {}
        summary["counter_deltas"] = {
            key: last_metrics.get(key, 0) - first_metrics.get(key, 0)
            for key in [
                "fetch_attempts",
                "successful_fetches",
                "discarded_fetches",
                "fetch_timeouts",
                "unknown_responses",
                "reconnect_count",
            ]
        }
        (args.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(args.output / "summary.json")


if __name__ == "__main__":
    main()
