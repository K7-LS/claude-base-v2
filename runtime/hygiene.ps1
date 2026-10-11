[CmdletBinding()]
param(
    [ValidateSet('All', 'Reconcile', 'Scan')][string]$Action = 'All',
    [string]$HomePath = $env:USERPROFILE,
    [string]$RuntimeRoot = '',
    [ValidateRange(0, 60)][int]$WaitPreviousSyncSeconds = 0,
    [switch]$SessionStart,
    [switch]$Check
)

# Гигиена установленной базы:
#   Reconcile — приводит хуки базы в ~/.claude/settings.json к набору релиза;
#   Scan      — только читает и перечисляет остатки прежней базы.
# Меняется одно значение ключа "hooks": остальные байты settings.json
# остаются прежними, заменённый файл уходит в копии. Чужие хуки (не из базы)
# сохраняются. Файл, который нельзя прочитать строго как UTF-8 и JSON, не
# трогается. Скрипт не блокирует сессию: код возврата всегда 0.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) { $RuntimeRoot = $PSScriptRoot }

$script:MaxSettingsBytes = 524288
$script:MaxJsonDepth = 64
$script:Utf8Strict = New-Object Text.UTF8Encoding($false, $true)
# Строгая грамматика JSON: строки без управляющих символов и с известными
# экранированиями, пробельные символы — только четыре разрешённых, цифры ASCII.
$script:JsonTokenPattern = New-Object Text.RegularExpressions.Regex(
    '"(?:[^"\\\u0000-\u001F]|\\(?:["\\/bfnrt]|u[0-9A-Fa-f]{4}))*"|[{}\[\]:,]|[^ \t\r\n{}\[\]:,"]+'
)
$script:JsonLiteralPattern = '^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)$'
$script:JsonGapPattern = '[^ \t\r\n]'

function New-JsonReader {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

    $Tokens = $script:JsonTokenPattern.Matches($Text)
    $Position = 0
    foreach ($Token in $Tokens) {
        if ($Token.Index -gt $Position -and
            $Text.Substring($Position, $Token.Index - $Position) -match $script:JsonGapPattern) {
            throw 'JSON contains unexpected characters.'
        }
        $Position = $Token.Index + $Token.Length
    }
    if ($Position -lt $Text.Length -and $Text.Substring($Position) -match $script:JsonGapPattern) {
        throw 'JSON contains unexpected characters.'
    }
    return [pscustomobject]@{ Text = $Text; Tokens = $Tokens; Index = 0; Depth = 0 }
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
        $Escape = [string]$Body[$Index]
        if ($Escape -ceq '"' -or $Escape -ceq '\' -or $Escape -ceq '/') {
            [void]$Builder.Append($Escape)
        }
        elseif ($Escape -ceq 'b') { [void]$Builder.Append([char]8) }
        elseif ($Escape -ceq 'f') { [void]$Builder.Append([char]12) }
        elseif ($Escape -ceq 'n') { [void]$Builder.Append([char]10) }
        elseif ($Escape -ceq 'r') { [void]$Builder.Append([char]13) }
        elseif ($Escape -ceq 't') { [void]$Builder.Append([char]9) }
        else {
            [void]$Builder.Append([char][Convert]::ToInt32($Body.Substring($Index + 1, 4), 16))
            $Index += 4
        }
        $Index++
    }
    return $Builder.ToString()
}

function ConvertTo-JsonStringToken {
    param([AllowEmptyString()][string]$Value)

    $Builder = New-Object Text.StringBuilder
    [void]$Builder.Append('"')
    for ($Index = 0; $Index -lt $Value.Length; $Index++) {
        $Char = $Value[$Index]
        $Code = [int]$Char
        if ($Code -eq 34) { [void]$Builder.Append('\"') }
        elseif ($Code -eq 92) { [void]$Builder.Append('\\') }
        elseif ($Code -eq 10) { [void]$Builder.Append('\n') }
        elseif ($Code -eq 13) { [void]$Builder.Append('\r') }
        elseif ($Code -eq 9) { [void]$Builder.Append('\t') }
        elseif ($Code -eq 8) { [void]$Builder.Append('\b') }
        elseif ($Code -eq 12) { [void]$Builder.Append('\f') }
        elseif ($Code -lt 32) { [void]$Builder.Append('\u' + $Code.ToString('x4')) }
        elseif ([char]::IsHighSurrogate($Char) -and $Index + 1 -lt $Value.Length -and
            [char]::IsLowSurrogate($Value[$Index + 1])) {
            [void]$Builder.Append($Char).Append($Value[$Index + 1])
            $Index++
        }
        # Одиночный суррогат в UTF-8 не записать: остаётся экранированным.
        elseif ([char]::IsSurrogate($Char)) { [void]$Builder.Append('\u' + $Code.ToString('x4')) }
        else { [void]$Builder.Append($Char) }
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

# Значения: объект — OrderedDictionary, массив — ArrayList, строка —
# Tuple[string,string] (значение и исходный токен), число и true/false/null —
# Tuple[string] с исходным токеном. Исходные токены уходят в файл как были.
function Read-JsonValue {
    param([Parameter(Mandatory = $true)]$Reader)

    $Token = Read-JsonToken $Reader
    $Value = [string]$Token.Value
    if ($Value -ceq '{' -or $Value -ceq '[') {
        $Reader.Depth = $Reader.Depth + 1
        if ($Reader.Depth -gt $script:MaxJsonDepth) { throw 'JSON is nested too deeply.' }
    }
    if ($Value -ceq '{') {
        $Object = New-Object Collections.Specialized.OrderedDictionary
        if ([string]$Reader.Tokens[$Reader.Index].Value -ceq '}') {
            $Reader.Index = $Reader.Index + 1
        }
        else {
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
        }
        $Reader.Depth = $Reader.Depth - 1
        return $Object
    }
    if ($Value -ceq '[') {
        $List = New-Object Collections.ArrayList
        if ([string]$Reader.Tokens[$Reader.Index].Value -ceq ']') {
            $Reader.Index = $Reader.Index + 1
        }
        else {
            while ($true) {
                $Item = Read-JsonValue $Reader
                [void]$List.Add($Item)
                $Next = [string](Read-JsonToken $Reader).Value
                if ($Next -ceq ']') { break }
                if ($Next -cne ',') { throw 'JSON array lacks a comma.' }
            }
        }
        $Reader.Depth = $Reader.Depth - 1
        return , $List
    }
    if ($Value.StartsWith('"')) {
        return (New-Object 'Tuple[string,string]' (ConvertFrom-JsonStringToken $Value), $Value)
    }
    if ($Value -cnotmatch $script:JsonLiteralPattern) { throw 'JSON literal is invalid.' }
    return (New-Object 'Tuple[string]' $Value)
}

function Get-JsonString {
    param([AllowNull()]$Value)

    if ($Value -is [Tuple[string, string]]) { return [string]$Value.Item1 }
    return $null
}

# Canonical — строки заново экранируются из значений (для сравнения по смыслу);
# без него строки пишутся исходными токенами.
function ConvertTo-JsonText {
    param(
        [AllowNull()]$Value,
        [int]$Level = 0,
        [string]$Unit = '  ',
        [string]$NewLine = "`n",
        [switch]$Compact,
        [switch]$Canonical
    )

    if ($Value -is [Tuple[string, string]]) {
        if ($Canonical) { return (ConvertTo-JsonStringToken ([string]$Value.Item1)) }
        return [string]$Value.Item2
    }
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
                (ConvertTo-JsonText $Value[[string]$Key] ($Level + 1) $Unit $NewLine `
                    -Compact:$Compact -Canonical:$Canonical)
            )
        }
        return '{' + $Break + ($Parts -join (',' + $Break)) + $Break + $Outer + '}'
    }
    if ($Value -is [Collections.ArrayList]) {
        if ($Value.Count -eq 0) { return '[]' }
        $Parts = New-Object 'Collections.Generic.List[string]'
        foreach ($Item in $Value) {
            $Parts.Add(
                $Inner + (ConvertTo-JsonText $Item ($Level + 1) $Unit $NewLine `
                    -Compact:$Compact -Canonical:$Canonical)
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
    if ($Start -lt 0 -or $Prefix -match '[^ \t]') { return $null }
    return $Prefix
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Bytes = [IO.File]::ReadAllBytes($Path)
    $Offset = 0
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        $Offset = 3
    }
    return (Read-JsonDocument ($script:Utf8Strict.GetString($Bytes, $Offset, $Bytes.Length - $Offset)))
}

function Get-MemberValue {
    param($Document, [string]$Key)

    foreach ($Member in $Document.Members) {
        if ([string]$Member.Key -ceq $Key) { return , $Member.Value }
    }
    return $null
}

function Get-PolicyPaths {
    param($Document, [string]$Field)

    $Items = Get-MemberValue $Document $Field
    if ($Items -isnot [Collections.ArrayList]) { throw 'Hook policy is invalid.' }
    $Result = New-Object 'Collections.Generic.List[string]'
    foreach ($Item in $Items) {
        $Value = Get-JsonString $Item
        if ([string]::IsNullOrWhiteSpace($Value)) { throw 'Hook policy is invalid.' }
        $Result.Add($Value.ToLowerInvariant().Trim('/'))
    }
    return , $Result
}

# Контекст сверки: что в ~/.claude принадлежит базе и как узнать домашний
# каталог в тексте команды. Ссылка считается только от профиля пользователя:
# одноимённый путь в проекте или на другом диске базе не принадлежит.
function New-HookContext {
    param([Parameter(Mandatory = $true)][string]$HomePath, [Parameter(Mandatory = $true)][string]$RuntimeRoot)

    $Document = Read-JsonFile (Join-Path $RuntimeRoot 'hooks-policy.json')
    $Previous = New-Object 'Collections.Generic.List[string]'
    foreach ($Field in @('superseded', 'retired')) {
        foreach ($Item in (Get-PolicyPaths $Document $Field)) { $Previous.Add($Item) }
    }
    $Literal = [regex]::Escape($HomePath.TrimEnd('\', '/')).Replace('\\', '[\\/]+')
    # Тильда — только отдельным началом пути, а не хвостом чужого имени.
    $HomePattern = '(?:\$HOME|\$env:USERPROFILE|\$\{env:USERPROFILE\}|%USERPROFILE%|(?<![^\s"''])~|' +
        $Literal + ')'
    $Quoted = '(?:"(?<path>[^"]+)"|''(?<path>[^'']+)'')'
    return [pscustomobject]@{
        HomePattern = $HomePattern
        Previous = $Previous
        PreviousSync = (Get-PolicyPaths $Document 'previous_sync')
        LegacyRoots = (Get-PolicyPaths $Document 'legacy_roots')
        # Известные формы запуска скрипта базы — команда целиком.
        Launchers = @(
            ('(?i)^\s*&\s*' + $Quoted + '\s*$'),
            ('(?i)^\s*(?:powershell|pwsh)(?:\.exe)?' +
                '(?:\s+-(?:NoProfile|NonInteractive|NoLogo)|\s+-(?:ExecutionPolicy|WindowStyle)\s+[A-Za-z]+)*' +
                '\s+-File\s+' + $Quoted + '\s*$')
        )
        ProfilePath = ('(?i)^' + $HomePattern + '[\\/]+\.claude[\\/]+(?<rel>.+)$')
        Reference = ('(?i)' + $HomePattern +
            '[\\/]+\.claude[\\/]+(?<rel>[^"''\s<>|;]+?\.(?:ps1|py))(?![A-Za-z0-9_])')
    }
}

function ConvertTo-RelativeKey {
    param([string]$Value)

    return ([regex]::Replace($Value, '[\\/]+', '/')).ToLowerInvariant()
}

# Скрипты внутри ~/.claude, упомянутые в команде в любом виде (для отчёта).
function Get-ProfileReferences {
    param([AllowEmptyString()][string]$Command, [Parameter(Mandatory = $true)]$Context)

    $Result = New-Object 'Collections.Generic.List[string]'
    foreach ($Match in [regex]::Matches($Command, $Context.Reference)) {
        $Result.Add((ConvertTo-RelativeKey $Match.Groups['rel'].Value))
    }
    return , $Result
}

# Хук базы — это команда, которая целиком запускает скрипт релиза или
# скрипт прежней базы из списка. Возвращает путь скрипта от ~/.claude.
function Get-ManagedHookTarget {
    param([AllowEmptyString()][string]$Command, [Parameter(Mandatory = $true)]$Context)

    foreach ($Launcher in $Context.Launchers) {
        $Match = [regex]::Match($Command, $Launcher)
        if (-not $Match.Success) { continue }
        $Path = [regex]::Match($Match.Groups['path'].Value, $Context.ProfilePath)
        if (-not $Path.Success) { return $null }
        $Relative = ConvertTo-RelativeKey $Path.Groups['rel'].Value
        if ($Relative -cmatch '^base/runtime/hooks/[a-z0-9_.-]+\.ps1$' -or
            $Context.Previous.Contains($Relative)) {
            return $Relative
        }
        return $null
    }
    return $null
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
                if ($Hook -isnot [Collections.Specialized.OrderedDictionary] -or
                    -not $Hook.Contains('command')) { continue }
                $Command = Get-JsonString $Hook['command']
                if ($null -ne $Command) { $Result.Add($Command) }
            }
        }
    }
    return , $Result
}

function Get-TemplateHooks {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot, [Parameter(Mandatory = $true)]$Context)

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
    # Шаблон обязан распознаваться собственной сверкой, иначе повторный
    # запуск добавлял бы его записи заново.
    $Commands = Get-HookCommands $Hooks
    if ($Commands.Count -eq 0) { throw 'Settings template has no hooks.' }
    foreach ($Command in $Commands) {
        if ($null -eq (Get-ManagedHookTarget $Command $Context)) {
            throw 'Settings template hook is not a base runtime launcher.'
        }
    }
    return $Hooks
}

function Get-ReconciledHooks {
    param([AllowNull()]$Current, [Parameter(Mandatory = $true)]$Template, [Parameter(Mandatory = $true)]$Context)

    $Removed = New-Object 'Collections.Generic.List[string]'
    $Replaced = 0
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
                    $Target = $null
                    if ($Hook -is [Collections.Specialized.OrderedDictionary] -and $Hook.Contains('command')) {
                        $Command = Get-JsonString $Hook['command']
                        if ($null -ne $Command) { $Target = Get-ManagedHookTarget $Command $Context }
                    }
                    if ($null -eq $Target) {
                        [void]$KeptHooks.Add($Hook)
                        $Foreign++
                        continue
                    }
                    $Replaced++
                    if ($Context.Previous.Contains($Target) -and -not $Removed.Contains($Target)) {
                        $Removed.Add($Target)
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
    return [pscustomobject]@{
        Hooks = $Result
        Removed = $Removed
        Replaced = $Replaced
        Foreign = $Foreign
    }
}

function Test-SameBytes {
    param([AllowNull()][AllowEmptyCollection()][byte[]]$Left, [AllowNull()][AllowEmptyCollection()][byte[]]$Right)

    if ($null -eq $Left -or $null -eq $Right) { return ($null -eq $Left -and $null -eq $Right) }
    if ($Left.Length -ne $Right.Length) { return $false }
    return ([Convert]::ToBase64String($Left) -ceq [Convert]::ToBase64String($Right))
}

# Состояние settings.json. Reason заполнен, когда файл нельзя трогать.
function Read-SettingsState {
    param([Parameter(Mandatory = $true)][string]$Path)

    $State = [pscustomobject]@{
        Reason = $null; Unreadable = $false; Exists = $false; Bytes = $null; Bom = $false
        Text = ''; Blank = $true; Document = $null; Member = $null; Hooks = $null
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $State }
    $State.Exists = $true
    $Bytes = [IO.File]::ReadAllBytes($Path)
    $State.Bytes = $Bytes
    if ($Bytes.Length -gt $script:MaxSettingsBytes) {
        $State.Reason = 'settings.json is too large to reconcile'
        $State.Unreadable = $true
        return $State
    }
    $Offset = 0
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        $State.Bom = $true
        $Offset = 3
    }
    try {
        # Строгое чтение: байты вне UTF-8 при записи превратились бы в мусор.
        $Text = $script:Utf8Strict.GetString($Bytes, $Offset, $Bytes.Length - $Offset)
        $Encoded = $script:Utf8Strict.GetBytes($Text)
        if ($Encoded.Length -ne $Bytes.Length - $Offset) { throw 'UTF-8 round trip differs.' }
    }
    catch {
        $State.Reason = 'settings.json is not valid UTF-8'
        $State.Unreadable = $true
        return $State
    }
    $State.Text = $Text
    $State.Blank = ($Text -notmatch $script:JsonGapPattern)
    if ($State.Blank) { return $State }
    try { $State.Document = Read-JsonDocument $Text }
    catch {
        $State.Reason = 'settings.json is not valid JSON'
        if ([string]$_.Exception.Message -ceq 'JSON is nested too deeply.') {
            $State.Reason = 'settings.json is nested too deeply to reconcile'
        }
        $State.Unreadable = $true
        return $State
    }
    foreach ($Candidate in $State.Document.Members) {
        if ([string]$Candidate.Key -ceq 'hooks') { $State.Member = $Candidate }
    }
    if ($null -ne $State.Member) {
        if ($State.Member.Value -isnot [Collections.Specialized.OrderedDictionary]) {
            $State.Reason = 'settings.json hooks value is not an object'
            return $State
        }
        $State.Hooks = $State.Member.Value
    }
    return $State
}

function Save-SettingsBackup {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Displaced,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Bytes
    )

    $Algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $Hash = (-join ($Algorithm.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') })).Substring(0, 12)
    }
    finally { $Algorithm.Dispose() }
    # Одно и то же состояние второй раз не копируется.
    $Same = @(Get-ChildItem -LiteralPath $Root -Filter ('settings-*-' + $Hash + '.json') -File)
    if ($Same.Count -gt 0) { return ('.claude/base/state/settings-backups/' + $Same[0].Name) }
    $Name = 'settings-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + $Hash + '.json'
    [IO.File]::Move($Displaced, (Join-Path $Root $Name))
    # Хранятся самая первая копия (состояние до первой сверки) и девять последних.
    $All = @(Get-ChildItem -LiteralPath $Root -Filter 'settings-*.json' -File | Sort-Object -Property Name)
    if ($All.Count -gt 10) {
        foreach ($Item in $All[1..($All.Count - 10)]) { Remove-Item -LiteralPath $Item.FullName -Force }
    }
    return ('.claude/base/state/settings-backups/' + $Name)
}

function New-ReconcileResult {
    param([string]$Status, [AllowNull()][string]$Reason = $null, $Plan = $null, [AllowNull()][string]$Backup = $null)

    $Removed = @()
    $Replaced = 0
    $Foreign = 0
    if ($null -ne $Plan) {
        $Removed = @($Plan.Removed | Sort-Object)
        $Replaced = [int]$Plan.Replaced
        $Foreign = [int]$Plan.Foreign
    }
    # Параметры типа string не хранят $null, поэтому пустое значение
    # переносится в нетипизированные переменные.
    $ReasonValue = $null
    $BackupValue = $null
    if (-not [string]::IsNullOrEmpty($Reason)) { $ReasonValue = $Reason }
    if (-not [string]::IsNullOrEmpty($Backup)) { $BackupValue = $Backup }
    return [pscustomobject][ordered]@{
        status = $Status; reason = $ReasonValue; replaced = $Replaced
        removed = $Removed; foreign = $Foreign; backup = $BackupValue
    }
}

# Синхронизация прежней базы в конце своего хука заново вливает хуки из общего
# шаблона. Пока она идёт, сверка была бы тут же отменена, поэтому её
# завершения ждут. Учитываются только процессы этого профиля. Возвращает
# finished, running или unknown (список процессов недоступен).
function Wait-PreviousSync {
    param([int]$Seconds, [Parameter(Mandatory = $true)]$Context, [switch]$Settle)

    $Names = @($Context.PreviousSync | ForEach-Object { [regex]::Escape($_).Replace('/', '[\\/]+') })
    $Pattern = '(?i)' + $Context.HomePattern + '[\\/]+\.claude[\\/]+(?:' + ($Names -join '|') + ')'
    $Deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    # Хук синхронизации стартует параллельно: даём ему появиться в списке.
    if ($Settle) { Start-Sleep -Milliseconds 1000 }
    while ($true) {
        try {
            $Running = @(
                Get-CimInstance -ClassName Win32_Process `
                    -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" -ErrorAction Stop |
                    Where-Object { $_.ProcessId -ne $PID -and [string]$_.CommandLine -match $Pattern }
            )
        }
        catch { return 'unknown' }
        if ($Running.Count -eq 0) { return 'finished' }
        if ([DateTime]::UtcNow -ge $Deadline) { return 'running' }
        Start-Sleep -Milliseconds 500
    }
}

function Test-PreviousSyncWired {
    param([AllowNull()]$Hooks, [Parameter(Mandatory = $true)]$Context)

    foreach ($Command in (Get-HookCommands $Hooks)) {
        foreach ($Reference in (Get-ProfileReferences $Command $Context)) {
            if ($Context.PreviousSync.Contains($Reference)) { return $true }
        }
    }
    return $false
}

# Скрипты синхронизации прежней базы лежат в профиле: её хук мог сработать из
# снимка настроек клиента, даже если в файле его уже нет.
function Test-PreviousSyncPresent {
    param([string]$HomePath, [Parameter(Mandatory = $true)]$Context)

    foreach ($Relative in $Context.PreviousSync) {
        $Target = Join-Path (Join-Path $HomePath '.claude') $Relative.Replace('/', '\')
        if (Test-Path -LiteralPath $Target -PathType Leaf) { return $true }
    }
    return $false
}

function Invoke-HooksReconcile {
    param(
        [string]$HomePath,
        [string]$RuntimeRoot,
        [int]$WaitSeconds,
        [switch]$SessionStart,
        [switch]$Check
    )

    $Context = New-HookContext $HomePath $RuntimeRoot
    $Template = Get-TemplateHooks $RuntimeRoot $Context
    $Path = Join-Path $HomePath '.claude\settings.json'
    $State = Read-SettingsState $Path
    if ($State.Reason) { return (New-ReconcileResult 'BLOCKED' $State.Reason) }

    if (-not $Check -and $WaitSeconds -gt 0) {
        $Wired = Test-PreviousSyncWired $State.Hooks $Context
        if ($Wired -or (Test-PreviousSyncPresent $HomePath $Context)) {
            $Sync = Wait-PreviousSync $WaitSeconds $Context -Settle:($Wired -and $SessionStart)
            # Без списка процессов на старте сессии с подключённым хуком
            # синхронизации исход гонки неизвестен: файл не трогается.
            if ($Sync -ceq 'running' -or ($Sync -ceq 'unknown' -and $Wired -and $SessionStart)) {
                return (New-ReconcileResult 'DEFERRED' 'the previous base sync is still running')
            }
            $State = Read-SettingsState $Path
            if ($State.Reason) { return (New-ReconcileResult 'BLOCKED' $State.Reason) }
        }
    }

    $Plan = Get-ReconciledHooks $State.Hooks $Template $Context
    if ($null -ne $State.Hooks -and
        (ConvertTo-JsonText $State.Hooks -Compact -Canonical) -ceq
        (ConvertTo-JsonText $Plan.Hooks -Compact -Canonical)) {
        $Plan.Removed.Clear()
        $Plan.Replaced = 0
        return (New-ReconcileResult 'CANONICAL' $null $Plan)
    }
    if ($Check) { return (New-ReconcileResult 'WOULD_UPDATE' $null $Plan) }

    $Text = [string]$State.Text
    $NewLine = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    if ($State.Blank) {
        $NewText = '{' + $NewLine + '  "hooks": ' +
            (ConvertTo-JsonText $Plan.Hooks 1 '  ' $NewLine) + $NewLine + '}' + $NewLine
    }
    elseif ($null -ne $State.Member) {
        $Indent = Get-LineIndent $Text ([int]$State.Member.KeyIndex)
        $Level = 1
        $Unit = $Indent
        if ([string]::IsNullOrEmpty($Indent)) { $Level = 0; $Unit = '  ' }
        $NewText = $Text.Substring(0, [int]$State.Member.ValueStart) +
            (ConvertTo-JsonText $Plan.Hooks $Level $Unit $NewLine) +
            $Text.Substring([int]$State.Member.ValueEnd)
    }
    elseif ($State.Document.Members.Count -eq 0) {
        $NewText = $Text.Substring(0, [int]$State.Document.OpenIndex + 1) + $NewLine + '  "hooks": ' +
            (ConvertTo-JsonText $Plan.Hooks 1 '  ' $NewLine) + $NewLine +
            $Text.Substring([int]$State.Document.CloseIndex)
    }
    else {
        $Last = $State.Document.Members[$State.Document.Members.Count - 1]
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
    if ((ConvertTo-JsonText $Verified -Compact -Canonical) -cne
        (ConvertTo-JsonText $Plan.Hooks -Compact -Canonical)) {
        throw 'Reconciled settings failed self-check.'
    }
    $NewBytes = $script:Utf8Strict.GetBytes($NewText)
    if ($State.Bom) { $NewBytes = [byte[]](0xEF, 0xBB, 0xBF) + $NewBytes }
    # Файл не должен перерасти собственный предел сверки.
    if ($NewBytes.Length -gt $script:MaxSettingsBytes) {
        return (New-ReconcileResult 'BLOCKED' 'settings.json would grow too large to reconcile' $Plan)
    }

    $Backups = Join-Path $HomePath '.claude\base\state\settings-backups'
    $Stamp = [Guid]::NewGuid().ToString('N')
    $Temporary = $Path + '.hygiene-' + $Stamp + '.tmp'
    $Displaced = $Path + '.hygiene-' + $Stamp + '.old'
    $Backup = $null
    # Вытесненный файл удаляется, только когда его содержимое сохранено.
    $DisplacedSafe = $false
    try {
        [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
        [IO.File]::WriteAllBytes($Temporary, $NewBytes)
        if (-not $State.Exists) {
            [IO.File]::Move($Temporary, $Path)
        }
        else {
            # Без места для копии файл не заменяется.
            [IO.Directory]::CreateDirectory($Backups) | Out-Null
            try { [IO.File]::Replace($Temporary, $Path, $Displaced) }
            catch {
                # Замена оборвалась на полпути: прежний файл возвращается на место.
                if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -and
                    (Test-Path -LiteralPath $Displaced -PathType Leaf)) {
                    [IO.File]::Move($Displaced, $Path)
                }
                return (New-ReconcileResult 'BLOCKED' 'settings.json could not be replaced' $Plan)
            }
            # Заменённый файл и есть копия. Если клиент успел переписать
            # настройки после чтения, возвращается его версия.
            $Latest = [IO.File]::ReadAllBytes($Displaced)
            if (-not (Test-SameBytes $Latest $State.Bytes)) {
                try {
                    [IO.File]::Replace($Displaced, $Path, [NullString]::Value)
                    $DisplacedSafe = $true
                    return (New-ReconcileResult 'BLOCKED' 'settings.json changed during reconcile' $Plan)
                }
                catch {
                    # Вернуть не удалось: версия клиента уходит в копии.
                    $Backup = Save-SettingsBackup $Backups $Displaced $Latest
                    $DisplacedSafe = $true
                    return (New-ReconcileResult 'BLOCKED' `
                        'settings.json changed during reconcile; its latest version is in settings-backups' `
                        $Plan $Backup)
                }
            }
            $Backup = Save-SettingsBackup $Backups $Displaced $State.Bytes
            $DisplacedSafe = $true
        }
    }
    finally {
        if (Test-Path -LiteralPath $Temporary -PathType Leaf) {
            Remove-Item -LiteralPath $Temporary -Force -ErrorAction SilentlyContinue
        }
        if ($DisplacedSafe -and (Test-Path -LiteralPath $Displaced -PathType Leaf)) {
            Remove-Item -LiteralPath $Displaced -Force -ErrorAction SilentlyContinue
        }
    }
    return (New-ReconcileResult 'UPDATED' $null $Plan $Backup)
}

function New-Finding {
    param([string]$Id, [string]$Path, [string]$Detail)

    return [pscustomobject][ordered]@{ id = $Id; path = $Path; detail = $Detail }
}

function Invoke-LegacyScan {
    param([string]$HomePath, [string]$RuntimeRoot, [AllowNull()]$Reconcile)

    $Findings = New-Object Collections.ArrayList
    $Claude = Join-Path $HomePath '.claude'
    $Context = New-HookContext $HomePath $RuntimeRoot
    $State = Read-SettingsState (Join-Path $Claude 'settings.json')

    if ($State.Unreadable) {
        [void]$Findings.Add((New-Finding 'settings_unreadable' '.claude/settings.json' `
            ([string]$State.Reason + '; hooks were not checked')))
    }
    elseif ($null -ne $Reconcile -and [string]$Reconcile.status -in @('BLOCKED', 'WOULD_UPDATE', 'DEFERRED')) {
        $Detail = 'hooks in settings.json differ from the release'
        if ($Reconcile.reason) { $Detail = [string]$Reconcile.reason }
        [void]$Findings.Add((New-Finding 'hooks_not_canonical' '.claude/settings.json' $Detail))
    }

    if (Test-Path -LiteralPath (Join-Path $Claude 'AGENTS.md') -PathType Leaf) {
        [void]$Findings.Add((New-Finding 'instruction_file' '.claude/AGENTS.md' `
            'instruction file outside the release; the client may load it next to CLAUDE.md'))
    }

    $Seen = @{}
    $Old = 0
    foreach ($Command in (Get-HookCommands $State.Hooks)) {
        foreach ($Reference in (Get-ProfileReferences $Command $Context)) {
            if ($Seen.ContainsKey($Reference)) { continue }
            $Seen[$Reference] = $true
            $Target = Join-Path $Claude ($Reference.Replace('/', '\'))
            if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
                [void]$Findings.Add((New-Finding 'hook_missing_target' ('.claude/' + $Reference) `
                    'a hook points to a script that does not exist'))
                continue
            }
            foreach ($Root in $Context.LegacyRoots) {
                if ($Reference.StartsWith($Root + '/')) {
                    $Old++
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
        $Detail = "scripts of the previous base: $Count file(s)"
        if ($Old -gt 0) { $Detail += "; $Old of them still run from hooks outside the release" }
        [void]$Findings.Add((New-Finding 'old_scripts' '.claude/scripts' $Detail))
    }
    if (Test-Path -LiteralPath (Join-Path $Claude 'settings.shared.json') -PathType Leaf) {
        [void]$Findings.Add((New-Finding 'old_settings_template' '.claude/settings.shared.json' `
            'settings template of the previous base; its sync rewrites hooks from this file'))
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
        try {
            $Report.hooks = Invoke-HooksReconcile -HomePath $HomePath -RuntimeRoot $RuntimeRoot `
                -WaitSeconds $WaitPreviousSyncSeconds -SessionStart:$SessionStart -Check:$Check
        }
        catch { $Report.hooks = New-ReconcileResult 'BLOCKED' ([string]$_.Exception.Message) }
    }
    if ($Action -in @('All', 'Scan')) {
        try {
            $Report.legacy = Invoke-LegacyScan -HomePath $HomePath -RuntimeRoot $RuntimeRoot `
                -Reconcile $Report.hooks
        }
        catch {
            $Report.legacy = [pscustomobject][ordered]@{
                status = 'FOUND'
                findings = @((New-Finding 'scan_failed' '.claude' ([string]$_.Exception.Message)))
            }
        }
    }
}
catch {
    $Report.hooks = New-ReconcileResult 'BLOCKED' ([string]$_.Exception.Message)
}
$Report | ConvertTo-Json -Compress -Depth 6
exit 0
