"""Append-only, hash-chained audit log.

Each record contains the SHA-256 of the previous record. Editing, deleting or reordering
any line breaks the chain, and verify() reports exactly where.
"""

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

GENESIS = "0" * 64


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last = GENESIS
        self._seq = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                self._last, self._seq = record["hash"], record["seq"]

    def append(self, kind: str, incident_id: str | None, /, **data) -> dict:
        with self._lock:
            record = {
                "seq": self._seq + 1,
                "at": datetime.now(UTC).isoformat(),
                "kind": kind,
                "incident_id": incident_id,
                "data": data,
                "prev_hash": self._last,
            }
            record["hash"] = _digest(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
            self._last, self._seq = record["hash"], record["seq"]
            return record

    def records(self, incident_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        return [r for r in rows if incident_id is None or r["incident_id"] == incident_id]


def verify(path: Path) -> list[str]:
    problems, previous = [], GENESIS
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        record = json.loads(line)
        if record.get("prev_hash") != previous:
            problems.append(f"line {number}: chain broken (record removed or reordered)")
        if _digest(record) != record.get("hash"):
            problems.append(f"line {number}: content modified")
        previous = record.get("hash")
    return problems
