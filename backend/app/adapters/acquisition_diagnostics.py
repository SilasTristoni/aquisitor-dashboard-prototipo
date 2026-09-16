from dataclasses import dataclass


@dataclass
class FetchDiagnostics:
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

    def snapshot(self) -> dict:
        return {
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
            "maximum_gap_ms": self.maximum_gap_ms,
            "average_query_duration_ms": (
                self.query_duration_ms / self.fetch_attempts if self.fetch_attempts else None
            ),
            "last_successful_fetch_at": self.last_successful_fetch_at,
            "last_failure": self.last_failure,
        }
