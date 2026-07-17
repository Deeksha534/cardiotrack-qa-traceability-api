"""Pydantic request/response models for the API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    markdown: str = Field(min_length=1)


class NodeSummary(BaseModel):
    id: int
    logical_id: str
    heading: str
    level: int
    content_hash: str
    path: str


class NodeDetail(NodeSummary):
    body: str
    version_number: int
    children: list[NodeSummary]


class SelectionCreate(BaseModel):
    name: str = Field(min_length=1)
    node_ids: list[int] = Field(min_length=1)
