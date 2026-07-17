"""Relational models for the document tree, versions, and selections.

The tree/versions/selections live in SQLite (this file). LLM-generated output
lives in a separate JSON document store (see app/doc_store.py).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)

    versions: Mapped[list["Version"]] = relationship(back_populates="document")


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("document_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, ...
    source_hash: Mapped[str] = mapped_column(String)  # hash of raw markdown
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document: Mapped["Document"] = relationship(back_populates="versions")
    nodes: Mapped[list["Node"]] = relationship(back_populates="version")


class Node(Base):
    """One heading section of the document, scoped to a single version.

    `logical_id` is the stable identity of a section across versions. Two nodes
    in different versions that represent "the same section" share a logical_id.
    """

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)

    logical_id: Mapped[str] = mapped_column(String, index=True)
    heading: Mapped[str] = mapped_column(String)
    level: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String)  # hash of heading + body
    path: Mapped[str] = mapped_column(String)  # human-readable heading path
    order_index: Mapped[int] = mapped_column(Integer)  # document order

    version: Mapped["Version"] = relationship(back_populates="nodes")
    children: Mapped[list["Node"]] = relationship(
        backref="parent", remote_side=[id], uselist=True, viewonly=True
    )


class Selection(Base):
    __tablename__ = "selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    items: Mapped[list["SelectionItem"]] = relationship(back_populates="selection")


class SelectionItem(Base):
    """A selection pins specific node rows. Because every Node row belongs to
    exactly one Version, referencing a node_id is inherently version-pinned."""

    __tablename__ = "selection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"))
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))

    selection: Mapped["Selection"] = relationship(back_populates="items")
