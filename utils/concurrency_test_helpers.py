"""Thread-safe helpers for concurrent Django database tests."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Callable, TypeVar

from django.db import close_old_connections, connections

T = TypeVar("T")
U = TypeVar("U")


def _close_worker_connections() -> None:
    connections.close_all()
    close_old_connections()


def run_concurrent_workers(
    operation: Callable[[], T],
    *,
    workers: int = 2,
    barrier: Barrier | None = None,
    barrier_timeout: float = 5,
    result_timeout: float = 15,
) -> list[T]:
    """Run ``operation`` in parallel threads; close DB connections in each worker."""

    def worker() -> T:
        close_old_connections()
        try:
            if barrier is not None:
                barrier.wait(timeout=barrier_timeout)
            return operation()
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker) for _ in range(workers)]
        results = [future.result(timeout=result_timeout) for future in futures]
    _close_worker_connections()
    time.sleep(0.05)
    _close_worker_connections()
    return results


def run_two_concurrent(
    operation_a: Callable[[], T],
    operation_b: Callable[[], U],
    *,
    result_timeout: float = 15,
) -> tuple[T, U]:
    """Run two different operations concurrently with per-thread DB cleanup."""

    def worker(fn: Callable[[], T | U]) -> T | U:
        close_old_connections()
        try:
            return fn()
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(worker, operation_a)
        future_b = pool.submit(worker, operation_b)
        result_a = future_a.result(timeout=result_timeout)
        result_b = future_b.result(timeout=result_timeout)
    _close_worker_connections()
    time.sleep(0.05)
    _close_worker_connections()
    return result_a, result_b
