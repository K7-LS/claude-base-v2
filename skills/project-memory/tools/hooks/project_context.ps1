# project_context.ps1 - project-memory UserPromptSubmit hook (skill project-memory)
# Extracts Windows paths from the user's prompt text (fallback: cwd), resolves the first
# one that is (inside) a memory project via find_project.ps1, and injects the project core
# (KONTEKST.md content + top of STATUS.md) into context EXACTLY ONCE per session+project
# (marker file). Fixes: sessions start with an unpredictable cwd, so the SessionStart
# cwd-only walk-up (session_start.ps1) can miss the project entirely when the user's
# message names a path instead of the session having started inside it. This hook
# re-checks on every prompt, using the message text as a second detection channel.
#
# Reuses find_project.ps1 (same folder) for the walk-up - NOT reimplemented here. Called
# as a SEPARATE PROCESS on purpose: find_project.ps1 ends with "exit 0", and calling it
# in-process (dot-source or call operator without a new process) would terminate THIS
# script's process too. See tests/test_hooks.py's own run_find_project() for the same
# pattern from the Python side.
#
# ASCII-only source on purpose (PowerShell 5.1 / no-BOM robustness). The Russian directive
# text lives in a UTF-8 sidecar file (project_context_directive.txt, same folder), read
# explicitly as UTF-8 - same pattern as routing-detector.ps1 + routing-reminder.txt.
#
# Contract: always exit 0 (a UserPromptSubmit hook must never break the session).

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch {}

$MaxCandidates    = 8
$MaxKontekstLines = 140
$MaxJournalLines  = 40
$MaxStatusLines   = 40
$MaxTotalLines    = 200

function Invoke-FindProject {
  param([string]$StartPath, [string]$ScriptPath)
  if ([string]::IsNullOrWhiteSpace($StartPath)) { return $null }
  try {
    $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath -StartPath $StartPath 2>$null
    if (-not $out) { return $null }
    $joined = ($out -join [System.Environment]::NewLine).Trim()
    if (-not $joined) { return $null }
    return $joined | ConvertFrom-Json
  } catch { return $null }
}

function Get-TopLines {
  param([string]$Path, [int]$Max)
  if (-not $Path) { return @() }
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
  try {
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
  } catch { return @() }
  if ($lines.Count -gt $Max) { return $lines[0..($Max - 1)] }
  return $lines
}

function Get-JournalTop {
  # Top N dated entries of the journal (same '^## YYYY-' anchor as session_start.ps1).
  # BLOCKER-1 fix (audit 2026-07-09): the path-channel must also deliver the journal, not
  # only KONTEKST+STATUS - session_start covers ONLY the cwd-channel.
  param([string]$Path, [int]$MaxEntries = 2, [int]$MaxLines = 40)
  if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
  try { $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8) } catch { return @() }
  $starts = @()
  for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^## \d{4}-') { $starts += $i } }
  if ($starts.Count -eq 0) { return @() }
  $end = $lines.Count - 1
  if ($starts.Count -gt $MaxEntries) { $end = $starts[$MaxEntries] - 1 }
  $cap = $starts[0] + $MaxLines - 1
  if ($end -gt $cap) { $end = $cap }
  return $lines[$starts[0]..$end]
}

try {
  $raw = [Console]::In.ReadToEnd()
  $inp = $null
  if ($raw) { try { $inp = $raw | ConvertFrom-Json } catch { $inp = $null } }
  if (-not $inp) { exit 0 }

  $prompt = ''
  if ($inp.prompt) { $prompt = [string]$inp.prompt }
  $cwd = ''
  if ($inp.cwd) { $cwd = [string]$inp.cwd }
  $sid = ''
  if ($inp.session_id) { $sid = [string]$inp.session_id }
  if (-not $sid) { exit 0 }   # can't dedupe injection without a session id - stay silent

  # --- 1) collect path candidates from the prompt text: quoted (both styles) then bare ---
  $sq = [char]39
  $dq = [char]34
  $patQuotedDouble = $dq + '([A-Za-z]:\\[^' + $dq + ']+)' + $dq
  $patQuotedSingle = $sq + '([A-Za-z]:\\[^' + $sq + ']+)' + $sq
  $patBare         = '([A-Za-z]:\\[^\s' + $dq + $sq + '<>|]+)'
  $pat = $patQuotedDouble + '|' + $patQuotedSingle + '|' + $patBare

  $candidates = New-Object System.Collections.Generic.List[string]
  if ($prompt) {
    foreach ($m in [regex]::Matches($prompt, $pat)) {
      $val = $null
      if ($m.Groups[1].Success) { $val = $m.Groups[1].Value }
      elseif ($m.Groups[2].Success) { $val = $m.Groups[2].Value }
      elseif ($m.Groups[3].Success) { $val = $m.Groups[3].Value }
      if ($val) { $candidates.Add($val) }
    }
  }
  # NB: cwd is deliberately NOT a spawn candidate. The cwd-project is resolved once by
  # session_start.ps1 (marker session_<sid>.json) - re-spawning find_project for cwd on
  # EVERY prompt cost ~600ms/prompt globally (audit 2026-07-09, BLOCKER-2). We read that
  # marker instead (no spawn); find_project is spawned ONLY for paths named in the prompt.
  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  $unique = New-Object System.Collections.Generic.List[string]
  foreach ($c in $candidates) {
    if ($c -and $seen.Add($c)) { $unique.Add($c) }
    if ($unique.Count -ge $MaxCandidates) { break }
  }

  $stateDir = $env:PROJECT_MEMORY_STATE_DIR
  if (-not $stateDir) { $stateDir = Join-Path $HOME '.claude\.local-state\project-memory' }

  # cwd-project from the session marker (written by session_start.ps1) - NO spawn
  $cwdRoot = $null; $cwdJournal = $null
  $sessMarker = Join-Path $stateDir ('session_' + $sid + '.json')
  if (Test-Path -LiteralPath $sessMarker) {
    try {
      $sm = (Get-Content -LiteralPath $sessMarker -Raw -Encoding UTF8) | ConvertFrom-Json
      if ($sm.project_root) { $cwdRoot = [string]$sm.project_root; $cwdJournal = [string]$sm.journal }
    } catch {}
  }

  # instant no-op (~5ms, no spawn): no path in the prompt AND cwd is not a known project
  if ($unique.Count -eq 0 -and -not $cwdRoot) { exit 0 }

  # --- 2) resolve project: prompt paths first (spawn only when a path is present),
  #        else the cwd-project from the session marker (no spawn) ---
  $KontekstName = (-join ([char]0x041A,[char]0x041E,[char]0x041D,[char]0x0422,[char]0x0415,[char]0x041A,[char]0x0421,[char]0x0422)) + '.md'
  $findProjectScript = Join-Path $PSScriptRoot 'find_project.ps1'
  $projectInfo = $null
  if ($unique.Count -gt 0 -and (Test-Path -LiteralPath $findProjectScript -PathType Leaf)) {
    foreach ($cand in $unique) {
      $info = Invoke-FindProject -StartPath $cand -ScriptPath $findProjectScript
      if ($info -and $info.root) { $projectInfo = $info; break }
    }
  }
  if (-not $projectInfo -and $cwdRoot) {
    $kpath = Join-Path (Join-Path $cwdRoot 'Claude') $KontekstName
    if (-not (Test-Path -LiteralPath $kpath -PathType Leaf)) { $kpath = '' }
    $projectInfo = [pscustomobject]@{ root = $cwdRoot; journal = $cwdJournal; kontekst = $kpath }
  }
  if (-not $projectInfo) { exit 0 }   # not a memory project - stay silent

  # --- 3) once-per-session+project marker ($stateDir already resolved above) ---
  New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

  $rootNorm = ([string]$projectInfo.root).TrimEnd('\', '/').ToLowerInvariant()
  $md5 = [System.Security.Cryptography.MD5]::Create()
  $hashBytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($rootNorm))
  $hashHex = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
  $hashShort = $hashHex.Substring(0, 10)

  $marker = Join-Path $stateDir ('ctx_' + $sid + '_' + $hashShort + '.json')
  if (Test-Path -LiteralPath $marker) { exit 0 }   # already injected this session+project

  # --- 4) build the injected block: directive + KONTEKST.md + top of STATUS.md ---
  $rootLeaf = Split-Path -Path $projectInfo.root -Leaf
  $directiveFile = Join-Path $PSScriptRoot 'project_context_directive.txt'
  $directive = '[project-memory] ' + $rootLeaf
  if (Test-Path -LiteralPath $directiveFile -PathType Leaf) {
    try {
      $tmpl = (Get-Content -LiteralPath $directiveFile -Encoding UTF8 -Raw).Trim()
      if ($tmpl) { $directive = $tmpl.Replace('[ROOT]', $rootLeaf) }
    } catch {}
  }

  $kontekstLines = Get-TopLines -Path ([string]$projectInfo.kontekst) -Max $MaxKontekstLines
  $journalLines = Get-JournalTop -Path ([string]$projectInfo.journal) -MaxEntries 2 -MaxLines $MaxJournalLines
  $statusPath = Join-Path $projectInfo.root 'Claude\STATUS.md'
  $statusLines = Get-TopLines -Path $statusPath -Max $MaxStatusLines

  $outLines = New-Object System.Collections.Generic.List[string]
  $outLines.Add($directive)
  if ($kontekstLines.Count -gt 0) {
    $outLines.Add('')
    $outLines.Add('--- KONTEKST.md ---')
    foreach ($l in $kontekstLines) { $outLines.Add($l) }
  }
  if ($journalLines.Count -gt 0) {
    $outLines.Add('')
    $outLines.Add('--- journal (top) ---')
    foreach ($l in $journalLines) { $outLines.Add($l) }
  }
  if ($statusLines.Count -gt 0) {
    $outLines.Add('')
    $outLines.Add('--- STATUS.md (top) ---')
    foreach ($l in $statusLines) { $outLines.Add($l) }
  }

  if ($outLines.Count -gt $MaxTotalLines) {
    $outLines = $outLines.GetRange(0, $MaxTotalLines)
    $outLines.Add('... (truncated)')
  }

  foreach ($l in $outLines) { Write-Output $l }

  # --- 5) mark as shown for this session+project (write AFTER successful output) ---
  $markerObj = [ordered]@{
    shown_epoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    root        = $projectInfo.root
  }
  $markerObj | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
} catch {}
exit 0
