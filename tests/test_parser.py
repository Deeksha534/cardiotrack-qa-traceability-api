"""Unit tests targeting the specific irregularities in the CT-200 manual.

Each test asserts a failure mode a naive line-based parser would fall into.
"""
from app.parser import PREAMBLE_HEADING, parse


def _by_heading(nodes, heading):
    return [n for n in nodes if n.heading == heading]


def test_duplicate_sibling_headings_are_distinct_nodes():
    md = """# 2. Safety

Intro.

## 2.1 Cuff Pressure Limits

First body: 300 mmHg.

## 2.1 Cuff Pressure Limits

Second body: fragile skin 280 mmHg.
"""
    nodes = parse(md)
    dupes = _by_heading(nodes, "2.1 Cuff Pressure Limits")
    assert len(dupes) == 2
    # distinct logical ids (distinct node identity)
    assert dupes[0].logical_id != dupes[1].logical_id
    # both parented to the same "2. Safety" node
    safety = _by_heading(nodes, "2. Safety")[0]
    safety_idx = nodes.index(safety)
    assert dupes[0].parent_index == safety_idx
    assert dupes[1].parent_index == safety_idx
    # bodies differ -> content hashes differ
    assert dupes[0].content_hash != dupes[1].content_hash


def test_skipped_heading_level_is_not_misparented():
    md = """# 3. Operation

Overview.

### 3.1.1 Starting a Measurement

Press START.
"""
    nodes = parse(md)
    op = _by_heading(nodes, "3. Operation")[0]
    child = _by_heading(nodes, "3.1.1 Starting a Measurement")[0]
    # H3 under H1 (H2 skipped): parent must be the H1, not None and not a sibling.
    assert child.parent_index == nodes.index(op)
    assert child.level == 3


def test_hash_inside_code_fence_is_not_a_heading():
    md = """# 4. Error Codes

## 4.1 Error Code Table

```
# error selection routine
if cuff_pressure > 300:
    display("E3")
```

E3 indicates overpressure.
"""
    nodes = parse(md)
    # "# error selection routine" must NOT become a node.
    assert not _by_heading(nodes, "error selection routine")
    table = _by_heading(nodes, "4.1 Error Code Table")[0]
    # the fenced content and trailing text stay in the table node's body
    assert "# error selection routine" in table.body
    assert "E3 indicates overpressure." in table.body


def test_preamble_before_first_heading_is_captured():
    md = """CardioTrack CT-200 Manual
Revision A

Read the safety section first.

# 1. Overview

Body.
"""
    nodes = parse(md)
    assert nodes[0].heading == PREAMBLE_HEADING
    assert "Revision A" in nodes[0].body
    assert nodes[0].parent_index is None
    # the real first heading still parses
    assert _by_heading(nodes, "1. Overview")


def test_trailing_whitespace_and_closing_hashes_are_stripped():
    md = "#   1. Overview   ###   \n\nBody.\n"
    nodes = parse(md)
    assert nodes[-1].heading == "1. Overview"
