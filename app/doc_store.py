"""JSON document store for LLM-generated output (the "NoSQL" side).

We use a single JSON file rather than MongoDB to keep the project runnable with
zero external services; the access pattern here (append-only documents, read by
id / selection_id / node logical_id) is document-shaped and does not need a
server. This is justified in APPROACH.md. The interface is deliberately
narrow so it could be swapped for pymongo without touching callers.

Each generation stores a *snapshot* of the exact node content it was generated
from (logical_id + content_hash + body + version). That snapshot is what makes
staleness detectable after the document is re-versioned: it does not depend on
the source rows still existing unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

_STORE_PATH = os.environ.get("CT200_DOCSTORE", "generations.json")
_LOCK = threading.Lock()


def _load() -> dict:
    if not os.path.exists(_STORE_PATH):
        return {"seq": 0, "generations": []}
    with open(_STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _STORE_PATH)


def snapshot_signature(snapshot: list[dict]) -> str:
    """Stable fingerprint of the pinned source content, used to detect
    duplicate submissions of the same selection against the same text."""
    joined = "|".join(f"{s['logical_id']}:{s['content_hash']}" for s in snapshot)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def find_by_signature(selection_id: int, signature: str) -> dict | None:
    data = _load()
    for g in data["generations"]:
        if g["selection_id"] == selection_id and g.get("signature") == signature:
            return g
    return None


def create_generation(
    selection_id: int,
    selection_name: str,
    snapshot: list[dict],
    test_cases: list[dict],
    status: str,
    model_provider: str,
    error: str | None = None,
    raw_attempts: list[str] | None = None,
) -> dict:
    with _LOCK:
        data = _load()
        data["seq"] += 1
        record = {
            "id": data["seq"],
            "selection_id": selection_id,
            "selection_name": selection_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "model_provider": model_provider,
            "signature": snapshot_signature(snapshot),
            "source_snapshot": snapshot,
            "test_cases": test_cases,
            "error": error,
            "raw_attempts": raw_attempts,
        }
        data["generations"].append(record)
        _save(data)
        return record


def get_generation(gen_id: int) -> dict | None:
    for g in _load()["generations"]:
        if g["id"] == gen_id:
            return g
    return None


def find_by_selection(selection_id: int) -> list[dict]:
    return [g for g in _load()["generations"] if g["selection_id"] == selection_id]


def find_by_logical_id(logical_id: str) -> list[dict]:
    out = []
    for g in _load()["generations"]:
        if any(s["logical_id"] == logical_id for s in g["source_snapshot"]):
            out.append(g)
    return out
