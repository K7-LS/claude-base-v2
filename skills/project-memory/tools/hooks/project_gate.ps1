# project_gate.ps1 - PreToolUse hook (skill project-memory)
# Blocks mutating tool calls (Write/Edit/MultiEdit/NotebookEdit/Task) inside a
# memory project (root has Claude\<journal>, see find_project.ps1) until THIS
# session has read Claude\<kontekst> for that project. "Read" is a deterministic
# fact, not a promise: log-tool-usage.ps1 (PostToolUse) sees a Read of that file
# and writes a ctxread marker; this hook only checks for the marker's presence.
# No marker -> block with exit 2 + stderr telling Claude what to read first.
# Outside any memory project, or already read -> exit 0 (no-op, never interferes).
#
# Marker contract (MUST match log-tool-usage.ps1's registration block):
#   <stateDir>\ctxread_<session_id>_<hash(root)>.json
#   stateDir   = env:PROJECT_MEMORY_STATE_DIR, else $HOME\.claude\.local-state\project-memory
#   hash(root) = first 12 hex chars of SHA1(lowercased, trailing-slash-trimmed root),
#                root taken verbatim from find_project.ps1's canonical output so both
#                sides hash the exact same string regardless of which file inside the
#                project triggered the walk-up.
#
# Field-name note: the mutating set is Write/Edit/MultiEdit/NotebookEdit; the first
# three use tool_input.file_path, but NotebookEdit uses tool_input.notebook_path
# (verified against the live tool schema) - handled explicitly below.
#
# Fail-open on any internal error (this is a safety gate, not a feature - a bug
# here must never block unrelated work). ASCII-only source on purpose (PowerShell
# 5.1 / no-BOM robustness) - KONTEKST.md name and the block message are assembled
# from codepoints, same convention as find_project.ps1 / session_end.ps1.

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch {}

try {
  $raw = [Console]::In.ReadToEnd()
  if (-not $raw) { exit 0 }
  $raw = $raw.Trim([char]0xFEFF)
  $j = $raw | ConvertFrom-Json
  if (-not $j) { exit 0 }

  $toolName = [string]$j.tool_name
  $mutating = @('Write', 'Edit', 'MultiEdit', 'NotebookEdit')

  $path = $null
  if ($toolName -eq 'NotebookEdit') {
    if ($j.tool_input -and $j.tool_input.notebook_path) { $path = [string]$j.tool_input.notebook_path }
  } elseif ($mutating -contains $toolName) {
    if ($j.tool_input -and $j.tool_input.file_path) { $path = [string]$j.tool_input.file_path }
  } elseif ($toolName -eq 'Task') {
    if ($j.cwd) { $path = [string]$j.cwd }
  } else {
    exit 0   # Read/Bash/Grep/... - not a mutation we gate, no checks at all
  }
  if ([string]::IsNullOrWhiteSpace($path)) { exit 0 }

  $fpScript = Join-Path $PSScriptRoot 'find_project.ps1'
  if (-not (Test-Path -LiteralPath $fpScript)) { exit 0 }
  $projOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fpScript -StartPath $path 2>$null
  $projOut = (@($projOut) -join "`n").Trim()
  if (-not $projOut) { exit 0 }             # not a memory project - stay out of the way
  $proj = $projOut | ConvertFrom-Json
  if (-not $proj -or -not $proj.root) { exit 0 }

  $sessionId = [string]$j.session_id
  if ([string]::IsNullOrWhiteSpace($sessionId)) { exit 0 }   # nothing to key the marker on - fail open

  $normRoot = ([string]$proj.root).TrimEnd('\','/').ToLowerInvariant()
  $sha1 = [System.Security.Cryptography.SHA1]::Create()
  try {
    $hashBytes = $sha1.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($normRoot))
    $rootHash = (($hashBytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12)
  } finally { $sha1.Dispose() }

  $stateDir = $env:PROJECT_MEMORY_STATE_DIR
  if (-not $stateDir) { $stateDir = Join-Path $HOME '.claude\.local-state\project-memory' }
  $marker = Join-Path $stateDir ("ctxread_" + $sessionId + "_" + $rootHash + ".json")
  if (Test-Path -LiteralPath $marker) { exit 0 }   # context already read this session - allow

  $projName = Split-Path -Path ([string]$proj.root) -Leaf

  # Codepoint-assembled Cyrillic (ASCII source convention, see header).
  function CU([int[]]$Codes) { -join ($Codes | ForEach-Object { [char]$_ }) }
  $wSnachala  = CU @(0x0421,0x043D,0x0430,0x0447,0x0430,0x043B,0x0430)          # Snachala
  $wProchitai = CU @(0x043F,0x0440,0x043E,0x0447,0x0438,0x0442,0x0430,0x0439)   # prochitai
  $wKontekst  = CU @(0x041A,0x041E,0x041D,0x0422,0x0415,0x041A,0x0421,0x0422)   # KONTEKST
  $wProekta   = CU @(0x043F,0x0440,0x043E,0x0435,0x043A,0x0442,0x0430)         # proekta
  $wRol       = CU @(0x0440,0x043E,0x043B,0x044C)                              # rol
  $wKriterii  = CU @(0x043A,0x0440,0x0438,0x0442,0x0435,0x0440,0x0438,0x0438)   # kriterii
  $wGrabli    = CU @(0x0433,0x0440,0x0430,0x0431,0x043B,0x0438)                # grabli
  $wPotom     = CU @(0x043F,0x043E,0x0442,0x043E,0x043C)                       # potom
  $wPrav      = CU @(0x043F,0x0440,0x0430,0x0432,0x044C)                       # prav

  $msg = "[project-memory] $wSnachala $wProchitai Claude\$wKontekst.md $wProekta '$projName' ($wRol, $wKriterii, $wGrabli), $wPotom $wPrav."
  [Console]::Error.WriteLine($msg)
  exit 2
} catch { exit 0 }
exit 0
