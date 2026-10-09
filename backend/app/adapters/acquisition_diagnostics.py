from dataclasses import dataclass, field


@dataclass
class FetchDiagnostics:
    # Historical fetch_* keys are retained for existing diagnostic consumers.
    trigger_interval_seconds: float = 5.0
    input_boundary_metrics: dict[str, int] = field(default_factory=dict)
    consecutive_fetch_failures: int = 0
    discarded_fetches: int = 0
    unknown_responses: int = 0
    reconnect_failures: int = 0
    consecutive_reconnect_failures: int = 0
    recovery_started: float | None = None
    successful_fetches: int = 0
    fetch_timeouts: int = 0
    consecutive_fetch_timeouts: int = 0
    reconnect_count: int = 0
    fetch_attempts: int = 0
    first_tx: float | None = None
    last_tx: float | None = None
    first_rx: float | None = None
    last_rx: float | None = None
    maximum_gap_ms: float = 0
    query_duration_ms: float = 0
    last_successful_fetch_at: str | None = None
    last_failure: dict | None = None

    def snapshot(self, now: float | None = None) -> dict:
        return {
            "acquisition_strategy": "celsius_trigger",
            "trigger_command": "SYST:UNIT CEL",
            "trigger_interval_seconds": self.trigger_interval_seconds,
            "frame_timeout_seconds": 4.0,
            "trigger_attempts": self.fetch_attempts,
            "successful_triggers": self.successful_fetches,
            "trigger_timeouts": self.fetch_timeouts,
            **self.input_boundary_metrics,
            "consecutive_fetch_failures": self.consecutive_fetch_failures,
            "discarded_fetches": self.discarded_fetches,
            "unknown_responses": self.unknown_responses,
            "reconnect_failures": self.reconnect_failures,
            "consecutive_reconnect_failures": self.consecutive_reconnect_failures,
            "successful_fetches": self.successful_fetches,
            "fetch_timeouts": self.fetch_timeouts,
            "consecutive_fetch_timeouts": self.consecutive_fetch_timeouts,
            "reconnect_count": self.reconnect_count,
            "fetch_attempts": self.fetch_attempts,
            "average_fetch_interval_ms": (
                (self.last_tx - self.first_tx) * 1000 / (self.fetch_attempts - 1)
                if self.fetch_attempts > 1
                else None
            ),
            "average_successful_rx_interval_ms": (
                (self.last_rx - self.first_rx) * 1000 / (self.successful_fetches - 1)
                if self.successful_fetches > 1
                else None
            ),
            "maximum_gap_ms": max(self.maximum_gap_ms, (now - self.last_rx) * 1000)
            if now is not None and self.last_rx is not None
            else self.maximum_gap_ms,
            "average_query_duration_ms": (
                self.query_duration_ms / self.fetch_attempts if self.fetch_attempts else None
            ),
            "last_successful_fetch_at": self.last_successful_fetch_at,
            "last_failure": self.last_failure,
        }
