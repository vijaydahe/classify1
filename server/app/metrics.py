"""In-process API metrics.

Counters live in process memory: on serverless they reflect the current
instance since its cold start, which is exactly the window that matters for
capacity decisions.
"""
import time

started_at = time.time()

stats = {
    "requests": 0,
    "errors": 0,
    "total_ms": 0.0,
    "max_ms": 0.0,
}


def record(duration_ms: float, is_error: bool) -> None:
    stats["requests"] += 1
    stats["total_ms"] += duration_ms
    if duration_ms > stats["max_ms"]:
        stats["max_ms"] = duration_ms
    if is_error:
        stats["errors"] += 1
