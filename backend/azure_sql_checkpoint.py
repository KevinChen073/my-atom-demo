"""Synchronous LangGraph checkpoint saver backed by Azure SQL.

This implements the BaseCheckpointSaver contract used by MYATOM. Checkpoint
serialization stays with LangGraph; SQL stores opaque bytes and ordered writes.
Each call owns its connection because mssql-python connections are not shared
between worker threads.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator, Sequence
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP, BaseCheckpointSaver, ChannelVersions, Checkpoint,
    CheckpointMetadata, CheckpointTuple, get_checkpoint_id,
    get_serializable_checkpoint_metadata, writes_sort_key,
)

from .azure_sql import azure_sql_connection


class AzureSqlSaver(BaseCheckpointSaver[str]):
    def __init__(self, connection_string: str):
        super().__init__()
        self.connection_string = connection_string

    def close(self) -> None:
        """Connections are scoped per method; retain Workflow's close contract."""

    def _tuple(self, db: Any, row: dict[str, Any]) -> CheckpointTuple:
        thread_id, namespace, checkpoint_id = row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"]
        pending = db.execute("""SELECT task_id, channel, data_type, value, task_path, idx
            FROM myatom_checkpoint_writes WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?""",
            (thread_id, namespace, checkpoint_id)).fetchall()
        pending.sort(key=lambda item: writes_sort_key(item["task_path"], item["task_id"], item["idx"]))
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace, "checkpoint_id": checkpoint_id}}
        parent = ({"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                    "checkpoint_id": row["parent_checkpoint_id"]}}
                  if row["parent_checkpoint_id"] else None)
        return CheckpointTuple(
            config,
            self.serde.loads_typed((row["data_type"], bytes(row["checkpoint"]))),
            cast(CheckpointMetadata, json.loads(row["metadata"])),
            parent,
            [(item["task_id"], item["channel"], self.serde.loads_typed((item["data_type"], bytes(item["value"]))))
             for item in pending],
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        values = config["configurable"]
        thread_id, namespace = str(values["thread_id"]), str(values.get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)
        with azure_sql_connection(self.connection_string) as db:
            if checkpoint_id:
                row = db.execute("""SELECT * FROM myatom_checkpoints
                    WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?""",
                    (thread_id, namespace, checkpoint_id)).fetchone()
            else:
                row = db.execute("""SELECT TOP (1) * FROM myatom_checkpoints
                    WHERE thread_id=? AND checkpoint_ns=? ORDER BY checkpoint_id DESC""",
                    (thread_id, namespace)).fetchone()
            return self._tuple(db, row) if row else None

    def list(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
             before: RunnableConfig | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        if limit is not None and limit <= 0:
            return
        clauses: list[str] = []
        params: list[Any] = []
        if config:
            values = config["configurable"]
            clauses.append("thread_id=?")
            params.append(str(values["thread_id"]))
            if values.get("checkpoint_ns") is not None:
                clauses.append("checkpoint_ns=?")
                params.append(str(values["checkpoint_ns"]))
            if checkpoint_id := get_checkpoint_id(config):
                clauses.append("checkpoint_id=?")
                params.append(checkpoint_id)
        if before and (checkpoint_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id<?")
            params.append(checkpoint_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with azure_sql_connection(self.connection_string) as db:
            rows = db.execute("SELECT * FROM myatom_checkpoints" + where + " ORDER BY checkpoint_id DESC", params).fetchall()
            results = []
            for row in rows:
                item = self._tuple(db, row)
                if filter and any(item.metadata.get(key) != value for key, value in filter.items()):
                    continue
                results.append(item)
                if limit is not None and len(results) >= limit:
                    break
        yield from results

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata,
            new_versions: ChannelVersions) -> RunnableConfig:
        values = config["configurable"]
        thread_id, namespace = str(values["thread_id"]), str(values.get("checkpoint_ns", ""))
        data_type, data = self.serde.dumps_typed(checkpoint)
        safe_metadata = get_serializable_checkpoint_metadata(config, metadata)
        key = (thread_id, namespace, checkpoint["id"])
        body = (values.get("checkpoint_id"), data_type, data, json.dumps(safe_metadata, ensure_ascii=False))
        with azure_sql_connection(self.connection_string) as db:
            db.execute("""IF EXISTS (SELECT 1 FROM myatom_checkpoints WITH (UPDLOCK, HOLDLOCK)
                WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?)
                UPDATE myatom_checkpoints SET parent_checkpoint_id=?, data_type=?, [checkpoint]=?, metadata=?
                WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?
                ELSE INSERT INTO myatom_checkpoints
                (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, data_type, [checkpoint], metadata)
                VALUES (?,?,?,?,?,?,?)""", key + body + key + key + body)
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                 "checkpoint_id": checkpoint["id"]}}

    def put_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
                   task_id: str, task_path: str = "") -> None:
        values = config["configurable"]
        thread_id, namespace, checkpoint_id = (str(values["thread_id"]),
                                               str(values.get("checkpoint_ns", "")),
                                               str(values["checkpoint_id"]))
        replace = all(channel in WRITES_IDX_MAP for channel, _ in writes)
        with azure_sql_connection(self.connection_string) as db:
            for index, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, index)
                data_type, data = self.serde.dumps_typed(value)
                key = (thread_id, namespace, checkpoint_id, task_id, idx)
                if replace:
                    db.execute("""IF EXISTS (SELECT 1 FROM myatom_checkpoint_writes WITH (UPDLOCK, HOLDLOCK)
                        WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=? AND task_id=? AND idx=?)
                        UPDATE myatom_checkpoint_writes SET task_path=?, channel=?, data_type=?, value=?
                        WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=? AND task_id=? AND idx=?
                        ELSE INSERT INTO myatom_checkpoint_writes
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, task_path, idx, channel, data_type, value)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        key + (task_path, channel, data_type, data) + key +
                        (thread_id, namespace, checkpoint_id, task_id, task_path, idx, channel, data_type, data))
                else:
                    db.execute("""IF NOT EXISTS (SELECT 1 FROM myatom_checkpoint_writes WITH (UPDLOCK, HOLDLOCK)
                        WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=? AND task_id=? AND idx=?)
                        INSERT INTO myatom_checkpoint_writes
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, task_path, idx, channel, data_type, value)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        key + (thread_id, namespace, checkpoint_id, task_id, task_path, idx, channel, data_type, data))

    def delete_thread(self, thread_id: str) -> None:
        with azure_sql_connection(self.connection_string) as db:
            db.execute("DELETE FROM myatom_checkpoint_writes WHERE thread_id=?", (str(thread_id),))
            db.execute("DELETE FROM myatom_checkpoints WHERE thread_id=?", (str(thread_id),))

    def get_next_version(self, current: str | None, channel: None) -> str:
        current_v = 0 if current is None else current if isinstance(current, int) else int(current.split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"
