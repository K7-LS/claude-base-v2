# grilling-detector.ps1 - UserPromptSubmit hook for the domain-grilling skill.
# Reads the hook JSON from stdin, matches the user prompt against строй-trigger
# phrases, and (on a hit) prints a reminder to stdout so Claude Code injects it
# into context before the turn.
#
# IMPORTANT: this file is ASCII-only on purpose. Cyrillic triggers and the
# reminder text live in UTF-8 sidecar files next to the skill, so PowerShell 5.1
# (which would mis-decode Cyrillic in an un-BOM-ed .ps1) never has to parse them.
#   triggers: ~/.claude/skills/domain-grilling/triggers.txt
#   reminder: ~/.claude/skills/domain-grilling/reminder.txt
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

    $base     = Join-Path $env:USERPROFILE '.claude\skills\domain-grilling'
    $trigFile = Join-Path $base 'triggers.txt'
    $remFile  = Join-Path $base 'reminder.txt'
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
