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
    # Без установленного релизного слоя уведомление всё равно нужно —
    # иначе старые consumer-ПК никогда не узнают о существовании обновлений
    # (фикс блокера №3 ревизии, 2026-08-28).
    $Installed = Test-Path -LiteralPath $VersionPath -PathType Leaf

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
                -Uri 'https://api.github.com/repos/K7-LS/claude-base-v2/releases?per_page=20' `
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

    $CurrentText = if ($Installed) {
        (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8).Trim()
    } else { '0.0.0' }
    $LatestText = ([string]$Stable.tag_name) -replace '^claude-v', ''
    if ([version]$LatestText -le [version]$CurrentText) { return $null }
    if (-not $Installed) {
        return "Claude-base $LatestText is available; release layer is not installed on this PC. Run `$sync-base to verify and install it."
    }
    return "Claude-base $LatestText is available. Run `$sync-base to verify and install it."
}

# Сверка хуков и остатки прежней базы. Подпись состава замечаний
# сохраняется уже после вывода: оборванный хук не «съедает» уведомление.
function Get-HygieneOutcome {
    param([int]$WaitSeconds)

    $Outcome = [pscustomobject]@{ Messages = @(); Signature = $null; StatePath = $null }
    $RuntimeRoot = Split-Path -Parent $PSScriptRoot
    $Hygiene = Join-Path $RuntimeRoot 'hygiene.ps1'
    $BaseHome = Join-Path $env:USERPROFILE '.claude\base'
    # Сверка идёт только из установленного слоя: запуск хука из исходников
    # или с чужим профилем настройки не трогает.
    if (-not (Test-Path -LiteralPath $Hygiene -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $BaseHome 'VERSION') -PathType Leaf) -or
        -not [string]::Equals(
            [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\'),
            [IO.Path]::GetFullPath((Join-Path $BaseHome 'runtime')).TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        )) { return $Outcome }

    $Report = (
        @(& $Hygiene -Action All -SessionStart -WaitPreviousSyncSeconds $WaitSeconds 2>$null) -join "`n"
    ) | ConvertFrom-Json
    $Messages = @()
    if ($Report.hooks -and [string]$Report.hooks.status -ceq 'UPDATED') {
        $Text = 'Claude-base hooks in settings.json were aligned with the installed release'
        $Removed = @($Report.hooks.removed).Count
        if ($Removed -gt 0) {
            $Text += " ($Removed hook script(s) of the previous base unhooked)"
        }
        if ($Report.hooks.backup) {
            $Text += '; the previous file is kept in base\state\settings-backups'
        }
        $Messages += ($Text + '. They apply from the next session.')
    }

    $Findings = @()
    if ($Report.legacy) { $Findings = @($Report.legacy.findings) }
    $Signature = @(
        $Findings | ForEach-Object { [string]$_.id + ':' + [string]$_.path } | Sort-Object
    ) -join '|'
    $StatePath = Join-Path $BaseHome 'state\hygiene.json'
    $Previous = $null
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        try {
            $Previous = [string](
                Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            ).notified
        } catch {
            # Следующая запись заменит повреждённый файл состояния.
        }
    }
    # Об одном и том же составе замечаний сообщаем один раз.
    if ($Signature -cne $Previous) {
        $Outcome.Signature = $Signature
        $Outcome.StatePath = $StatePath
        $Own = @('settings_unreadable', 'hooks_not_canonical', 'scan_failed')
        $Blocked = @($Findings | Where-Object { [string]$_.id -in $Own })
        $Leftovers = @($Findings | Where-Object { [string]$_.id -notin $Own })
        if ($Blocked.Count -gt 0) {
            # Нечитаемый файл повторный запуск не исправит: его чинит человек.
            $Advice = 'Run $sync-base to retry.'
            if ([string]$Blocked[0].id -ceq 'settings_unreadable') {
                $Advice = 'Fix the file; hooks are aligned at the next session start.'
            }
            $Messages += (
                'Claude-base did not align hooks in settings.json: ' +
                [string]$Blocked[0].detail + '. ' + $Advice
            )
        }
        if ($Leftovers.Count -gt 0) {
            $Ids = @($Leftovers | ForEach-Object { [string]$_.id } | Sort-Object -Unique) -join ', '
            $Messages += "Leftovers of the previous base are still present ($Ids). Ask Claude to run base\runtime\hygiene.ps1 -Action Scan for the list."
        }
    }
    $Outcome.Messages = $Messages
    return $Outcome
}

$Clock = [Diagnostics.Stopwatch]::StartNew()
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

$Hygiene = $null
try {
    # Сверка идёт последней и ждёт синхронизацию прежней базы не дольше,
    # чем осталось от 40 секунд хука.
    $Wait = [Math]::Max(1, [Math]::Min(20, 32 - [int]$Clock.Elapsed.TotalSeconds))
    $Hygiene = Get-HygieneOutcome -WaitSeconds $Wait
    foreach ($HygieneMessage in @($Hygiene.Messages)) {
        [void]$Messages.Add([string]$HygieneMessage)
    }
} catch {
    # Сверка хуков не блокирует запуск сессии.
}

if ($Messages.Count -gt 0) {
    [ordered]@{ systemMessage = ($Messages -join ' ') } | ConvertTo-Json -Compress
}

try {
    if ($null -ne $Hygiene -and $null -ne $Hygiene.Signature) {
        [IO.Directory]::CreateDirectory((Split-Path -Parent $Hygiene.StatePath)) | Out-Null
        $StatePayload = [ordered]@{ notified = [string]$Hygiene.Signature } | ConvertTo-Json -Compress
        Write-Utf8NoBom $Hygiene.StatePath ($StatePayload + "`n")
    }
} catch {
    # Без записи состояния уведомление повторится на следующем старте.
}
exit 0