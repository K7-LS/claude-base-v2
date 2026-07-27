# session_end.ps1 - project-memory Stop hook (skill project-memory)
# "A session that changed project files but wrote nothing to the session journal
#  is not closed." Fires AT MOST ONCE per session, only inside memory projects
# (marker written by session_start.ps1). Blocks the stop once (exit 2 + stderr)
# so Claude adds the journal entry. All other paths: silent exit 0.
# ASCII-only source on purpose (PowerShell 5.1 / no-BOM robustness).

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch {}

try {
  $raw = [Console]::In.ReadToEnd()
  if (-not $raw) { exit 0 }
  $inp = $raw | ConvertFrom-Json
  if ($inp.stop_hook_active -eq $true) { exit 0 }      # anti-loop guard
  $sid = ''
  if ($inp.session_id) { $sid = [string]$inp.session_id }
  if (-not $sid) { exit 0 }

  $stateDir = $env:PROJECT_MEMORY_STATE_DIR
  if (-not $stateDir) { $stateDir = Join-Path $HOME '.claude\.local-state\project-memory' }
  $marker = Join-Path $stateDir ("session_" + $sid + ".json")
  if (-not (Test-Path -LiteralPath $marker)) { exit 0 } # not a memory-project session

  $st = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $st) { exit 0 }
  if ($st.reminded -eq $true) { exit 0 }                # remind at most once
  $start = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$st.start_epoch).UtcDateTime

  $journal = [string]$st.journal
  $root    = [string]$st.project_root
  if (-not (Test-Path -LiteralPath $journal)) { exit 0 }
  if (-not (Test-Path -LiteralPath $root))    { exit 0 }

  $jw = (Get-Item -LiteralPath $journal).LastWriteTimeUtc
  if ($jw -gt $start) { exit 0 }                        # journal updated - all good

  # did anything else in the project change? (short-circuit on first hit;
  # journal itself, .curate and _backup_ folders excluded)
  $changed = Get-ChildItem -LiteralPath $root -Recurse -File -Force -EA SilentlyContinue |
    Where-Object {
      ($_.LastWriteTimeUtc -gt $start) -and
      ($_.FullName -ne $journal) -and
      ($_.FullName -notmatch '\\\.curate\\') -and
      ($_.FullName -notmatch '\\_backup_') } |
    Select-Object -First 1
  if (-not $changed) { exit 0 }

  # remember we reminded (once per session), then block this stop
  $st.reminded = $true
  $st | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8

  [Console]::Error.WriteLine('[project-memory] Project files changed this session, but the session journal (Claude\) has NO new entry. Session without a journal entry = not closed. Add a compact entry ON TOP of the journal (## date * device * topic; Done / Files / Next session) and update Claude\STATUS.md. If the user is still mid-work - continue the task and write the journal at the real end.')
  exit 2
} catch {}
exit 0
