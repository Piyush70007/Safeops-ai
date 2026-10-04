"""Lab-only fault injection (FAULTS_ENABLED=true). Used by the incident replay lab.

Supported faults: error_rate (share of business requests answered with 500), latency_ms,
cpu (burn one core for N seconds) and memory (hold N MB). Never enabled in production.
"""

import random
import threading
import time

from app.common.metrics import FAULT_ACTIVE


class Faults:
    def __init__(self) -> None:
        self.error_rate = 0.0
        self.latency_ms = 0
        self._ballast: list[bytearray] = []
        self._cpu_until = 0.0

    def snapshot(self) -> dict:
        return {
            "error_rate": self.error_rate,
            "latency_ms": self.latency_ms,
            "memory_mb": len(self._ballast),
            "cpu_active": time.monotonic() < self._cpu_until,
        }

    def configure(self, error_rate=None, latency_ms=None, memory_mb=None, cpu_seconds=None):
        if error_rate is not None:
            self.error_rate = max(0.0, min(1.0, error_rate))
            FAULT_ACTIVE.labels("error_rate").set(1 if self.error_rate else 0)
        if latency_ms is not None:
            self.latency_ms = max(0, min(10_000, latency_ms))
            FAULT_ACTIVE.labels("latency").set(1 if self.latency_ms else 0)
        if memory_mb is not None:
            self._ballast = [bytearray(1024 * 1024) for _ in range(max(0, min(2048, memory_mb)))]
            FAULT_ACTIVE.labels("memory").set(1 if self._ballast else 0)
        if cpu_seconds:
            self._cpu_until = time.monotonic() + min(600, cpu_seconds)
            FAULT_ACTIVE.labels("cpu").set(1)
            threading.Thread(target=self._burn, daemon=True).start()
        return self.snapshot()

    def reset(self) -> dict:
        self._cpu_until = 0.0
        return self.configure(error_rate=0.0, latency_ms=0, memory_mb=0)

    def _burn(self) -> None:
        while time.monotonic() < self._cpu_until:
            sum(i * i for i in range(10_000))
        FAULT_ACTIVE.labels("cpu").set(0)

    def should_fail(self) -> bool:
        return self.error_rate > 0 and random.random() < self.error_rate  # noqa: S311 - not crypto

    def delay(self) -> None:
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
