"""Markdown -> hierarchical section tree.

This is deliberately NOT a generic markdown parser. It handles the specific
irregularities present in the CT-200 manual (see APPROACH.md):

  * a document preamble that appears before the first heading
  * ATX headings whose level "skips" (e.g. H1 -> H3), which must not be
    mis-parented
  * duplicate sibling headings, which must produce distinct nodes
  * `#` characters inside fenced code blocks, which must NOT be read as headings
  * trailing whitespace / inconsistent spacing around heading text

The parser emits a flat, document-ordered list of ParsedNode; parent links are
expressed as indices into that list so persistence stays trivial.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

PREAMBLE_HEADING = "(document preamble)"


@dataclass
class ParsedNode:
    heading: str
    level: int
    body: str
    path: str            # human-readable heading path, e.g. "2. Safety > 2.1 ..."
    logical_id: str      # stable, disambiguated key used to match across versions
    parent_index: int | None
    order_index: int
    content_hash: str = field(default="")


def _slug(heading: str) -> str:
    return re.sub(r"\s+", " ", heading.strip().lower())


def content_hash(heading: str, body: str) -> str:
    """Hash of the section's own content (heading + body), whitespace-normalized
    per line so that reflowing/indentation noise does not read as a change but a
    real word/number change does."""
    norm_body = "\n".join(line.rstrip() for line in body.strip().splitlines())
    payload = f"{heading.strip()}\n{norm_body}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse(markdown: str) -> list[ParsedNode]:
    lines = markdown.splitlines()

    # (level, node_index) stack of open ancestors; used to find parents even
    # when heading levels skip.
    stack: list[tuple[int, int]] = []
    nodes: list[ParsedNode] = []
    # buffers for body text of the "current" node
    current_idx: int | None = None
    body_lines: list[str] = []
    preamble_lines: list[str] = []

    # track duplicate logical_ids so siblings with identical headings diverge
    seen_logical: dict[str, int] = {}

    in_fence = False

    def flush_body():
        nonlocal body_lines
        if current_idx is not None:
            nodes[current_idx].body = "\n".join(body_lines).strip()
        body_lines = []

    for raw in lines:
        fence = FENCE_RE.match(raw)
        if fence:
            in_fence = not in_fence
            (body_lines if current_idx is not None else preamble_lines).append(raw)
            continue

        heading_match = None if in_fence else HEADING_RE.match(raw)
        if heading_match is None:
            (body_lines if current_idx is not None else preamble_lines).append(raw)
            continue

        # It's a real heading -> close out the previous node's body.
        flush_body()

        level = len(heading_match.group(1))
        heading = heading_match.group(2).strip()

        # Parent = nearest ancestor on the stack with a strictly smaller level.
        # This is what protects against mis-parenting on a skipped level.
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_index = stack[-1][1] if stack else None

        parent_path = nodes[parent_index].logical_id if parent_index is not None else ""
        base_logical = f"{parent_path}/{_slug(heading)}"
        # disambiguate duplicate siblings
        count = seen_logical.get(base_logical, 0)
        seen_logical[base_logical] = count + 1
        logical_id = base_logical if count == 0 else f"{base_logical}#{count + 1}"

        parent_disp = nodes[parent_index].path if parent_index is not None else ""
        disp_path = f"{parent_disp} > {heading}" if parent_disp else heading

        node = ParsedNode(
            heading=heading,
            level=level,
            body="",
            path=disp_path,
            logical_id=logical_id,
            parent_index=parent_index,
            order_index=len(nodes),
        )
        nodes.append(node)
        current_idx = len(nodes) - 1
        stack.append((level, current_idx))

    flush_body()

    # If the file opened with text before any heading, keep it as a real node so
    # it is never silently dropped.
    preamble = "\n".join(preamble_lines).strip()
    if preamble:
        # Shift every existing parent_index/order_index by one, then prepend the
        # preamble node so all references stay consistent.
        for n in nodes:
            if n.parent_index is not None:
                n.parent_index += 1
            n.order_index += 1
        pre = ParsedNode(
            heading=PREAMBLE_HEADING,
            level=0,
            body=preamble,
            path=PREAMBLE_HEADING,
            logical_id="/__preamble__",
            parent_index=None,
            order_index=0,
        )
        nodes.insert(0, pre)

    for n in nodes:
        n.content_hash = content_hash(n.heading, n.body)

    return nodes
