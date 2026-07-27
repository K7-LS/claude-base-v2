# find_project.ps1 - project-memory reusable walk-up finder (skill project-memory)
# Reusable building block: given -StartPath (a file OR a directory, existing
# or not yet on disk), walks up to 12 levels looking for <root>\Claude\<journal>.
# Future hooks (path-detector, gates) should CALL this script instead of
# re-implementing the walk-up. Mirrors the walk-up in session_start.ps1
# (that hook keeps its own copy for now - refactoring it to call this script
# is a separate task, not done here).
#
# Output contract:
#   found     -> ONE compact JSON line on stdout:
#                {"root":"<...>","journal":"<...>","kontekst":"<...|"">"}
#   not found -> nothing on stdout
#   always    -> exit 0 (never breaks the caller)
#
# ASCII-only source on purpose (PowerShell 5.1 / no-BOM robustness).
# Journal/kontekst file names are Russian, assembled from codepoints.

param(
  # Not marked -Mandatory on purpose: a mandatory param left unsupplied makes
  # PowerShell prompt on the console, which can hang a non-interactive caller.
  # Missing/blank input is instead treated as "nothing to do" below (exit 0).
  [string]$StartPath = ''
)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [Text.Encoding]::UTF8 } catch {}

$JournalName = (-join ([char]0x0416,[char]0x0423,[char]0x0420,[char]0x041D,[char]0x0410,[char]0x041B)) + ' ' + `
               (-join ([char]0x0421,[char]0x0415,[char]0x0421,[char]0x0421,[char]0x0418,[char]0x0419)) + '.md'
$KontekstName = (-join ([char]0x041A,[char]0x041E,[char]0x041D,[char]0x0422,[char]0x0415,[char]0x041A,[char]0x0421,[char]0x0422)) + '.md'

try {
  if ([string]::IsNullOrWhiteSpace($StartPath)) { exit 0 }

  # Resolve the starting directory: file -> its parent, directory -> itself.
  # StartPath may not exist yet (e.g. a file a hook is about to write), so
  # existence checks are attempted first and a filename heuristic (dot in
  # the last path segment) is the fallback for paths that aren't on disk.
  $startDir = $null
  if (Test-Path -LiteralPath $StartPath -PathType Leaf) {
    $startDir = Split-Path -Path $StartPath -Parent
  } elseif (Test-Path -LiteralPath $StartPath -PathType Container) {
    $startDir = $StartPath
  } else {
    $leaf = Split-Path -Path $StartPath -Leaf
    if ($leaf -match '\.') {
      $startDir = Split-Path -Path $StartPath -Parent
    } else {
      $startDir = $StartPath
    }
  }
  if ([string]::IsNullOrWhiteSpace($startDir)) { exit 0 }

  # Walk up from startDir looking for <d>\Claude\<journal>. String-based
  # (Split-Path), not Get-Item/.Parent: intermediate levels (e.g. "sub\deep"
  # above) may not exist on disk yet, only the final match needs to.
  $root = $null; $journal = $null
  $d = $startDir
  for ($i = 0; ($i -lt 12) -and $d; $i++) {
    $cand = Join-Path (Join-Path $d 'Claude') $JournalName
    if (Test-Path -LiteralPath $cand -PathType Leaf) { $root = $d; $journal = $cand; break }
    $leaf = Split-Path -Path $d -Leaf
    if ($leaf -eq 'Claude') {
      $cand2 = Join-Path $d $JournalName
      if (Test-Path -LiteralPath $cand2 -PathType Leaf) {
        $root = Split-Path -Path $d -Parent
        $journal = $cand2
        break
      }
    }
    $parent = Split-Path -Path $d -Parent
    if ([string]::IsNullOrEmpty($parent) -or $parent -eq $d) { break }
    $d = $parent
  }
  if (-not $journal) { exit 0 }   # not a memory project - stay silent

  # Normalize to canonical absolute paths. Safe to Get-Item here: root/journal
  # are guaranteed to exist on disk now (journal was just found via Test-Path,
  # and a file can't exist without its containing directories existing too).
  $root = (Get-Item -LiteralPath $root).FullName
  $journal = (Get-Item -LiteralPath $journal).FullName

  $claudeDir = Split-Path -Path $journal -Parent
  $kontekstPath = Join-Path $claudeDir $KontekstName
  $kontekstOut = ''
  if (Test-Path -LiteralPath $kontekstPath -PathType Leaf) {
    $kontekstOut = (Get-Item -LiteralPath $kontekstPath).FullName
  }

  $out = [ordered]@{
    root     = $root
    journal  = $journal
    kontekst = $kontekstOut
  }
  $out | ConvertTo-Json -Compress
} catch {}
exit 0
