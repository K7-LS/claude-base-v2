# graph-staleness-check.ps1 - SessionStart hook (claude-base)
# Keeps the DETERMINISTIC navigation skeleton fresh (0 tokens) so Claude can
# trust it and navigate the base via query instead of grep.
#
#   * skeleton.json - deterministic backbone (agents/skills/memory/rules/...), built
#     WITHOUT an LLM from structural signals.
#   * graph.json - semantic ENRICHMENT (LLM, hub, occasional). Its staleness is NOT a
#     reason to distrust the graph: the skeleton is fresh.
#
# Freshness key: the installed release (base\VERSION), stamped into skeleton.json as
# built_at_commit=base-<version>. The skeleton is rebuilt once after a release is
# installed; otherwise the hook is silent. Never breaks session start (exit 0
# everywhere). ASCII-only on purpose (robust under PowerShell 5.1 / no-BOM).

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$base    = Join-Path $env:USERPROFILE '.claude'
$skel    = Join-Path $base 'graphify-out\skeleton.json'
$builder = Join-Path $base 'skills\graphify\tools\skeleton_build.py'
$pyfile  = Join-Path $base 'graphify-out\.graphify_python'
$log     = Join-Path $base 'graphify-out\skeleton-hook.log'
$version = Join-Path $base 'base\VERSION'
function Write-HookLog($m){ try { Add-Content -LiteralPath $log -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')+' | '+$m) -Encoding UTF8 -EA SilentlyContinue } catch {} }
if (-not (Test-Path -LiteralPath $builder)) { exit 0 }   # skeleton tool not installed - stay silent
if (-not (Test-Path -LiteralPath $version)) { exit 0 }   # release layer not installed - stay silent

$stamp = 'base-' + ([string](Get-Content -LiteralPath $version -Raw -Encoding UTF8)).Trim()
if ($stamp -notmatch '^base-\d+\.\d+\.\d+$') { exit 0 }

# is the skeleton fresh? (built_at_commit == base-<version>)
$fresh = $false
if (Test-Path -LiteralPath $skel) {
  $raw = Get-Content -LiteralPath $skel -Raw -Encoding UTF8
  if ($raw -match '"built_at_commit"\s*:\s*"([^"]+)"') {
    if ($Matches[1] -eq $stamp) { $fresh = $true }
  }
}
if ($fresh) { exit 0 }   # already fresh - quiet

# rebuild the skeleton (deterministic, 0 tokens, seconds)
$py = 'python'
if (Test-Path -LiteralPath $pyfile) {
  $p = ([string](Get-Content -LiteralPath $pyfile -Raw -Encoding UTF8)).Trim()
  if ($p) { $py = $p }
}
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $base
& $py $builder --commit $stamp *> $null
$ok = ($LASTEXITCODE -eq 0)
Pop-Location

if ($ok) {
  Write-HookLog "$stamp action=REBUILT-ok"
  Write-Output '[graph] base navigator (skeleton) rebuilt & fresh - query first: python skills/graphify/tools/graph_query.py "your question" (truth lives in source_file).'
} else {
  Write-HookLog "$stamp action=REBUILD-FAILED"
}
exit 0
