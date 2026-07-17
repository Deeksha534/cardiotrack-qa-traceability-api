#!/usr/bin/env bash
# End-to-end demo: ingest v1 -> browse -> select -> generate -> ingest v2 ->
# detect change -> show generation is now flagged STALE at retrieval.
#
# Requires the API running on :8000 (see README). Uses the mock LLM by default.
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
DOC="ct200"
jq_or_cat() { if command -v jq >/dev/null; then jq "$@"; else cat; fi; }

echo "== 1. Ingest v1 =="
curl -sf -X POST "$BASE/documents/$DOC/versions" \
  -H 'Content-Type: application/json' \
  --data @<(python3 -c 'import json,sys;print(json.dumps({"markdown":open("data/ct200_manual.md").read()}))') \
  | jq_or_cat

echo "== 2. Top-level sections (latest) =="
curl -sf "$BASE/documents/$DOC/sections" | jq_or_cat '.sections[] | {id, heading}'

echo "== 3. Find the overpressure section (search) =="
NODE_ID=$(curl -sf "$BASE/search?q=exceed%20300&doc_name=$DOC" | jq -r '.results[0].id')
echo "overpressure node id = $NODE_ID"
curl -sf "$BASE/nodes/$NODE_ID" | jq_or_cat '{id, heading, content_hash, body}'

echo "== 4. Create a version-pinned selection =="
SEL_ID=$(curl -sf -X POST "$BASE/selections" -H 'Content-Type: application/json' \
  -d "{\"name\":\"overpressure-review\",\"node_ids\":[$NODE_ID]}" | jq -r '.id')
echo "selection id = $SEL_ID"

echo "== 5. Generate QA test cases =="
GEN_ID=$(curl -sf -X POST "$BASE/selections/$SEL_ID/generate" | tee /tmp/gen.json | jq -r '.id')
jq_or_cat '.test_cases[] | {title, expected_result}' < /tmp/gen.json
echo "generation id = $GEN_ID"

echo "== 6. Retrieve generation -> should be CURRENT =="
curl -sf "$BASE/generations/$GEN_ID" | jq_or_cat '.staleness'

echo "== 7. Ingest v2 (threshold 300 -> 320 mmHg) =="
curl -sf -X POST "$BASE/documents/$DOC/versions" \
  -H 'Content-Type: application/json' \
  --data @<(python3 -c 'import json;print(json.dumps({"markdown":open("data/ct200_manual_v2.md").read()}))') \
  | jq_or_cat

echo "== 8. Node change across versions (lightweight diff) =="
curl -sf "$BASE/nodes/$NODE_ID/changes" | jq_or_cat '{changed_across_versions, history}'

echo "== 9. Retrieve the SAME generation -> now STALE (material: number changed) =="
curl -sf "$BASE/generations/$GEN_ID" | jq_or_cat '.staleness'

echo "== 10. Retrieve by node logical_id (traceability from a node) =="
LID=$(curl -sf "$BASE/nodes/$NODE_ID" | jq -r '.logical_id')
curl -sf --get "$BASE/generations" --data-urlencode "logical_id=$LID" \
  | jq_or_cat '.[] | {id, "overall": .staleness.overall}'

echo "== DONE =="
