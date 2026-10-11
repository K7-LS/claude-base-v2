# routing-detector.ps1 - UserPromptSubmit hook: enforces the routing-gate.
# Reads the hook JSON from stdin, matches the user prompt against the SAME domain
# trigger phrases as domain-grilling (single shared source, no duplicate list),
# and on a hit prints a reminder so Claude routes the task to a domain agent
# instead of doing it inline / via general-purpose.
# Fixes the measured failure: general-purpose call count > all domain agents,
# because the text-only routing-gate in CLAUDE.md was obeyed ~70% of the time.
#
# IMPORTANT: ASCII-only on purpose. PowerShell 5.1 mis-decodes an un-BOM-ed .ps1
# with Cyrillic. All Cyrillic lives in UTF-8 sidecar files:
#   triggers (shared with grilling): ~/.claude/skills/domain-grilling/triggers.txt
#   reminder:                        routing-reminder.txt next to this script
# Fail-open: any error => exit 0 with no output (never block the prompt).

$ErrorActionPreference = 'SilentlyContinue'
try {
    [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

    $data = $raw | ConvertFrom-Json
    $prompt = [string]$data.prompt
    if ([string]::IsNullOrWhiteSpace($prompt)) { exit 0 }
    $lc = $prompt.ToLowerInvariant()

    $trigFile = Join-Path $env:USERPROFILE '.claude\skills\domain-grilling\triggers.txt'
    $remFile  = Join-Path $PSScriptRoot 'routing-reminder.txt'
    if (-not (Test-Path -LiteralPath $trigFile)) { exit 0 }

    $hit = $false
    foreach ($line in (Get-Content -LiteralPath $trigFile -Encoding UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        if ($lc.Contains($t.ToLowerInvariant())) { $hit = $true; break }
    }
    if (-not $hit) { exit 0 }

    if (Test-Path -LiteralPath $remFile) {
        Write-Output (Get-Content -LiteralPath $remFile -Encoding UTF8 -Raw)
    }
    exit 0
} catch {
    exit 0
}
