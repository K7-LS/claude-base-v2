# regen-tom-widgets.ps1 - SessionStart hook: auto-regenerate tom widgets.
# DESIGN (blocks/pto, s.12): "widget must be alive - SessionStart hook regenerates
# widgets of all toms". Mechanics: walk up from cwd (max 12 levels) to an object
# root (marker: Claude\<session journal>), then scan limited depth for
# */journal.json with build_status.py next to it and run the generator.
# Outside memory-objects: silent no-op. NEVER breaks session start (exit 0 always).
# ASCII-only source on purpose (PowerShell 5.1 / no-BOM robustness); the Russian
# journal file name is assembled from codepoints.

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

  # walk up from cwd looking for <root>\Claude\<journal> (or cwd itself being Claude\)
  $root = $null
  $d = $null
  if (Test-Path -LiteralPath $cwd) { $d = Get-Item -LiteralPath $cwd }
  for ($i = 0; ($i -lt 12) -and $d; $i++) {
    $cand = Join-Path (Join-Path $d.FullName 'Claude') $JournalName
    if (Test-Path -LiteralPath $cand) { $root = $d.FullName; break }
    if ($d.Name -eq 'Claude') {
      $cand2 = Join-Path $d.FullName $JournalName
      if (Test-Path -LiteralPath $cand2) { $root = $d.Parent.FullName; break }
    }
    $d = $d.Parent
  }
  if (-not $root) { exit 0 }   # not a memory-object - stay silent

  $jsons = Get-ChildItem -LiteralPath $root -Recurse -Depth 5 -Filter 'journal.json' -File -EA SilentlyContinue
  $done = 0
  foreach ($j in $jsons) {
    $dir = $j.DirectoryName
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'build_status.py'))) { continue }
    Push-Location -LiteralPath $dir
    & python build_status.py *> $null
    if ($LASTEXITCODE -eq 0) { $done++ }
    Pop-Location
  }
  if ($done -gt 0) {
    Write-Output ("[tom-widgets] regenerated " + $done + " widget(s) under '" + (Split-Path $root -Leaf) + "'.")
  }
} catch {}
exit 0
