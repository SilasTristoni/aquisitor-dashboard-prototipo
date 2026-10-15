"""Non-invasive, bounded copies of existing runtime evidence. No device calls."""

import asyncio
from collections import deque
from datetime import UTC, datetime
from itertools import islice
from time import monotonic


def bounded(value, depth=0, budget=None):
    budget = budget if budget is not None else [12000, 256 * 1024]
    budget[0] -= 1
    if budget[0] < 0 or budget[1] <= 0:
        return "[snapshot limit]"
    if depth > 7:
        return "[depth limit]"
    if value is None or type(value) in (bool, int, float):
        return value
    if type(value) is str:
        result = value[: min(4096, budget[1])]
        budget[1] -= len(result)
        return result
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is dict:
        return {
            str(k)[:128]: bounded(v, depth + 1, budget)
            for k, v in islice(value.items(), 128)
            if budget[0] > 0 and budget[1] > 0
        }
    if type(value) in (list, tuple, deque):
        return [
            bounded(v, depth + 1, budget)
            for v in islice(value, max(0, len(value) - 256), None)
            if budget[0] > 0 and budget[1] > 0
        ]
    return "[not collected]"


def task_snapshot(task):
    if not isinstance(task, asyncio.Task):
        return None
    chain = []
    coro = task.get_coro()
    for _ in range(12):
        code = getattr(coro, "cr_code", None)
        if code is None:
            break
        chain.append(code.co_name)
        coro = getattr(coro, "cr_await", None)
    return {"done": task.done(), "cancelled": task.cancelled(), "await_chain": chain}


def runtime_snapshot(service, hub=None):
    """One event-loop instant; no awaits, properties, adapter methods or lock acquisition."""
    states, transactions, boundaries = [], {}, {}
    for device_id, runtime in islice(service.runtimes.items(), 32):
        adapter = vars(runtime.adapter)
        transport = adapter.get("transport")
        wire = vars(transport) if transport is not None else {}
        lock = wire.get("_io_lock")
        latest = vars(runtime.latest) if runtime.latest is not None else {}
        states.append(
            {
                "device_id": device_id,
                "protocol": runtime.protocol,
                "session_id": runtime.session_id,
                "paused": runtime.paused,
                "sample_count": runtime.sample_count,
                "persisted_count": runtime.persisted_count,
                "buffered_measurements": len(runtime.buffer),
                "last_error": bounded(runtime.last_error),
                "last_received_timestamp": bounded(latest.get("received_timestamp")),
                "last_device_timestamp": bounded(latest.get("device_timestamp")),
                "task": task_snapshot(runtime.task),
                "adapter_state": bounded(
                    {
                        k: adapter.get(k)
                        for k in (
                            "_reading",
                            "_connection_state",
                            "_reconnecting",
                            "_connected_at",
                            "last_message_at",
                            "read_errors",
                            "_read_count",
                            "port",
                            "baud_rate",
                            "_last_command_tx_monotonic",
                            "_last_command_rx_monotonic",
                        )
                    }
                ),
                "serial_lock_held": lock.locked() if isinstance(lock, asyncio.Lock) else None,
                "serial_handle_present": wire.get("connection") is not None,
                "connection_verified": False,
            }
        )
        transactions[str(device_id)] = bounded(adapter.get("transactions", []))
        boundaries[str(device_id)] = bounded(
            {
                "open": wire.get("open_boundary"),
                "last_query": wire.get("last_query_boundary"),
                "fetch": adapter.get("fetch_diagnostics"),
            }
        )
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "monotonic_timestamp": monotonic(),
        "states": states,
        "transactions": transactions,
        "boundaries": boundaries,
        "last_connection_results": bounded(service.last_connection_results),
        "websocket_queue_sizes": [q.qsize() for q in islice(hub.clients.values(), 64)]
        if hub
        else [],
        "limitations": "Passive memory snapshot; handles do not prove connection; received "
        "counts do not prove WebSocket publication. Rings truncated to 256, runtimes to 32.",
    }
