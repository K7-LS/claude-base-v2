# session_start.ps1 - project-memory SessionStart hook (skill project-memory)
# If cwd (or a parent, up to 12 levels) is a memory project (has Claude\<journal>):
#   1) prints the top 2 journal entries into session context ("read journal first"),
#   2) writes a session marker used by session_end.ps1 (Stop) to detect an
#      "unclosed" session (files changed, journal not updated).
# Outside memory projects: bootstrap a nearby CLAUDE.md if present, otherwise no-op.
# NEVER breaks a session (exit 0 always).
# ASCII-only source on purpose (PowerShell 5.1 / no-BOM robustness).
# Journal file name is Russian ("ZHURNAL SESSIY.md"), assembled from codepoints.

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch {}

$JournalName = (-join ([char]0x0416,[char]0x0423,[char]0x0420,[char]0x041D,[char]0x0410,[char]0x041B)) + ' ' + `
               (-join ([char]0x0421,[char]0x0415,[char]0x0421,[char]0x0421,[char]0x0418,[char]0x0419)) + '.md'

try {
  $raw = [Console]::In.ReadToEnd()
  $inp = $null
  if ($raw) { $inp = $raw | ConvertFrom-Json }
  $cwd = ''
  if ($inp -and $inp.cwd) { $cwd = [string]$inp.cwd } else { $cwd = (Get-Location).Path }
  $sid = ''
  if ($inp -and $inp.session_id) { $sid = [string]$inp.session_id }

  $stateDir = $env:PROJECT_MEMORY_STATE_DIR
  if (-not $stateDir) { $stateDir = Join-Path $HOME '.claude\.local-state\project-memory' }
  New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

  # housekeeping: drop session markers older than 7 days (local state hygiene
  # only - NOT curation/reminder logic; that logic has no day thresholds)
  Get-ChildItem -LiteralPath $stateDir -Filter 'session_*.json' -EA SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force -EA SilentlyContinue

  # walk up from cwd looking for <root>\Claude\<journal>
  $root = $null; $journal = $null; $claudeRoot = $null
  $d = $null
  if (Test-Path -LiteralPath $cwd) { $d = Get-Item -LiteralPath $cwd }
  for ($i = 0; ($i -lt 12) -and $d; $i++) {
    if (-not $claudeRoot) {
      $rootClaude = Join-Path $d.FullName 'CLAUDE.md'
      if (Test-Path -LiteralPath $rootClaude) {
        $isMemoryDir = $false
        if (($d.Name -eq 'Claude') -and $d.Parent) {
          $parentClaude = Join-Path $d.Parent.FullName 'CLAUDE.md'
          $isMemoryDir = (Test-Path -LiteralPath (Join-Path $d.FullName $JournalName)) -or
                         (Test-Path -LiteralPath $parentClaude)
        }
        if ($isMemoryDir) {
          $claudeRoot = $d.Parent.FullName
        } else {
          $claudeRoot = $d.FullName
        }
      }
    }
    $cand = Join-Path (Join-Path $d.FullName 'Claude') $JournalName
    if (Test-Path -LiteralPath $cand) { $root = $d.FullName; $journal = $cand; break }
    if ($d.Name -eq 'Claude') {
      $cand2 = Join-Path $d.FullName $JournalName
      if (Test-Path -LiteralPath $cand2) { $root = $d.Parent.FullName; $journal = $cand2; break }
    }
    $d = $d.Parent
  }

  # Project AGENTS bootstrap: content-based and ownership-safe in the generator.
  # This also covers a plain project with only root CLAUDE.md and no memory journal.
  if (-not $claudeRoot -and $root) { $claudeRoot = $root }
  if ($claudeRoot) {
    $toolsDir = Split-Path $PSScriptRoot -Parent
    $generator = Join-Path $toolsDir 'gen_project_agents.py'
    if (Test-Path -LiteralPath $generator) {
      & python $generator --quiet-current $claudeRoot
    }
  }
  if (-not $journal) { exit 0 }   # not a memory project - stay silent

  if ($sid) {
    $marker = Join-Path $stateDir ("session_" + $sid + ".json")
    $obj = @{
      start_epoch  = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
      project_root = $root
      journal      = $journal
      reminded     = $false
    }
    $obj | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
  }

  # print top of the journal: up to 2 entries, capped at 60 lines
  $lines = @(Get-Content -LiteralPath $journal -Encoding UTF8)
  $starts = @()
  for ($i = 0; $i -lt $lines.Count; $i++) {
    # entries start with a dated header (## YYYY-...); a bare '## *' would also
    # match the entry template inside the fenced code block of the header
    if ($lines[$i] -match '^## \d{4}-') { $starts += $i }
  }
  $rel = $journal.Substring($root.Length).TrimStart('\','/')
  Write-Output ("[project-memory] Memory project detected (root: " + (Split-Path $root -Leaf) + ").")
  Write-Output ("Top of the session journal (" + $rel + "); also read Claude\STATUS.md; at session end add your entry ON TOP and update STATUS:")
  Write-Output ""
  if ($starts.Count -ge 1) {
    $end = $lines.Count - 1
    if ($starts.Count -ge 3) { $end = $starts[2] - 1 }
    $cap = $starts[0] + 59
    if ($end -gt $cap) { $end = $cap }
    $lines[$starts[0]..$end] | ForEach-Object { Write-Output $_ }
  } else {
    $lines | Select-Object -First 20 | ForEach-Object { Write-Output $_ }
  }

} catch {}
exit 0
