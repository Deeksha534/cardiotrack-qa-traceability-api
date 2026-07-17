"""Ingestion + versioning.

Re-ingesting a modified manual creates a NEW version rather than mutating the
old one. Logical identity is matched **by path** (the disambiguated heading
path from the parser's logical_id): a section keeps its logical_id across
versions if its heading-path is unchanged. Body changes are then detected by
comparing content_hash. See APPROACH.md for why path-based matching was chosen
and where it breaks.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.parser import parse


def _get_or_create_document(db: Session, name: str) -> models.Document:
    doc = db.scalar(select(models.Document).where(models.Document.name == name))
    if doc is None:
        doc = models.Document(name=name)
        db.add(doc)
        db.flush()
    return doc


def ingest(db: Session, doc_name: str, markdown: str) -> models.Version:
    doc = _get_or_create_document(db, doc_name)

    existing = db.scalars(
        select(models.Version).where(models.Version.document_id == doc.id)
    ).all()
    next_number = max((v.number for v in existing), default=0) + 1

    version = models.Version(
        document_id=doc.id,
        number=next_number,
        source_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    db.add(version)
    db.flush()

    parsed = parse(markdown)
    index_to_node: dict[int, models.Node] = {}
    for i, pn in enumerate(parsed):
        node = models.Node(
            version_id=version.id,
            parent_id=None,  # set after all rows exist
            logical_id=pn.logical_id,
            heading=pn.heading,
            level=pn.level,
            body=pn.body,
            content_hash=pn.content_hash,
            path=pn.path,
            order_index=pn.order_index,
        )
        db.add(node)
        db.flush()
        index_to_node[i] = node

    for i, pn in enumerate(parsed):
        if pn.parent_index is not None:
            index_to_node[i].parent_id = index_to_node[pn.parent_index].id

    db.commit()
    return version


def latest_version(db: Session, doc_name: str) -> models.Version | None:
    doc = db.scalar(select(models.Document).where(models.Document.name == doc_name))
    if doc is None:
        return None
    versions = db.scalars(
        select(models.Version).where(models.Version.document_id == doc.id)
    ).all()
    return max(versions, key=lambda v: v.number, default=None)
