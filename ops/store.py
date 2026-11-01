"""Read-only cross-project exception queries; never imports workbench settings."""

from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import quote


class DatabaseUnavailable(Exception):
    pass


class InvalidCursor(Exception):
    pass


FIELDS = "id, trace_id, project_id, run_id, source, phase, code, exception_type, reason, severity, occurred_at"


def encode_cursor(occurred_at: str, record_id: str) -> str:
    raw = json.dumps([occurred_at, record_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    if not cursor or len(cursor) > 500:
        raise InvalidCursor
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if (not isinstance(value, list) or len(value) != 2 or
                not all(isinstance(item, str) and 1 <= len(item) <= 80 for item in value)):
            raise ValueError
        return value[0], value[1]
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise InvalidCursor from exc


class ReadOnlyExceptionStore:
    def __init__(self, path: Path | None):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.path is None or not self.path.is_absolute() or not self.path.is_file():
            raise DatabaseUnavailable
        uri = "file:" + quote(self.path.as_posix(), safe="/:") + "?mode=ro"
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(uri, uri=True, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("SELECT 1 FROM exception_records LIMIT 1")
        except sqlite3.Error as exc:
            if db is not None:
                db.close()
            raise DatabaseUnavailable from exc
        try:
            yield db
        except sqlite3.Error as exc:
            raise DatabaseUnavailable from exc
        finally:
            db.close()

    def list_records(self, *, limit: int, cursor: str | None, source: str | None,
                     code: str | None, project_id: str | None,
                     trace_id: str | None) -> dict:
        conditions: list[str] = []
        values: list[str | int] = []
        for column, value in (("source", source), ("code", code),
                              ("project_id", project_id), ("trace_id", trace_id)):
            if value:
                conditions.append(f"{column}=?")
                values.append(value)
        if cursor:
            at, record_id = decode_cursor(cursor)
            conditions.append("(occurred_at < ? OR (occurred_at = ? AND id < ?))")
            values.extend((at, at, record_id))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT {FIELDS} FROM exception_records{where} ORDER BY occurred_at DESC, id DESC LIMIT ?"
        values.append(limit + 1)
        with self.connection() as db:
            rows = db.execute(query, values).fetchall()
        items = [dict(row) for row in rows[:limit]]
        next_cursor = encode_cursor(items[-1]["occurred_at"], items[-1]["id"]) if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    def get_record(self, record_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(f"SELECT {FIELDS} FROM exception_records WHERE id=?", (record_id,)).fetchone()
            if row is None:
                return None
            timeline = []
            run_metrics = None
            build_checks = []
            if row["run_id"]:
                metrics = db.execute(
                    "SELECT created_at, active_seconds, model_calls, tokens_used FROM runs WHERE id=?",
                    (row["run_id"],),
                ).fetchone()
                if metrics is not None:
                    try:
                        elapsed = max(0, int((datetime.fromisoformat(row["occurred_at"]) -
                                              datetime.fromisoformat(metrics["created_at"])).total_seconds()))
                    except (TypeError, ValueError):
                        elapsed = None
                    run_metrics = {"created_at": metrics["created_at"],
                                   "elapsed_seconds": elapsed,
                                   "active_seconds": int(metrics["active_seconds"]) if metrics["active_seconds"] is not None else None,
                                   "model_calls": metrics["model_calls"],
                                   "tokens_used": metrics["tokens_used"]}
                # Deliberately avoid events.payload_json and all business content.
                timeline = [dict(item) for item in db.execute(
                    "SELECT seq, type, at FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 30",
                    (row["run_id"],),
                ).fetchall()]
                timeline.reverse()
                build_checks = [dict(item) for item in db.execute("""SELECT attempt, outcome, category,
                    command, exit_code, duration_seconds, fix_round, model_calls, tokens_used,
                    fingerprints_json, target_files_json, error_codes_json, stop_code, occurred_at
                    FROM build_check_attempts WHERE run_id=? ORDER BY attempt DESC LIMIT 60""",
                    (row["run_id"],)).fetchall()]
                for item in build_checks:
                    for name in ("fingerprints", "target_files", "error_codes"):
                        item[name] = json.loads(item.pop(name + "_json"))
                build_checks.reverse()
            return {"exception": dict(row), "timeline": timeline, "run_metrics": run_metrics,
                    "build_checks": build_checks}
