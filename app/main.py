"""FastAPI application wiring together ingestion, browse, selection,
generation, staleness, and retrieval."""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import doc_store, ingest, llm, models, versioning
from app.db import get_db, init_db
from app.schemas import IngestRequest, NodeDetail, NodeSummary, SelectionCreate

app = FastAPI(title="CardioTrack CT-200 QA Traceability API")


@app.on_event("startup")
def _startup():
    init_db()


def _node_summary(n: models.Node) -> dict:
    return {
        "id": n.id,
        "logical_id": n.logical_id,
        "heading": n.heading,
        "level": n.level,
        "content_hash": n.content_hash,
        "path": n.path,
    }


def _resolve_version(db: Session, doc_name: str, version: int | None) -> models.Version:
    doc = db.scalar(select(models.Document).where(models.Document.name == doc_name))
    if doc is None:
        raise HTTPException(404, f"document '{doc_name}' not found")
    if version is None:
        v = ingest.latest_version(db, doc_name)
    else:
        v = db.scalar(
            select(models.Version).where(
                models.Version.document_id == doc.id,
                models.Version.number == version,
            )
        )
    if v is None:
        raise HTTPException(404, "version not found")
    return v


# --- Ingestion -------------------------------------------------------------

@app.post("/documents/{doc_name}/versions")
def ingest_version(doc_name: str, req: IngestRequest, db: Session = Depends(get_db)):
    version = ingest.ingest(db, doc_name, req.markdown)
    count = len(
        db.scalars(select(models.Node).where(models.Node.version_id == version.id)).all()
    )
    return {
        "document": doc_name,
        "version": version.number,
        "source_hash": version.source_hash,
        "node_count": count,
    }


# --- Browse ----------------------------------------------------------------

@app.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(models.Document)).all()
    out = []
    for d in docs:
        versions = sorted(d.versions, key=lambda v: v.number)
        out.append(
            {"name": d.name, "versions": [v.number for v in versions]}
        )
    return out


@app.get("/documents/{doc_name}/sections")
def top_level_sections(
    doc_name: str,
    version: int | None = Query(None),
    db: Session = Depends(get_db),
):
    v = _resolve_version(db, doc_name, version)
    nodes = db.scalars(
        select(models.Node)
        .where(models.Node.version_id == v.id, models.Node.parent_id.is_(None))
        .order_by(models.Node.order_index)
    ).all()
    return {
        "document": doc_name,
        "version": v.number,
        "sections": [_node_summary(n) for n in nodes],
    }


@app.get("/nodes/{node_id}", response_model=NodeDetail)
def get_node(node_id: int, db: Session = Depends(get_db)):
    n = db.get(models.Node, node_id)
    if n is None:
        raise HTTPException(404, "node not found")
    children = db.scalars(
        select(models.Node)
        .where(models.Node.parent_id == n.id)
        .order_by(models.Node.order_index)
    ).all()
    return {
        **_node_summary(n),
        "body": n.body,
        "version_number": db.get(models.Version, n.version_id).number,
        "children": [NodeSummary(**_node_summary(c)) for c in children],
    }


@app.get("/search")
def search(
    q: str,
    doc_name: str | None = Query(None),
    version: int | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(models.Node).where(
        or_(models.Node.heading.ilike(f"%{q}%"), models.Node.body.ilike(f"%{q}%"))
    )
    if doc_name is not None:
        v = _resolve_version(db, doc_name, version)
        stmt = stmt.where(models.Node.version_id == v.id)
    nodes = db.scalars(stmt.order_by(models.Node.order_index)).all()
    return {"query": q, "results": [_node_summary(n) for n in nodes]}


@app.get("/nodes/{node_id}/changes")
def node_changes(node_id: int, db: Session = Depends(get_db)):
    n = db.get(models.Node, node_id)
    if n is None:
        raise HTTPException(404, "node not found")
    return versioning.node_change_across_versions(db, n)


# --- Selection -------------------------------------------------------------

@app.post("/selections")
def create_selection(req: SelectionCreate, db: Session = Depends(get_db)):
    for nid in req.node_ids:
        if db.get(models.Node, nid) is None:
            raise HTTPException(400, f"node {nid} does not exist")
    sel = models.Selection(name=req.name)
    db.add(sel)
    db.flush()
    for nid in req.node_ids:
        db.add(models.SelectionItem(selection_id=sel.id, node_id=nid))
    db.commit()
    return _selection_view(db, sel.id)


def _selection_view(db: Session, selection_id: int) -> dict:
    sel = db.get(models.Selection, selection_id)
    if sel is None:
        raise HTTPException(404, "selection not found")
    items = db.scalars(
        select(models.SelectionItem).where(
            models.SelectionItem.selection_id == selection_id
        )
    ).all()
    pinned = []
    for it in items:
        n = db.get(models.Node, it.node_id)
        v = db.get(models.Version, n.version_id)
        doc = db.get(models.Document, v.document_id)
        pinned.append(
            {
                "node_id": n.id,
                "logical_id": n.logical_id,
                "heading": n.heading,
                "content_hash": n.content_hash,
                "body": n.body,
                "version_number": v.number,
                "document_id": doc.id,
                "document_name": doc.name,
            }
        )
    return {"id": sel.id, "name": sel.name, "pinned_nodes": pinned}


@app.get("/selections/{selection_id}")
def get_selection(selection_id: int, db: Session = Depends(get_db)):
    return _selection_view(db, selection_id)


# --- Generation ------------------------------------------------------------

@app.post("/selections/{selection_id}/generate")
def generate(
    selection_id: int,
    force: bool = Query(False, description="create a fresh generation even if an identical one exists"),
    db: Session = Depends(get_db),
):
    view = _selection_view(db, selection_id)
    snapshot = view["pinned_nodes"]
    signature = doc_store.snapshot_signature(snapshot)

    # Duplicate-submission policy: identical selection + identical pinned text
    # returns the cached generation (idempotent) unless force=true. Rationale in
    # APPROACH.md — generation costs money and the inputs are pinned, so a repeat
    # request should not silently diverge or double-bill.
    if not force:
        existing = doc_store.find_by_signature(selection_id, signature)
        if existing is not None:
            return {"reused": True, **existing}

    provider = os.environ.get("CT200_LLM_PROVIDER", "mock")
    sections = [
        {"logical_id": s["logical_id"], "heading": s["heading"], "body": s["body"]}
        for s in snapshot
    ]
    try:
        result = llm.generate_test_cases(sections)
        record = doc_store.create_generation(
            selection_id=selection_id,
            selection_name=view["name"],
            snapshot=snapshot,
            test_cases=[tc.model_dump() for tc in result.test_cases],
            status="completed",
            model_provider=provider,
        )
        return {"reused": False, **record}
    except llm.GenerationError as e:
        # We do not raise: we persist the failure so it is auditable and the
        # caller can see exactly what the model returned.
        record = doc_store.create_generation(
            selection_id=selection_id,
            selection_name=view["name"],
            snapshot=snapshot,
            test_cases=[],
            status="failed",
            model_provider=provider,
            error=str(e),
            raw_attempts=e.attempts,
        )
        raise HTTPException(
            502,
            {"message": "LLM generation failed structured-output validation", "generation": record},
        )


# --- Staleness + Retrieval -------------------------------------------------

def _staleness_report(db: Session, generation: dict) -> dict:
    """For each pinned source section, compare against the current latest
    version of its document and classify the change."""
    items = []
    overall = "current"
    for s in generation["source_snapshot"]:
        doc = db.get(models.Document, s["document_id"])
        latest = ingest.latest_version(db, doc.name) if doc else None
        current = (
            versioning.node_in_version(db, s["logical_id"], latest.id)
            if latest
            else None
        )
        if current is None:
            status = "removed"
            detail = {"note": "section no longer present in latest version"}
        elif current.content_hash == s["content_hash"]:
            status = "current"
            detail = {}
        else:
            severity = versioning.classify_staleness(s["body"], current.body)
            status = "stale"
            detail = {
                "severity": severity,
                "diff": versioning.diff_summary(s["body"], current.body),
                "latest_version": latest.number,
            }
        if status != "current":
            overall = "stale"
        items.append(
            {
                "logical_id": s["logical_id"],
                "heading": s["heading"],
                "pinned_version": s["version_number"],
                "pinned_content_hash": s["content_hash"],
                "current_content_hash": current.content_hash if current else None,
                "status": status,
                **detail,
            }
        )
    return {"overall": overall, "sections": items}


def _with_staleness(db: Session, g: dict) -> dict:
    return {**g, "staleness": _staleness_report(db, g)}


@app.get("/generations/{gen_id}")
def get_generation(gen_id: int, db: Session = Depends(get_db)):
    g = doc_store.get_generation(gen_id)
    if g is None:
        raise HTTPException(404, "generation not found")
    return _with_staleness(db, g)


@app.get("/selections/{selection_id}/generations")
def generations_by_selection(selection_id: int, db: Session = Depends(get_db)):
    gens = doc_store.find_by_selection(selection_id)
    return [_with_staleness(db, g) for g in gens]


@app.get("/generations")
def generations_by_node(
    logical_id: str = Query(..., description="return generations whose source included this node"),
    db: Session = Depends(get_db),
):
    gens = doc_store.find_by_logical_id(logical_id)
    return [_with_staleness(db, g) for g in gens]
