# End-to-end demo (Windows / PowerShell): ingest v1 -> browse -> select ->
# generate -> ingest v2 -> detect change -> show generation is now STALE.
#
# Requires the API running on :8000 (see README_WINDOWS.md). Uses the mock LLM.
# Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts\demo.ps1

$ErrorActionPreference = "Stop"
$base = if ($env:BASE) { $env:BASE } else { "http://localhost:8000" }
$doc = "ct200"

function Body($path) { @{ markdown = (Get-Content $path -Raw) } | ConvertTo-Json }

Write-Host "== 1. Ingest v1 =="
Invoke-RestMethod -Method Post -Uri "$base/documents/$doc/versions" `
  -ContentType 'application/json' -Body (Body "data\ct200_manual.md") | Format-List

Write-Host "== 2. Top-level sections (latest) =="
(Invoke-RestMethod "$base/documents/$doc/sections").sections |
  Select-Object id, heading | Format-Table

Write-Host "== 3. Find the overpressure section (search) =="
$q = [uri]::EscapeDataString("never exceed")
$nodeId = (Invoke-RestMethod "$base/search?q=$q&doc_name=$doc").results[0].id
Write-Host "overpressure node id = $nodeId"
Invoke-RestMethod "$base/nodes/$nodeId" | Select-Object id, heading, content_hash, body | Format-List

Write-Host "== 4. Create a version-pinned selection =="
$sel = Invoke-RestMethod -Method Post -Uri "$base/selections" -ContentType 'application/json' `
  -Body (@{ name = "overpressure-review"; node_ids = @($nodeId) } | ConvertTo-Json)
$selId = $sel.id
Write-Host "selection id = $selId"

Write-Host "== 5. Generate QA test cases =="
$gen = Invoke-RestMethod -Method Post -Uri "$base/selections/$selId/generate"
$genId = $gen.id
$gen.test_cases | Select-Object title, expected_result | Format-List
Write-Host "generation id = $genId"

Write-Host "== 6. Retrieve generation -> should be CURRENT =="
(Invoke-RestMethod "$base/generations/$genId").staleness | ConvertTo-Json -Depth 6

Write-Host "== 7. Ingest v2 (threshold 300 -> 320 mmHg) =="
Invoke-RestMethod -Method Post -Uri "$base/documents/$doc/versions" `
  -ContentType 'application/json' -Body (Body "data\ct200_manual_v2.md") | Format-List

Write-Host "== 8. Node change across versions (lightweight diff) =="
Invoke-RestMethod "$base/nodes/$nodeId/changes" | ConvertTo-Json -Depth 8

Write-Host "== 9. Retrieve the SAME generation -> now STALE (material) =="
(Invoke-RestMethod "$base/generations/$genId").staleness | ConvertTo-Json -Depth 8

Write-Host "== 10. Retrieve by node logical_id (traceability from a node) =="
$lid = (Invoke-RestMethod "$base/nodes/$nodeId").logical_id
$lidEnc = [uri]::EscapeDataString($lid)
Invoke-RestMethod "$base/generations?logical_id=$lidEnc" |
  ForEach-Object { [pscustomobject]@{ id = $_.id; overall = $_.staleness.overall } } | Format-Table

Write-Host "== DONE =="
