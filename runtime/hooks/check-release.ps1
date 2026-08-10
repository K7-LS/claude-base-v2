$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $Encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Text, $Encoding)
}

function Get-DailyReleaseMessage {
    $ConnectionRuntime = Join-Path (Split-Path -Parent $PSScriptRoot) 'connection.ps1'
    if (-not (Test-Path -LiteralPath $ConnectionRuntime -PathType Leaf)) { return $null }
    . $ConnectionRuntime
    $BaseHome = Join-Path $env:USERPROFILE '.claude\base'
    $VersionPath = Join-Path $BaseHome 'VERSION'
    if (-not (Test-Path -LiteralPath $VersionPath -PathType Leaf)) { return $null }

    $StateRoot = Join-Path $BaseHome 'state'
    $StatePath = Join-Path $StateRoot 'update-check.json'
    $Now = [DateTimeOffset]::UtcNow
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        try {
            $State = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $Checked = [DateTimeOffset]::Parse([string]$State.checked_at)
            if (($Now - $Checked).TotalHours -lt 24) { return $null }
        } catch {
            # Следующая успешная проверка заменит повреждённый TTL-файл.
        }
    }

    $Releases = Invoke-WithLlmConnection `
        -HomePath $env:USERPROFILE `
        -ScriptBlock {
            Invoke-LlmJsonGet `
                -Uri 'https://api.github.com/repos/daniileliseev1337/claude-base-v2/releases?per_page=20' `
                -UserAgent 'claude-base-v2-version-check/1' `
                -TimeoutSeconds 5
        }
    $Stable = @($Releases) |
        Where-Object {
            (-not $_.draft) -and
            (-not $_.prerelease) -and
            ([string]$_.tag_name -match '^claude-v\d+\.\d+\.\d+$')
        } |
        Sort-Object -Property published_at -Descending |
        Select-Object -First 1

    [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
    $StatePayload = [ordered]@{
        checked_at = $Now.ToString('o')
        latest_tag = if ($Stable) { [string]$Stable.tag_name } else { $null }
    } | ConvertTo-Json -Compress
    Write-Utf8NoBom $StatePath ($StatePayload + "`n")
    if (-not $Stable) { return $null }

    $CurrentText = (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8).Trim()
    $LatestText = ([string]$Stable.tag_name) -replace '^claude-v', ''
    if ([version]$LatestText -le [version]$CurrentText) { return $null }
    return "Claude-base $LatestText is available. Run `$sync-base to verify and install it."
}

$Messages = New-Object 'Collections.Generic.List[string]'
try {
    $Updater = Join-Path (Split-Path -Parent $PSScriptRoot) 'update-session-tools.ps1'
    if (Test-Path -LiteralPath $Updater -PathType Leaf) {
        $UpdaterOutput = @(& $Updater -HookFallback 2>$null)
        if ($UpdaterOutput -ccontains 'TOOLS_APPLIED_NEXT_SESSION') {
            [void]$Messages.Add('Session tools were updated and will be available in the next session.')
        }
    }
} catch {
    # Сессионное обновление не блокирует прямой запуск Claude.
}

try {
    $ReleaseMessage = Get-DailyReleaseMessage
    if ($ReleaseMessage) { [void]$Messages.Add($ReleaseMessage) }
} catch {
    # Проверка уведомления не блокирует запуск сессии.
}

if ($Messages.Count -gt 0) {
    [ordered]@{ systemMessage = ($Messages -join ' ') } | ConvertTo-Json -Compress
}
exit 0
