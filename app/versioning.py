"""Cross-version comparison: node change detection, lightweight diffs, and
staleness classification for generated test cases."""
from __future__ import annotations

import difflib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def node_in_version(db: Session, logical_id: str, version_id: int) -> models.Node | None:
    return db.scalar(
        select(models.Node).where(
            models.Node.logical_id == logical_id,
            models.Node.version_id == version_id,
        )
    )


def all_versions_for_node(db: Session, node: models.Node) -> list[models.Version]:
    doc_id = db.get(models.Version, node.version_id).document_id
    versions = db.scalars(
        select(models.Version).where(models.Version.document_id == doc_id)
    ).all()
    return sorted(versions, key=lambda v: v.number)


def diff_summary(old_body: str, new_body: str, context: int = 0) -> dict:
    old_lines = old_body.splitlines()
    new_lines = new_body.splitlines()
    added = [l for l in new_lines if l not in old_lines]
    removed = [l for l in old_lines if l not in new_lines]
    udiff = list(
        difflib.unified_diff(old_lines, new_lines, lineterm="", n=context)
    )
    ratio = difflib.SequenceMatcher(None, old_body, new_body).ratio()
    return {
        "similarity": round(ratio, 4),
        "added_lines": added,
        "removed_lines": removed,
        "unified_diff": udiff,
    }


def node_change_across_versions(db: Session, node: models.Node) -> dict:
    """Given a node, report whether its section changed across versions and,
    if so, a lightweight diff against the previous version that had it."""
    versions = all_versions_for_node(db, node)
    history = []
    prev: models.Node | None = None
    for v in versions:
        n = node_in_version(db, node.logical_id, v.id)
        entry = {
            "version": v.number,
            "present": n is not None,
            "content_hash": n.content_hash if n else None,
            "changed_from_prev": None,
            "diff": None,
        }
        if n is not None and prev is not None:
            changed = n.content_hash != prev.content_hash
            entry["changed_from_prev"] = changed
            if changed:
                entry["diff"] = diff_summary(prev.body, n.body)
        if n is not None:
            prev = n
        history.append(entry)

    changed_anywhere = any(h["changed_from_prev"] for h in history)
    return {
        "logical_id": node.logical_id,
        "heading": node.heading,
        "changed_across_versions": changed_anywhere,
        "history": history,
    }


def classify_staleness(old_body: str, new_body: str) -> str:
    """Coarse but honest severity classification.

    Returns one of: "unchanged", "cosmetic", "material".

    A key limitation, called out in APPROACH.md: this is a heuristic on the raw
    text. A one-word wording change and a changed pressure threshold both flip
    content_hash; we use a numeric-token check to *escalate* likely-material
    changes, but we cannot truly know intent. When in doubt we round UP to
    "material" so a reviewer is warned rather than falsely reassured.
    """
    if old_body.strip() == new_body.strip():
        return "unchanged"

    import re

    nums_old = set(re.findall(r"\d+(?:\.\d+)?", old_body))
    nums_new = set(re.findall(r"\d+(?:\.\d+)?", new_body))
    if nums_old != nums_new:
        return "material"  # a number changed -> treat as material (e.g. a threshold)

    ratio = difflib.SequenceMatcher(None, old_body, new_body).ratio()
    return "cosmetic" if ratio >= 0.95 else "material"
