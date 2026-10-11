[CmdletBinding()]
param(
    [ValidateSet('All', 'Reconcile', 'Scan')][string]$Action = 'All',
    [string]$HomePath = $env:USERPROFILE,
    [string]$RuntimeRoot = '',
    [switch]$Check
)

# Гигиена установленной базы:
#   Reconcile — приводит хуки в ~/.claude/settings.json к набору релиза;
#   Scan      — только читает и перечисляет остатки прежней базы.
# Меняется одно значение ключа "hooks": остальной текст settings.json
# остаётся побайтно прежним, перед записью снимается копия. Чужие хуки
# (не из базы) сохраняются. Скрипт не блокирует сессию: код возврата 0.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = $PSScriptRoot }

$script:JsonTokenPattern = New-Object Text.RegularExpressions.Regex(
    '"(?:[^"\\]|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,"]+',
    [Text.RegularExpressions.RegexOptions]::Singleline
)
$script:JsonLiteralPattern = '^(?:true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$'

function New-JsonReader {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

    $Tokens = $script:JsonTokenPattern.Matches($Text)
    $Position = 0
    foreach ($Token in $Tokens) {
        if ($Token.Index -gt $Position -and
            $Text.Substring($Position, $Token.Index - $Position).Trim().Length -ne 0) {
            throw 'JSON contains unexpected characters.'
        }
        $Position = $Token.Index + $Token.Length
    }
    if ($Position -lt $Text.Length -and $Text.Substring($Position).Trim().Length -ne 0) {
        throw 'JSON contains unexpected characters.'
    }
    return [pscustomobject]@{ Text = $Text; Tokens = $Tokens; Index = 0 }
}

function Read-JsonToken {
    param([Parameter(Mandatory = $true)]$Reader)

    if ($Reader.Index -ge $Reader.Tokens.Count) { throw 'JSON ended unexpectedly.' }
    $Token = $Reader.Tokens[$Reader.Index]
    $Reader.Index = $Reader.Index + 1
    return $Token
}

function ConvertFrom-JsonStringToken {
    param([Parameter(Mandatory = $true)][string]$Token)

    $Body = $Token.Substring(1, $Token.Length - 2)
    if ($Body.IndexOf('\') -lt 0) { return $Body }
    $Builder = New-Object Text.StringBuilder
    $Index = 0
    while ($Index -lt $Body.Length) {
        $Char = [string]$Body[$Index]
        if ($Char -cne '\') {
            [void]$Builder.Append($Char)
            $Index++
            continue
        }
        $Index++
        if ($Index -ge $Body.Length) { throw 'JSON string escape is incomplete.' }
        $Escape = [string]$Body[$Index]
        if ($Escape -ceq '"' -or $Escape -ceq '\' -or $Escape -ceq '/') {
            [void]$Builder.Append($Escape)
        }
        elseif ($Escape -ceq 'b') { [void]$Builder.Append([char]8) }
        elseif ($Escape -ceq 'f') { [void]$Builder.Append([char]12) }
        elseif ($Escape -ceq 'n') { [void]$Builder.Append([char]10) }
        elseif ($Escape -ceq 'r') { [void]$Builder.Append([char]13) }
        elseif ($Escape -ceq 't') { [void]$Builder.Append([char]9) }
        elseif ($Escape -ceq 'u') {
            if ($Index + 4 -gt $Body.Length - 1) { throw 'JSON unicode escape is incomplete.' }
            $Hex = $Body.Substring($Index + 1, 4)
            if ($Hex -notmatch '^[0-9A-Fa-f]{4}$') { throw 'JSON unicode escape is invalid.' }
            [void]$Builder.Append([char][Convert]::ToInt32($Hex, 16))
            $Index += 4
        }
        else { throw 'JSON string escape is invalid.' }
        $Index++
    }
    return $Builder.ToString()
}

function ConvertTo-JsonStringToken {
    param([AllowEmptyString()][string]$Value)

    $Builder = New-Object Text.StringBuilder
    [void]$Builder.Append('"')
    foreach ($Char in $Value.ToCharArray()) {
        $Code = [int]$Char
        if ($Code -eq 34) { [void]$Builder.Append('\"') }
        elseif ($Code -eq 92) { [void]$Builder.Append('\\') }
        elseif ($Code -eq 10) { [void]$Builder.Append('\n') }
        elseif ($Code -eq 13) { [void]$Builder.Append('\r') }
        elseif ($Code -eq 9) { [void]$Builder.Append('\t') }
        elseif ($Code -eq 8) { [void]$Builder.Append('\b') }
        elseif ($Code -eq 12) { [void]$Builder.Append('\f') }
        elseif ($Code -lt 32) { [void]$Builder.Append('\u' + $Code.ToString('x4')) }
        else { [void]$Builder.Append($Char) }
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

# Значения: объект — OrderedDictionary, массив — ArrayList, строка — string,
# число и true/false/null — Tuple[string] с исходным текстом токена.
function Read-JsonValue {
    param([Parameter(Mandatory = $true)]$Reader)

    $Token = Read-JsonToken $Reader
    $Value = [string]$Token.Value
    if ($Value -ceq '{') {
        $Object = New-Object Collections.Specialized.OrderedDictionary
        if ([string]$Reader.Tokens[$Reader.Index].Value -ceq '}') {
            $Reader.Index = $Reader.Index + 1
            return $Object
        }
        while ($true) {
            $KeyToken = [string](Read-JsonToken $Reader).Value
            if (-not $KeyToken.StartsWith('"')) { throw 'JSON object key is not a string.' }
            $Key = ConvertFrom-JsonStringToken $KeyToken
            if ([string](Read-JsonToken $Reader).Value -cne ':') { throw 'JSON object lacks a colon.' }
            $Item = Read-JsonValue $Reader
            if ($Object.Contains($Key)) { throw 'JSON object repeats a key.' }
            $Object.Add($Key, $Item)
            $Next = [string](Read-JsonToken $Reader).Value
            if ($Next -ceq '}') { break }
            if ($Next -cne ',') { throw 'JSON object lacks a comma.' }
        }
        return $Object
    }
    if ($Value -ceq '[') {
        $List = New-Object Collections.ArrayList
        if ([string]$Reader.Tokens[$Reader.Index].Value -ceq ']') {
            $Reader.Index = $Reader.Index + 1
            return , $List
        }
        while ($true) {
            $Item = Read-JsonValue $Reader
            [void]$List.Add($Item)
            $Next = [string](Read-JsonToken $Reader).Value
            if ($Next -ceq ']') { break }
            if ($Next -cne ',') { throw 'JSON array lacks a comma.' }
        }
        return , $List
    }
    if ($Value.StartsWith('"')) { return (ConvertFrom-JsonStringToken $Value) }
    if ($Value -cnotmatch $script:JsonLiteralPattern) { throw 'JSON literal is invalid.' }
    return (New-Object 'Tuple[string]' $Value)
}

function ConvertTo-JsonText {
    param(
        [AllowNull()]$Value,
        [int]$Level = 0,
        [string]$Unit = '  ',
        [string]$NewLine = "`n",
        [switch]$Compact
    )

    if ($Value -is [string]) { return (ConvertTo-JsonStringToken $Value) }
    if ($Value -is [Tuple[string]]) { return [string]$Value.Item1 }
    $Inner = ''
    $Outer = ''
    $Break = ''
    $Colon = ':'
    if (-not $Compact) {
        $Inner = $Unit * ($Level + 1)
        $Outer = $Unit * $Level
        $Break = $NewLine
        $Colon = ': '
    }
    if ($Value -is [Collections.Specialized.OrderedDictionary]) {
        if ($Value.Count -eq 0) { return '{}' }
        $Parts = New-Object 'Collections.Generic.List[string]'
        foreach ($Key in @($Value.Keys)) {
            $Parts.Add(
                $Inner + (ConvertTo-JsonStringToken ([string]$Key)) + $Colon +
                (ConvertTo-JsonText $Value[[string]$Key] ($Level + 1) $Unit $NewLine -Compact:$Compact)
            )
        }
        return '{' + $Break + ($Parts -join (',' + $Break)) + $Break + $Outer + '}'
    }
    if ($Value -is [Collections.ArrayList]) {
        if ($Value.Count -eq 0) { return '[]' }
        $Parts = New-Object 'Collections.Generic.List[string]'
        foreach ($Item in $Value) {
            $Parts.Add(
                $Inner + (ConvertTo-JsonText $Item ($Level + 1) $Unit $NewLine -Compact:$Compact)
            )
        }
        return '[' + $Break + ($Parts -join (',' + $Break)) + $Break + $Outer + ']'
    }
    throw 'JSON value type is not supported.'
}

function Read-JsonDocument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

    $Reader = New-JsonReader $Text
    if ($Reader.Tokens.Count -eq 0) { throw 'JSON document is empty.' }
    $Open = Read-JsonToken $Reader
    if ([string]$Open.Value -cne '{') { throw 'JSON document is not an object.' }
    $Members = New-Object Collections.ArrayList
    $Close = $null
    if ([string]$Reader.Tokens[$Reader.Index].Value -ceq '}') {
        $Close = Read-JsonToken $Reader
    }
    else {
        while ($true) {
            $KeyToken = Read-JsonToken $Reader
            if (-not ([string]$KeyToken.Value).StartsWith('"')) { throw 'JSON object key is not a string.' }
            if ([string](Read-JsonToken $Reader).Value -cne ':') { throw 'JSON object lacks a colon.' }
            $First = $Reader.Tokens[$Reader.Index]
            $Item = Read-JsonValue $Reader
            $Last = $Reader.Tokens[$Reader.Index - 1]
            [void]$Members.Add([pscustomobject]@{
                Key = ConvertFrom-JsonStringToken ([string]$KeyToken.Value)
                KeyIndex = [int]$KeyToken.Index
                ValueStart = [int]$First.Index
                ValueEnd = [int]($Last.Index + $Last.Length)
                Value = $Item
            })
            $Next = Read-JsonToken $Reader
            if ([string]$Next.Value -ceq '}') { $Close = $Next; break }
            if ([string]$Next.Value -cne ',') { throw 'JSON object lacks a comma.' }
        }
    }
    if ($Reader.Index -ne $Reader.Tokens.Count) { throw 'JSON document has trailing content.' }
    $Seen = New-Object Collections.Hashtable ([StringComparer]::Ordinal)
    foreach ($Member in $Members) {
        if ($Seen.ContainsKey([string]$Member.Key)) { throw 'JSON document repeats a key.' }
        $Seen[[string]$Member.Key] = $true
    }
    return [pscustomobject]@{
        Members = $Members
        OpenIndex = [int]$Open.Index
        CloseIndex = [int]$Close.Index
    }
}

function Get-LineIndent {
    param([string]$Text, [int]$Index)

    if ($Index -le 0) { return $null }
    $Start = $Text.LastIndexOf([char]10, $Index - 1)
    $Prefix = $Text.Substring($Start + 1, $Index - $Start - 1)
    if ($Start -lt 0 -or $Prefix.Trim().Length -ne 0) { return $null }
    return $Prefix
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    return (Read-JsonDocument $Text)
}

function Get-MemberValue {
    param($Document, [string]$Key)

    foreach ($Member in $Document.Members) {
        if ([string]$Member.Key -ceq $Key) { return , $Member.Value }
    }
    return $null
}

function Get-HookPolicy {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)

    $Document = Read-JsonFile (Join-Path $RuntimeRoot 'hooks-policy.json')
    $Names = New-Object 'Collections.Generic.List[string]'
    foreach ($Field in @('superseded', 'retired')) {
        $Items = Get-MemberValue $Document $Field
        if ($Items -isnot [Collections.ArrayList]) { throw 'Hook policy is invalid.' }
        foreach ($Item in $Items) { $Names.Add(([string]$Item).ToLowerInvariant()) }
    }
    $Roots = New-Object 'Collections.Generic.List[string]'
    $Items = Get-MemberValue $Document 'legacy_roots'
    if ($Items -isnot [Collections.ArrayList]) { throw 'Hook policy is invalid.' }
    foreach ($Item in $Items) { $Roots.Add(([string]$Item).ToLowerInvariant().TrimEnd('/')) }
    return [pscustomobject]@{ Names = $Names; Roots = $Roots }
}

function Get-TemplateHooks {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)

    $Path = Join-Path $RuntimeRoot 'settings.template.json'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $Path = Join-Path $RuntimeRoot 'settings.json'
    }
    $Hooks = Get-MemberValue (Read-JsonFile $Path) 'hooks'
    if ($Hooks -isnot [Collections.Specialized.OrderedDictionary] -or $Hooks.Count -eq 0) {
        throw 'Settings template has no hooks.'
    }
    foreach ($EventName in @($Hooks.Keys)) {
        if ($Hooks[[string]$EventName] -isnot [Collections.ArrayList]) {
            throw 'Settings template hooks are invalid.'
        }
    }
    return $Hooks
}

# Пути скриптов внутри ~/.claude, на которые ссылается команда хука:
# относительные, в нижнем регистре, с прямыми слэшами.
function Get-ClaudeScriptReferences {
    param([AllowEmptyString()][string]$Command)

    $Result = New-Object 'Collections.Generic.List[string]'
    $Pattern = '(?i)[\\/]\.claude[\\/]+([^"''\s<>|]+?\.(?:ps1|py))(?![A-Za-z0-9_])'
    foreach ($Match in [regex]::Matches($Command, $Pattern)) {
        $Result.Add(([regex]::Replace($Match.Groups[1].Value, '[\\/]+', '/')).ToLowerInvariant())
    }
    return , $Result
}

function Test-ManagedHookCommand {
    param([AllowEmptyString()][string]$Command, [Parameter(Mandatory = $true)]$Policy)

    foreach ($Reference in (Get-ClaudeScriptReferences $Command)) {
        if ($Reference.StartsWith('base/runtime/hooks/')) { return $true }
        $Leaf = $Reference.Substring($Reference.LastIndexOf('/') + 1)
        if (-not $Policy.Names.Contains($Leaf)) { continue }
        foreach ($Root in $Policy.Roots) {
            if ($Reference.StartsWith($Root + '/')) { return $true }
        }
    }
    return $false
}

function Get-HookCommands {
    param([AllowNull()]$Hooks)

    $Result = New-Object 'Collections.Generic.List[string]'
    if ($Hooks -isnot [Collections.Specialized.OrderedDictionary]) { return , $Result }
    foreach ($EventName in @($Hooks.Keys)) {
        $Groups = $Hooks[[string]$EventName]
        if ($Groups -isnot [Collections.ArrayList]) { continue }
        foreach ($Group in $Groups) {
            if ($Group -isnot [Collections.Specialized.OrderedDictionary] -or
                -not $Group.Contains('hooks') -or
                $Group['hooks'] -isnot [Collections.ArrayList]) { continue }
            foreach ($Hook in $Group['hooks']) {
                if ($Hook -is [Collections.Specialized.OrderedDictionary] -and
                    $Hook.Contains('command') -and $Hook['command'] -is [string]) {
                    $Result.Add([string]$Hook['command'])
                }
            }
        }
    }
    return , $Result
}

function Get-ReconciledHooks {
    param([AllowNull()]$Current, [Parameter(Mandatory = $true)]$Template, [Parameter(Mandatory = $true)]$Policy)

    $Removed = New-Object 'Collections.Generic.List[string]'
    $Foreign = 0
    $Result = New-Object Collections.Specialized.OrderedDictionary
    if ($Current -is [Collections.Specialized.OrderedDictionary]) {
        foreach ($EventName in @($Current.Keys)) {
            $Groups = $Current[[string]$EventName]
            if ($Groups -isnot [Collections.ArrayList]) {
                $Result.Add([string]$EventName, $Groups)
                continue
            }
            $KeptGroups = New-Object Collections.ArrayList
            foreach ($Group in $Groups) {
                if ($Group -isnot [Collections.Specialized.OrderedDictionary] -or
                    -not $Group.Contains('hooks') -or
                    $Group['hooks'] -isnot [Collections.ArrayList]) {
                    [void]$KeptGroups.Add($Group)
                    continue
                }
                $KeptHooks = New-Object Collections.ArrayList
                foreach ($Hook in $Group['hooks']) {
                    $Managed = $false
                    if ($Hook -is [Collections.Specialized.OrderedDictionary] -and
                        $Hook.Contains('command') -and $Hook['command'] -is [string]) {
                        $Managed = Test-ManagedHookCommand ([string]$Hook['command']) $Policy
                    }
                    if ($Managed) {
                        foreach ($Reference in (Get-ClaudeScriptReferences ([string]$Hook['command']))) {
                            if (-not $Removed.Contains($Reference)) { $Removed.Add($Reference) }
                        }
                    }
                    else {
                        [void]$KeptHooks.Add($Hook)
                        $Foreign++
                    }
                }
                if ($KeptHooks.Count -eq 0) { continue }
                $Copy = New-Object Collections.Specialized.OrderedDictionary
                foreach ($Key in @($Group.Keys)) {
                    if ([string]$Key -ceq 'hooks') { $Copy.Add('hooks', $KeptHooks) }
                    else { $Copy.Add([string]$Key, $Group[[string]$Key]) }
                }
                [void]$KeptGroups.Add($Copy)
            }
            if ($KeptGroups.Count -gt 0) { $Result.Add([string]$EventName, $KeptGroups) }
        }
    }
    foreach ($EventName in @($Template.Keys)) {
        $Merged = New-Object Collections.ArrayList
        foreach ($Group in $Template[[string]$EventName]) { [void]$Merged.Add($Group) }
        if ($Result.Contains([string]$EventName)) {
            foreach ($Group in $Result[[string]$EventName]) { [void]$Merged.Add($Group) }
            $Result[[string]$EventName] = $Merged
        }
        else { $Result.Add([string]$EventName, $Merged) }
    }
    return [pscustomobject]@{ Hooks = $Result; Removed = $Removed; Foreign = $Foreign }
}

function Read-SettingsFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [pscustomobject]@{ Exists = $false; Bytes = $null; Bom = $false; Text = '' }
    }
    $Bytes = [IO.File]::ReadAllBytes($Path)
    $Bom = ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF)
    $Text = if ($Bom) {
        [Text.Encoding]::UTF8.GetString($Bytes, 3, $Bytes.Length - 3)
    } else {
        [Text.Encoding]::UTF8.GetString($Bytes)
    }
    return [pscustomobject]@{ Exists = $true; Bytes = $Bytes; Bom = $Bom; Text = $Text }
}

function Test-SameBytes {
    param([AllowNull()][byte[]]$Left, [AllowNull()][byte[]]$Right)

    if ($null -eq $Left -or $null -eq $Right) { return ($null -eq $Left -and $null -eq $Right) }
    if ($Left.Length -ne $Right.Length) { return $false }
    return ([Convert]::ToBase64String($Left) -ceq [Convert]::ToBase64String($Right))
}

function Save-SettingsBackup {
    param([Parameter(Mandatory = $true)][string]$HomePath, [Parameter(Mandatory = $true)][byte[]]$Bytes)

    $Root = Join-Path $HomePath '.claude\base\state\settings-backups'
    [IO.Directory]::CreateDirectory($Root) | Out-Null
    $Name = 'settings-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.json'
    [IO.File]::WriteAllBytes((Join-Path $Root $Name), $Bytes)
    $Old = @(Get-ChildItem -LiteralPath $Root -Filter 'settings-*.json' -File |
        Sort-Object -Property Name -Descending | Select-Object -Skip 10)
    foreach ($Item in $Old) { Remove-Item -LiteralPath $Item.FullName -Force }
    return ('.claude/base/state/settings-backups/' + $Name)
}

function Invoke-HooksReconcile {
    param([string]$HomePath, [string]$RuntimeRoot, [switch]$Check)

    $Template = Get-TemplateHooks $RuntimeRoot
    $Policy = Get-HookPolicy $RuntimeRoot
    $Path = Join-Path $HomePath '.claude\settings.json'
    $File = Read-SettingsFile $Path
    $Text = [string]$File.Text
    $Blank = ($Text.Trim().Length -eq 0)
    $Document = $null
    $Member = $null
    if (-not $Blank) {
        try { $Document = Read-JsonDocument $Text }
        catch {
            return [pscustomobject][ordered]@{
                status = 'BLOCKED'; reason = 'settings.json is not valid JSON'
                removed = @(); foreign = 0; backup = $null
            }
        }
        foreach ($Candidate in $Document.Members) {
            if ([string]$Candidate.Key -ceq 'hooks') { $Member = $Candidate }
        }
    }
    $Current = $null
    if ($null -ne $Member) { $Current = $Member.Value }
    if ($null -ne $Member -and $Current -isnot [Collections.Specialized.OrderedDictionary]) {
        return [pscustomobject][ordered]@{
            status = 'BLOCKED'; reason = 'settings.json hooks value is not an object'
            removed = @(); foreign = 0; backup = $null
        }
    }
    $Plan = Get-ReconciledHooks $Current $Template $Policy
    $Removed = @($Plan.Removed | Sort-Object)
    if ($null -ne $Current -and
        (ConvertTo-JsonText $Current -Compact) -ceq (ConvertTo-JsonText $Plan.Hooks -Compact)) {
        return [pscustomobject][ordered]@{
            status = 'CANONICAL'; reason = $null
            removed = @(); foreign = [int]$Plan.Foreign; backup = $null
        }
    }
    if ($Check) {
        return [pscustomobject][ordered]@{
            status = 'WOULD_UPDATE'; reason = $null
            removed = $Removed; foreign = [int]$Plan.Foreign; backup = $null
        }
    }

    $NewLine = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    if ($Blank) {
        $NewText = '{' + $NewLine + '  "hooks": ' +
            (ConvertTo-JsonText $Plan.Hooks 1 '  ' $NewLine) + $NewLine + '}' + $NewLine
    }
    elseif ($null -ne $Member) {
        $Indent = Get-LineIndent $Text ([int]$Member.KeyIndex)
        $Level = 1
        $Unit = $Indent
        if ([string]::IsNullOrEmpty($Indent)) { $Level = 0; $Unit = '  ' }
        $NewText = $Text.Substring(0, [int]$Member.ValueStart) +
            (ConvertTo-JsonText $Plan.Hooks $Level $Unit $NewLine) +
            $Text.Substring([int]$Member.ValueEnd)
    }
    elseif ($Document.Members.Count -eq 0) {
        $NewText = $Text.Substring(0, [int]$Document.OpenIndex + 1) + $NewLine + '  "hooks": ' +
            (ConvertTo-JsonText $Plan.Hooks 1 '  ' $NewLine) + $NewLine +
            $Text.Substring([int]$Document.CloseIndex)
    }
    else {
        $Last = $Document.Members[$Document.Members.Count - 1]
        $Indent = Get-LineIndent $Text ([int]$Last.KeyIndex)
        $Level = 1
        $Unit = $Indent
        $Lead = $NewLine + $Indent
        if ([string]::IsNullOrEmpty($Indent)) { $Level = 0; $Unit = '  '; $Lead = ' ' }
        $NewText = $Text.Substring(0, [int]$Last.ValueEnd) + ',' + $Lead + '"hooks": ' +
            (ConvertTo-JsonText $Plan.Hooks $Level $Unit $NewLine) +
            $Text.Substring([int]$Last.ValueEnd)
    }

    $Verified = Get-MemberValue (Read-JsonDocument $NewText) 'hooks'
    if ((ConvertTo-JsonText $Verified -Compact) -cne (ConvertTo-JsonText $Plan.Hooks -Compact)) {
        throw 'Reconciled settings failed self-check.'
    }
    $NewBytes = $Utf8NoBom.GetBytes($NewText)
    if ($File.Bom) { $NewBytes = [byte[]](0xEF, 0xBB, 0xBF) + $NewBytes }

    $Backup = $null
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    if ($File.Exists) {
        $Backup = Save-SettingsBackup $HomePath $File.Bytes
        # Клиент мог переписать файл, пока шла сверка: тогда не трогаем.
        if (-not (Test-SameBytes ([IO.File]::ReadAllBytes($Path)) $File.Bytes)) {
            return [pscustomobject][ordered]@{
                status = 'BLOCKED'; reason = 'settings.json changed during reconcile'
                removed = @(); foreign = [int]$Plan.Foreign; backup = $Backup
            }
        }
    }
    $Temporary = $Path + '.hygiene-' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllBytes($Temporary, $NewBytes)
        if ($File.Exists) {
            try { [IO.File]::Replace($Temporary, $Path, [NullString]::Value) }
            catch { [IO.File]::Copy($Temporary, $Path, $true) }
        }
        else { [IO.File]::Move($Temporary, $Path) }
    }
    finally {
        if (Test-Path -LiteralPath $Temporary -PathType Leaf) {
            Remove-Item -LiteralPath $Temporary -Force
        }
    }
    return [pscustomobject][ordered]@{
        status = 'UPDATED'; reason = $null
        removed = $Removed; foreign = [int]$Plan.Foreign; backup = $Backup
    }
}

function New-Finding {
    param([string]$Id, [string]$Path, [string]$Detail)

    return [pscustomobject][ordered]@{ id = $Id; path = $Path; detail = $Detail }
}

function Invoke-LegacyScan {
    param([string]$HomePath, [string]$RuntimeRoot, [AllowNull()]$Reconcile)

    $Findings = New-Object Collections.ArrayList
    $Claude = Join-Path $HomePath '.claude'
    $Policy = Get-HookPolicy $RuntimeRoot

    if ($null -ne $Reconcile -and [string]$Reconcile.status -in @('BLOCKED', 'WOULD_UPDATE')) {
        $Detail = 'hooks in settings.json differ from the release'
        if ($Reconcile.reason) { $Detail = [string]$Reconcile.reason }
        [void]$Findings.Add((New-Finding 'hooks_not_canonical' '.claude/settings.json' $Detail))
    }

    if (Test-Path -LiteralPath (Join-Path $Claude 'AGENTS.md') -PathType Leaf) {
        [void]$Findings.Add((New-Finding 'instruction_file' '.claude/AGENTS.md' `
            'instruction file outside the release; the client may load it next to CLAUDE.md'))
    }

    $Hooks = $null
    $File = Read-SettingsFile (Join-Path $Claude 'settings.json')
    if ($File.Exists -and ([string]$File.Text).Trim().Length -ne 0) {
        try { $Hooks = Get-MemberValue (Read-JsonDocument ([string]$File.Text)) 'hooks' }
        catch {
            [void]$Findings.Add((New-Finding 'settings_unreadable' '.claude/settings.json' `
                'settings.json is not valid JSON; hooks were not checked'))
        }
    }
    $Seen = @{}
    foreach ($Command in (Get-HookCommands $Hooks)) {
        foreach ($Reference in (Get-ClaudeScriptReferences $Command)) {
            if ($Seen.ContainsKey($Reference)) { continue }
            $Seen[$Reference] = $true
            $Target = Join-Path $Claude ($Reference.Replace('/', '\'))
            if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
                [void]$Findings.Add((New-Finding 'hook_missing_target' ('.claude/' + $Reference) `
                    'a hook points to a script that does not exist'))
                continue
            }
            foreach ($Root in $Policy.Roots) {
                if ($Reference.StartsWith($Root + '/')) {
                    [void]$Findings.Add((New-Finding 'hook_old_location' ('.claude/' + $Reference) `
                        'a hook outside the release runs a script from the previous base location'))
                    break
                }
            }
        }
    }

    if (Test-Path -LiteralPath (Join-Path $Claude '.git')) {
        [void]$Findings.Add((New-Finding 'old_checkout' '.claude/.git' `
            'git checkout of the previous base inside the profile'))
    }
    $Scripts = Join-Path $Claude 'scripts'
    if (Test-Path -LiteralPath $Scripts -PathType Container) {
        $Count = @(Get-ChildItem -LiteralPath $Scripts -Recurse -File -ErrorAction SilentlyContinue).Count
        [void]$Findings.Add((New-Finding 'old_scripts' '.claude/scripts' `
            ("scripts of the previous base: $Count file(s)")))
    }
    if (Test-Path -LiteralPath (Join-Path $Claude 'settings.shared.json') -PathType Leaf) {
        [void]$Findings.Add((New-Finding 'old_settings_template' '.claude/settings.shared.json' `
            'settings template of the previous base'))
    }

    $Cold = Join-Path $Claude 'base\cold\memory'
    $Memory = Join-Path $Claude 'memory'
    if ((Test-Path -LiteralPath $Cold -PathType Container) -and
        (Test-Path -LiteralPath $Memory -PathType Container)) {
        $Differ = New-Object 'Collections.Generic.List[string]'
        foreach ($Item in @(Get-ChildItem -LiteralPath $Cold -File | Sort-Object -Property Name)) {
            $Shadow = Join-Path $Memory $Item.Name
            if (-not (Test-Path -LiteralPath $Shadow -PathType Leaf)) { continue }
            $Left = [IO.File]::ReadAllText($Item.FullName, [Text.Encoding]::UTF8).Replace("`r`n", "`n").Trim()
            $Right = [IO.File]::ReadAllText($Shadow, [Text.Encoding]::UTF8).Replace("`r`n", "`n").Trim()
            if ($Left -cne $Right) { $Differ.Add($Item.Name) }
        }
        if ($Differ.Count -gt 0) {
            [void]$Findings.Add((New-Finding 'memory_shadow' '.claude/memory' `
                ("$($Differ.Count) file(s) differ from the release reference layer: " +
                    (@($Differ | Select-Object -First 5) -join ', '))))
        }
    }

    $Status = if ($Findings.Count -eq 0) { 'CLEAN' } else { 'FOUND' }
    return [pscustomobject][ordered]@{ status = $Status; findings = @($Findings) }
}

$Report = [ordered]@{ schema_version = 1; hooks = $null; legacy = $null }
try {
    $HomePath = [IO.Path]::GetFullPath($HomePath)
    $RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
    if ($Action -in @('All', 'Reconcile')) {
        try { $Report.hooks = Invoke-HooksReconcile -HomePath $HomePath -RuntimeRoot $RuntimeRoot -Check:$Check }
        catch {
            $Report.hooks = [pscustomobject][ordered]@{
                status = 'BLOCKED'; reason = [string]$_.Exception.Message
                removed = @(); foreign = 0; backup = $null
            }
        }
    }
    if ($Action -in @('All', 'Scan')) {
        try { $Report.legacy = Invoke-LegacyScan -HomePath $HomePath -RuntimeRoot $RuntimeRoot -Reconcile $Report.hooks }
        catch {
            $Report.legacy = [pscustomobject][ordered]@{
                status = 'FOUND'
                findings = @((New-Finding 'scan_failed' '.claude' ([string]$_.Exception.Message)))
            }
        }
    }
}
catch {
    $Report.hooks = [pscustomobject][ordered]@{
        status = 'BLOCKED'; reason = [string]$_.Exception.Message
        removed = @(); foreign = 0; backup = $null
    }
}
$Report | ConvertTo-Json -Compress -Depth 6
exit 0
