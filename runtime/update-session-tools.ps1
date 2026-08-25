[CmdletBinding()]
param(
    [switch]$ManagedPreflight,
    [switch]$HookFallback,
    [string]$TransactionId,
    [Int64]$StartTick,
    [Int64]$MutationCutoffTick,
    [Int64]$KillTick,
    [Int64]$HardDeadlineTick,
    [Int64]$StopwatchFrequency
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Utf8NoBom = New-Object Text.UTF8Encoding($false, $true)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$Target = 'claude'
$Repository = 'K7-LS/claude-base-v2'
$RepositoryUrl = "https://github.com/$Repository"
$AllowedExtensions = @(
    '.docx', '.js', '.json', '.lsp', '.md', '.patch', '.ps1', '.py',
    '.tmpl', '.toml', '.txt', '.xlsx', '.yaml', '.yml'
)
$AllowedSpecialNames = @('.gitkeep', '.graphify_version')
$StateRoot = Join-Path $env:USERPROFILE '.llm-foundation\state\session-tools\claude'
$StatePath = Join-Path $StateRoot 'state.json'
$JournalPath = Join-Path $StateRoot 'active-transaction.json'
$LockPath = Join-Path $StateRoot 'update.lock'
$DownloadsPath = Join-Path $StateRoot 'downloads'
$SkillsRoot = Join-Path $env:USERPROFILE '.claude\skills'
$BaselinePath = Join-Path $env:USERPROFILE '.claude\base\runtime\session-tools-baseline.json'
$ReceiptPath = Join-Path $env:USERPROFILE '.llm-foundation\bin\claude-managed.receipt.json'

function Test-ExactTickContract {
    param(
        [Int64]$Start,
        [Int64]$Mutation,
        [Int64]$Kill,
        [Int64]$Deadline,
        [Int64]$Frequency
    )
    if ($Start -le 0 -or $Frequency -le 0 -or
        $Frequency -ne [Diagnostics.Stopwatch]::Frequency) { return $false }
    if ($Frequency -gt [Int64]::MaxValue / 30L -or
        $Start -gt [Int64]::MaxValue - 30L * $Frequency) { return $false }
    return (
        $Mutation -eq ($Start + 22L * $Frequency) -and
        $Kill -eq ($Start + 25L * $Frequency) -and
        $Deadline -eq ($Start + 30L * $Frequency)
    )
}

if ($ManagedPreflight -eq $HookFallback -or
    ($ManagedPreflight -and (
        -not [Guid]::TryParseExact($TransactionId, 'D', [ref]([Guid]::Empty)) -or
        $TransactionId -cne ([Guid]$TransactionId).ToString('D') -or
        -not (Test-ExactTickContract $StartTick $MutationCutoffTick $KillTick $HardDeadlineTick $StopwatchFrequency)
    ))) {
    [Console]::Error.WriteLine('BLOCKED_INVALID_PREFLIGHT')
    exit 64
}

if ($HookFallback) {
    $TransactionId = [Guid]::NewGuid().ToString('D')
    $StopwatchFrequency = [Diagnostics.Stopwatch]::Frequency
    $StartTick = [Diagnostics.Stopwatch]::GetTimestamp()
    $MutationCutoffTick = $StartTick + 22L * $StopwatchFrequency
    $KillTick = $StartTick + 25L * $StopwatchFrequency
    $HardDeadlineTick = $StartTick + 30L * $StopwatchFrequency
}

if ($ManagedPreflight -and [Diagnostics.Stopwatch]::GetTimestamp() -ge $HardDeadlineTick) {
    [Console]::Error.WriteLine('BLOCKED_SESSION_RECOVERY')
    exit 65
}

if (-not ('Foundation.SessionTools.StrictJsonGuard' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;

namespace Foundation.SessionTools
{
    public static class StrictJsonGuard
    {
        public static void Validate(string text)
        {
            if (text == null || (text.Length > 0 && text[0] == '\ufeff'))
                throw new FormatException("invalid UTF-8 JSON");
            Parser parser = new Parser(text);
            parser.Value();
            parser.White();
            if (!parser.End) throw new FormatException("trailing JSON content");
        }

        private sealed class Parser
        {
            private readonly string text;
            private int index;
            internal Parser(string value) { text = value; }
            internal bool End { get { return index == text.Length; } }
            internal void White()
            {
                while (index < text.Length)
                {
                    char value = text[index];
                    if (value != ' ' && value != '\t' && value != '\r' && value != '\n') break;
                    index++;
                }
            }
            private char Take() { if (index >= text.Length) throw new FormatException("unexpected end"); return text[index++]; }
            private char Peek() { if (index >= text.Length) throw new FormatException("unexpected end"); return text[index]; }
            internal void Value()
            {
                White();
                char value = Peek();
                if (value == '{') Object();
                else if (value == '[') Array();
                else if (value == '"') String(false);
                else if (value == 't') Literal("true");
                else if (value == 'f') Literal("false");
                else if (value == 'n') Literal("null");
                else Number();
            }
            private void Object()
            {
                Take(); White();
                HashSet<string> names = new HashSet<string>(StringComparer.Ordinal);
                if (Peek() == '}') { Take(); return; }
                while (true)
                {
                    string name = String(true);
                    if (!names.Add(name)) throw new FormatException("duplicate JSON key");
                    White(); if (Take() != ':') throw new FormatException("missing colon");
                    Value(); White();
                    char next = Take();
                    if (next == '}') return;
                    if (next != ',') throw new FormatException("invalid object separator");
                    White();
                }
            }
            private void Array()
            {
                Take(); White();
                if (Peek() == ']') { Take(); return; }
                while (true)
                {
                    Value(); White();
                    char next = Take();
                    if (next == ']') return;
                    if (next != ',') throw new FormatException("invalid array separator");
                    White();
                }
            }
            private string String(bool property)
            {
                if (Take() != '"') throw new FormatException("string expected");
                System.Text.StringBuilder result = new System.Text.StringBuilder();
                while (true)
                {
                    char value = Take();
                    if (value == '"') return result.ToString();
                    if (value < 0x20) throw new FormatException("control character");
                    if (value != '\\') { result.Append(value); continue; }
                    if (property) throw new FormatException("escaped property name");
                    char escape = Take();
                    if (escape == 'u')
                    {
                        for (int count = 0; count < 4; count++)
                        {
                            char hex = Take();
                            if (!Uri.IsHexDigit(hex)) throw new FormatException("invalid unicode escape");
                        }
                    }
                    else if ("\"\\/bfnrt".IndexOf(escape) < 0)
                        throw new FormatException("invalid string escape");
                }
            }
            private void Number()
            {
                if (Peek() == '-') Take();
                if (Peek() == '0') Take();
                else { Digit(true); while (index < text.Length && Char.IsDigit(text[index])) index++; }
                if (index < text.Length && text[index] == '.')
                { index++; Digit(true); while (index < text.Length && Char.IsDigit(text[index])) index++; }
                if (index < text.Length && (text[index] == 'e' || text[index] == 'E'))
                {
                    index++;
                    if (index < text.Length && (text[index] == '+' || text[index] == '-')) index++;
                    Digit(true); while (index < text.Length && Char.IsDigit(text[index])) index++;
                }
            }
            private void Digit(bool required)
            {
                if (index >= text.Length || !Char.IsDigit(text[index]))
                    throw new FormatException("digit expected");
                index++;
            }
            private void Literal(string value)
            {
                foreach (char expected in value) if (Take() != expected) throw new FormatException("invalid literal");
            }
        }
    }
}
'@
}

function Read-StrictJsonBytes {
    param([byte[]]$Bytes)
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        throw 'UTF-8 BOM is not accepted'
    }
    $Text = $Utf8NoBom.GetString($Bytes)
    [Foundation.SessionTools.StrictJsonGuard]::Validate($Text)
    return ($Text | ConvertFrom-Json)
}

function Read-StrictJsonFile {
    param([string]$Path)
    return Read-StrictJsonBytes ([IO.File]::ReadAllBytes($Path))
}

function Assert-ExactProperties {
    param($Value, [string[]]$Expected, [string]$Label)
    if ($null -eq $Value -or $Value -isnot [psobject]) { throw "$Label is not an object" }
    $Actual = @($Value.PSObject.Properties | ForEach-Object { $_.Name })
    if ($Actual.Count -ne $Expected.Count) { throw "$Label fields differ" }
    foreach ($Name in $Expected) {
        if (-not ($Actual -ccontains $Name)) { throw "$Label fields differ" }
    }
}

function Test-Integer {
    param($Value)
    return ($Value -is [Int32] -or $Value -is [Int64])
}

function Get-Sha256Bytes {
    param([byte[]]$Bytes)
    $Hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $Hash.Dispose() }
}

function Get-Sha256File {
    param([string]$Path)
    return Get-Sha256Bytes ([IO.File]::ReadAllBytes($Path))
}

function Test-Sha256 {
    param($Value)
    return ($Value -is [string] -and $Value -cmatch '^[0-9a-f]{64}$')
}

function Test-ReparseAtOrAbove {
    param([string]$Path)
    $Current = [IO.Path]::GetFullPath($Path)
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $true }
        }
        $Parent = [IO.Path]::GetDirectoryName($Current)
        if (-not $Parent -or $Parent -eq $Current) { break }
        $Current = $Parent
    }
    return $false
}

function Test-ReparseTree {
    param([string]$Path)
    if (Test-ReparseAtOrAbove $Path) { return $true }
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $Root = Get-Item -LiteralPath $Path -Force
    if (-not $Root.PSIsContainer) { return $false }
    $Pending = New-Object 'Collections.Generic.Stack[string]'
    $Pending.Push([string]$Root.FullName)
    while ($Pending.Count -gt 0) {
        $Directory = $Pending.Pop()
        foreach ($Child in @(Get-ChildItem -LiteralPath $Directory -Force)) {
            if (($Child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $true }
            if ($Child.PSIsContainer) { $Pending.Push([string]$Child.FullName) }
        }
    }
    return $false
}

function Get-Fingerprint {
    param([string]$Path)
    if (Test-ReparseTree $Path) { throw 'reparse path' }
    if (-not (Test-Path -LiteralPath $Path)) { return 'absent' }
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return Get-Sha256File $Path }
    [string[]]$Paths = @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force | ForEach-Object { $_.FullName })
    [Array]::Sort($Paths, [StringComparer]::Ordinal)
    $Builder = New-Object Text.StringBuilder
    $Prefix = [IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    foreach ($File in $Paths) {
        if (Test-ReparseAtOrAbove $File) { throw 'reparse file' }
        $Relative = $File.Substring($Prefix.Length).Replace('\', '/')
        if ($Relative -cmatch '(^|/)__pycache__/[^/]+\.pyc$') { continue }
        [void]$Builder.Append($Relative).Append([char]0).Append((Get-Sha256File $File)).Append("`n")
    }
    return Get-Sha256Bytes $Utf8NoBom.GetBytes($Builder.ToString())
}

function ConvertTo-JsonBytes {
    param($Value)
    $Text = ($Value | ConvertTo-Json -Depth 20 -Compress) + "`n"
    return $Utf8NoBom.GetBytes($Text)
}

function Write-DurableBytes {
    param([string]$Path, [byte[]]$Bytes)
    $Parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($Parent) | Out-Null
    $Temporary = Join-Path $Parent ('.tmp-' + [Guid]::NewGuid().ToString('N'))
    $Stream = New-Object IO.FileStream(
        $Temporary,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $Stream.Write($Bytes, 0, $Bytes.Length)
        $Stream.Flush($true)
    } finally { $Stream.Dispose() }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $Backup = Join-Path $Parent ('.backup-' + [Guid]::NewGuid().ToString('N'))
        [IO.File]::Replace($Temporary, $Path, $Backup)
        if (Test-Path -LiteralPath $Backup) { [IO.File]::Delete($Backup) }
    } else {
        [IO.File]::Move($Temporary, $Path)
    }
}

function Write-DurableJson {
    param([string]$Path, $Value)
    Write-DurableBytes $Path (ConvertTo-JsonBytes $Value)
}

function Write-Event {
    param([string]$Tag, [string]$Result, [string]$Reason)
    [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
    $SafeTag = if ($Tag -cmatch '^claude-v[0-9]+\.[0-9]+\.[0-9]+$') { $Tag } else { '-' }
    $Line = '{0} target=claude tag={1} result={2} reason={3}' -f (
        [DateTimeOffset]::UtcNow.ToString('o'), $SafeTag, $Result, $Reason
    )
    [IO.File]::AppendAllText((Join-Path $StateRoot 'events.log'), $Line + "`n", $Utf8NoBom)
}

function ConvertTo-WindowsArgument {
    param([string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $Builder = New-Object Text.StringBuilder
    [void]$Builder.Append('"')
    $Backslashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') { $Backslashes++; continue }
        if ($Character -eq '"') {
            [void]$Builder.Append(('\' * (2 * $Backslashes + 1))).Append('"')
            $Backslashes = 0
            continue
        }
        if ($Backslashes) { [void]$Builder.Append(('\' * $Backslashes)); $Backslashes = 0 }
        [void]$Builder.Append($Character)
    }
    if ($Backslashes) { [void]$Builder.Append(('\' * (2 * $Backslashes))) }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Invoke-BoundedProcess {
    param([string]$FilePath, [string[]]$Arguments, [Int64]$Deadline)
    $RemainingTicks = $Deadline - [Diagnostics.Stopwatch]::GetTimestamp()
    if ($RemainingTicks -le 0) { return [pscustomobject]@{ ExitCode = -1; TimedOut = $true; Output = ''; Error = '' } }
    $Milliseconds = [Math]::Max(1, [Math]::Min([Int32]::MaxValue, [Int64]($RemainingTicks * 1000L / $StopwatchFrequency)))
    $Info = New-Object Diagnostics.ProcessStartInfo
    $Info.FileName = $FilePath
    $Info.UseShellExecute = $false
    $Info.CreateNoWindow = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $true
    $Info.Arguments = (($Arguments | ForEach-Object { ConvertTo-WindowsArgument ([string]$_) }) -join ' ')
    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $Info
    [void]$Process.Start()
    $OutputTask = $Process.StandardOutput.ReadToEndAsync()
    $ErrorTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit([int]$Milliseconds)) {
        try { $Process.Kill() } catch { }
        return [pscustomobject]@{ ExitCode = -1; TimedOut = $true; Output = ''; Error = '' }
    }
    $Output = $OutputTask.Result
    $ErrorText = $ErrorTask.Result
    if ($Output.Length -gt 1048576 -or $ErrorText.Length -gt 1048576) { throw 'process output limit exceeded' }
    return [pscustomobject]@{ ExitCode = $Process.ExitCode; TimedOut = $false; Output = $Output; Error = $ErrorText }
}

function Assert-SafeRelativePath {
    param([string]$Path)
    if (-not $Path -or $Path.Contains('\') -or [IO.Path]::IsPathRooted($Path) -or $Path.Contains(':')) { throw 'unsafe path' }
    foreach ($Part in $Path.Split('/')) { if (-not $Part -or $Part -eq '.' -or $Part -eq '..') { throw 'unsafe path' } }
}

function Assert-FileRecord {
    param($Record)
    Assert-ExactProperties $Record @('path', 'sha256', 'bytes') 'file record'
    Assert-SafeRelativePath ([string]$Record.path)
    $Leaf = [IO.Path]::GetFileName([string]$Record.path)
    if ($AllowedExtensions -notcontains [IO.Path]::GetExtension([string]$Record.path).ToLowerInvariant() -and
        $AllowedSpecialNames -cnotcontains $Leaf) { throw 'non-portable content' }
    if (-not (Test-Sha256 $Record.sha256) -or -not (Test-Integer $Record.bytes) -or $Record.bytes -lt 0 -or $Record.bytes -gt 1048576) {
        throw 'invalid file record'
    }
}

function Read-SessionArchive {
    param([string]$Path, $AssetRecord)
    if ((Get-Item -LiteralPath $Path).Length -ne [Int64]$AssetRecord.bytes -or
        (Get-Sha256File $Path) -cne [string]$AssetRecord.sha256 -or
        (Get-Item -LiteralPath $Path).Length -gt 10485760) { throw 'session asset binding differs' }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        if ($Archive.Entries.Count -gt 513) { throw 'archive entry limit exceeded' }
        $Names = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        $Folded = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        $Entries = @{}
        [Int64]$Expanded = 0
        foreach ($Entry in $Archive.Entries) {
            Assert-SafeRelativePath $Entry.FullName
            if (-not $Names.Add($Entry.FullName) -or -not $Folded.Add($Entry.FullName)) { throw 'duplicate archive path' }
            if (-not $Entry.Name) { throw 'directory archive entry' }
            $Mode = ($Entry.ExternalAttributes -shr 16) -band 0xFFFF
            if (($Mode -band 0xF000) -eq 0xA000 -or ($Mode -band 73) -ne 0) { throw 'unsafe archive mode' }
            $Expanded += $Entry.Length
            if ($Expanded -gt 8388608) { throw 'expanded size limit exceeded' }
            $Memory = New-Object IO.MemoryStream
            $Stream = $Entry.Open()
            try { $Stream.CopyTo($Memory) } finally { $Stream.Dispose() }
            $Entries[$Entry.FullName] = $Memory.ToArray()
            $Memory.Dispose()
        }
        if (-not $Entries.ContainsKey('session-tools-manifest.json')) { throw 'session manifest missing' }
        $ManifestBytes = [byte[]]$Entries['session-tools-manifest.json']
        if ((Get-Sha256Bytes $ManifestBytes) -cne [string]$AssetRecord.manifest_sha256) { throw 'session manifest binding differs' }
        $Manifest = Read-StrictJsonBytes $ManifestBytes
        Assert-ExactProperties $Manifest @('schema_version', 'target', 'release_tag', 'base_version', 'tools') 'session manifest'
        if (-not (Test-Integer $Manifest.schema_version) -or $Manifest.schema_version -ne 1 -or
            $Manifest.target -cne 'claude' -or $Manifest.release_tag -cne $script:SelectedTag -or
            $Manifest.base_version -cne $script:SelectedVersion) { throw 'session manifest identity differs' }
        $Tools = @($Manifest.tools)
        if ($Tools.Count -lt 1 -or $Tools.Count -gt 64 -or
            $AssetRecord.tool_count -ne $Tools.Count) { throw 'BLOCKED_MULTI_TOOL_ASSET' }
        $Expected = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        [void]$Expected.Add('session-tools-manifest.json')
        $PreviousTool = ''
        $TotalFiles = 0
        foreach ($Tool in $Tools) {
            Assert-ExactProperties $Tool @('id', 'files') 'tool record'
            if ($Tool.id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$' -or
                ($PreviousTool -and [StringComparer]::Ordinal.Compare($PreviousTool, [string]$Tool.id) -ge 0)) {
                throw 'invalid or unsorted tool id'
            }
            $PreviousTool = [string]$Tool.id
            $Files = @($Tool.files)
            if ($Files.Count -lt 1 -or $Files.Count -gt 512) { throw 'file count differs' }
            $Previous = ''
            foreach ($Record in $Files) {
                Assert-FileRecord $Record
                if ($Previous -and [StringComparer]::Ordinal.Compare($Previous, [string]$Record.path) -ge 0) { throw 'file records not sorted' }
                $Previous = [string]$Record.path
                $Name = 'tools/{0}/{1}' -f $Tool.id, $Record.path
                if (-not $Expected.Add($Name) -or -not $Entries.ContainsKey($Name)) { throw 'archive layout differs' }
                $Payload = [byte[]]$Entries[$Name]
                if ($Payload.Length -ne [Int64]$Record.bytes -or (Get-Sha256Bytes $Payload) -cne [string]$Record.sha256) { throw 'archive payload differs' }
                $TotalFiles++
            }
        }
        if ($TotalFiles -gt 512 -or $TotalFiles -ne $AssetRecord.file_count) { throw 'file count differs' }
        if ($Expected.Count -ne $Entries.Count) { throw 'unexpected archive entry' }
        return [pscustomobject]@{ Manifest = $Manifest; ManifestBytes = $ManifestBytes; Tools = $Tools; Entries = $Entries }
    } finally { $Archive.Dispose() }
}

function Assert-ReleaseManifest {
    param($Manifest)
    Assert-ExactProperties $Manifest @(
        'schema_version', 'target', 'version', 'tag', 'channel', 'client',
        'foundation_engine_version', 'foundation_engine_manifest_sha256', 'source',
        'asset', 'package_manifest_sha256', 'components_lock_sha256',
        'session_tools_asset', 'requires', 'acceptance_evidence_sha256',
        'promoted_from_candidate_manifest_sha256'
    ) 'release manifest'
    if (-not (Test-Integer $Manifest.schema_version) -or $Manifest.schema_version -ne 1 -or
        $Manifest.target -cne 'claude' -or $Manifest.version -cne $script:SelectedVersion -or
        $Manifest.tag -cne $script:SelectedTag -or $Manifest.channel -cne 'stable') { throw 'release identity differs' }
    Assert-ExactProperties $Manifest.client @('id', 'supported_version') 'client'
    if ($Manifest.client.id -cne 'claude-code' -or $Manifest.client.supported_version -cne '2.1.114') { throw 'client binding differs' }
    Assert-ExactProperties $Manifest.source @('repository', 'commit', 'tree', 'transformation') 'source'
    if ($Manifest.source.repository -cne $RepositoryUrl -or
        $Manifest.source.commit -cnotmatch '^[0-9a-f]{40}$' -or
        $Manifest.source.tree -cnotmatch '^[0-9a-f]{40}$' -or
        $Manifest.source.transformation -cne 'claude-native-v2') { throw 'source binding differs' }
    Assert-ExactProperties $Manifest.asset @('name', 'sha256', 'bytes') 'main asset'
    Assert-ExactProperties $Manifest.session_tools_asset @('name', 'sha256', 'bytes', 'manifest_sha256', 'tool_count', 'file_count') 'session asset'
    Assert-ExactProperties $Manifest.requires @('immutable_release', 'release_attestation', 'verification_commands') 'requires'
    if ($Manifest.requires.immutable_release -ne $true -or $Manifest.requires.release_attestation -ne $true) { throw 'immutable requirements differ' }
    foreach ($Name in @('foundation_engine_manifest_sha256', 'package_manifest_sha256', 'components_lock_sha256', 'acceptance_evidence_sha256', 'promoted_from_candidate_manifest_sha256')) {
        if (-not (Test-Sha256 $Manifest.$Name)) { throw 'release hash differs' }
    }
    foreach ($Name in @('sha256', 'manifest_sha256')) { if (-not (Test-Sha256 $Manifest.session_tools_asset.$Name)) { throw 'session hash differs' } }
    if (-not (Test-Integer $Manifest.session_tools_asset.tool_count) -or
        $Manifest.session_tools_asset.tool_count -lt 1 -or
        $Manifest.session_tools_asset.tool_count -gt 64) { throw 'BLOCKED_MULTI_TOOL_ASSET' }
    foreach ($Name in @('bytes', 'file_count')) {
        if (-not (Test-Integer $Manifest.session_tools_asset.$Name) -or $Manifest.session_tools_asset.$Name -le 0) { throw 'session count differs' }
    }
    if ($Manifest.session_tools_asset.file_count -gt 512) { throw 'session count differs' }
    if ($Manifest.session_tools_asset.name -cne "session-tools-claude-$script:SelectedVersion.zip") { throw 'session asset name differs' }
}

function Read-VerifiedState {
    $StateBytes = [IO.File]::ReadAllBytes($StatePath)
    $State = Read-StrictJsonBytes $StateBytes
    $StateFields = @(
        'schema_version', 'target', 'release_tag', 'release_version',
        'release_manifest_sha256', 'session_manifest_sha256', 'verified_at', 'tools'
    )
    if ((Test-Integer $State.schema_version) -and $State.schema_version -eq 2) {
        $StateFields += 'complete'
    }
    Assert-ExactProperties $State $StateFields 'state'
    # pwsh ConvertFrom-Json turns ISO-8601 strings into [datetime]; the raw
    # JSON value is still required to be a string holding a roundtrip stamp.
    $VerifiedAtRaw = [regex]::Match(
        $Utf8NoBom.GetString($StateBytes),
        '"verified_at":\s*"([^"]+)"'
    )
    if (-not (Test-Integer $State.schema_version) -or $State.schema_version -notin @(1, 2) -or
        $State.target -isnot [string] -or $State.target -cne 'claude' -or
        $State.release_version -isnot [string] -or
        $State.release_version -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or
        $State.release_tag -cne "claude-v$($State.release_version)" -or
        -not (Test-Sha256 $State.release_manifest_sha256) -or
        -not (Test-Sha256 $State.session_manifest_sha256) -or
        -not $VerifiedAtRaw.Success -or
        ($State.schema_version -eq 2 -and $State.complete -isnot [bool])) { throw 'BLOCKED_STATE_DRIFT' }
    try {
        [void][DateTimeOffset]::ParseExact(
            [string]$VerifiedAtRaw.Groups[1].Value,
            'o',
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    } catch { throw 'BLOCKED_STATE_DRIFT' }
    $Tools = @($State.tools)
    if ($Tools.Count -lt 1 -or $Tools.Count -gt 64) { throw 'BLOCKED_STATE_DRIFT' }
    $PreviousTool = ''
    $TotalFiles = 0
    foreach ($Owned in $Tools) {
        Assert-ExactProperties $Owned @('id', 'destination', 'ownership_marker', 'files') 'owned tool'
        $ExpectedDestination = Join-Path $SkillsRoot ([string]$Owned.id)
        if ($Owned.id -isnot [string] -or $Owned.id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$' -or
            ($PreviousTool -and [StringComparer]::Ordinal.Compare($PreviousTool, [string]$Owned.id) -ge 0) -or
            $Owned.destination -isnot [string] -or -not (Test-PathEqual $Owned.destination $ExpectedDestination) -or
            $Owned.ownership_marker -cne "session-tools-v1:claude:$($Owned.id)") { throw 'BLOCKED_STATE_DRIFT' }
        $Files = @($Owned.files)
        if ($Files.Count -lt 1 -or $Files.Count -gt 512) { throw 'BLOCKED_STATE_DRIFT' }
        $Previous = ''
        foreach ($Record in $Files) {
            Assert-FileRecord $Record
            if ($Previous -and [StringComparer]::Ordinal.Compare($Previous, [string]$Record.path) -ge 0) {
                throw 'BLOCKED_STATE_DRIFT'
            }
            $Previous = [string]$Record.path
            $TotalFiles++
        }
        if ((Get-Fingerprint $ExpectedDestination) -cne (Get-ExpectedDirectoryFingerprint $Files)) {
            throw 'BLOCKED_STATE_DRIFT'
        }
        $PreviousTool = [string]$Owned.id
    }
    if ($TotalFiles -gt 512) { throw 'BLOCKED_STATE_DRIFT' }
    return $State
}

function Assert-StateOwnership {
    param([string]$Destination, $Tool)
    if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
        $State = Read-VerifiedState
        $Owned = @($State.tools | Where-Object { [string]$_.id -ceq [string]$Tool.id })
        if ($Owned.Count -eq 1 -and (Test-PathEqual $Owned[0].destination $Destination)) {
            return
        }
    }
    if (-not (Test-Path -LiteralPath $Destination)) {
        return
    }
    if (-not (Test-Path -LiteralPath $BaselinePath -PathType Leaf) -or
        (Test-ReparseAtOrAbove $BaselinePath)) { throw 'BLOCKED_UNMANAGED_COLLISION' }
    try {
        $Baseline = Read-StrictJsonFile $BaselinePath
        Assert-ExactProperties $Baseline @('schema_version', 'target', 'release_tag', 'base_version', 'tools') 'baseline'
        if (-not (Test-Integer $Baseline.schema_version) -or $Baseline.schema_version -ne 1 -or
            $Baseline.target -cne 'claude' -or $Baseline.base_version -isnot [string] -or
            $Baseline.base_version -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or
            $Baseline.release_tag -cne "claude-v$($Baseline.base_version)") { throw 'baseline identity differs' }
        if ([version]([string]$Baseline.base_version) -gt
            [version]([string]$script:SelectedVersion)) {
            throw 'BLOCKED_NO_DOWNGRADE'
        }
        $BaselineTool = @($Baseline.tools | Where-Object {
            [string]$_.id -ceq [string]$Tool.id
        })
        if ($BaselineTool.Count -ne 1) { throw 'baseline tool differs' }
        Assert-ExactProperties $BaselineTool[0] @('id', 'files') 'baseline tool'
        if ($BaselineTool[0].id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$') { throw 'baseline tool differs' }
        $BaselineFiles = @($BaselineTool[0].files)
        if ($BaselineFiles.Count -lt 1 -or $BaselineFiles.Count -gt 512) { throw 'baseline files differ' }
        $Previous = ''
        foreach ($Record in $BaselineFiles) {
            Assert-FileRecord $Record
            if ($Previous -and [StringComparer]::Ordinal.Compare($Previous, [string]$Record.path) -ge 0) {
                throw 'baseline files not sorted'
            }
            $Previous = [string]$Record.path
        }
        if ((Get-Fingerprint $Destination) -cne (Get-ExpectedDirectoryFingerprint $BaselineFiles)) {
            throw 'baseline fingerprint differs'
        }
    } catch {
        if ($_.Exception.Message -eq 'BLOCKED_NO_DOWNGRADE') { throw }
        throw 'BLOCKED_UNMANAGED_COLLISION'
    }
}

function Get-ExpectedDirectoryFingerprint {
    param($Files)
    $Builder = New-Object Text.StringBuilder
    foreach ($Record in @($Files)) {
        [void]$Builder.Append([string]$Record.path).Append([char]0).Append([string]$Record.sha256).Append("`n")
    }
    return Get-Sha256Bytes $Utf8NoBom.GetBytes($Builder.ToString())
}

function Test-PathEqual {
    param([string]$Left, [string]$Right)
    return [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFullPath($Left), [IO.Path]::GetFullPath($Right))
}

function Assert-JournalShape {
    param($Journal)
    Assert-ExactProperties $Journal @(
        'schema_version', 'target', 'transaction_id', 'phase', 'receipt_sha256',
        'start_tick', 'mutation_cutoff_tick', 'kill_tick', 'hard_deadline_tick',
        'stopwatch_frequency', 'previous_destination_sha256', 'previous_state_sha256',
        'expected_staging_sha256', 'expected_destination_sha256', 'expected_state_sha256',
        'staging_path', 'previous_path', 'destination_path', 'state_path', 'operations'
    ) 'journal'
    $Phases = @(
        'created', 'staged', 'move_destination_intent', 'move_destination_applied',
        'move_staging_intent', 'move_staging_applied', 'state_write_intent',
        'state_write_applied', 'committed'
    )
    if (-not (Test-Integer $Journal.schema_version) -or $Journal.schema_version -ne 1 -or
        $Journal.target -isnot [string] -or $Journal.target -cne 'claude' -or
        -not [Guid]::TryParseExact([string]$Journal.transaction_id, 'D', [ref]([Guid]::Empty)) -or
        $Journal.transaction_id -cne ([Guid]$Journal.transaction_id).ToString('D') -or
        $Journal.phase -isnot [string] -or $Phases -cnotcontains $Journal.phase -or
        -not (Test-Integer $Journal.start_tick) -or
        -not (Test-Integer $Journal.mutation_cutoff_tick) -or
        -not (Test-Integer $Journal.kill_tick) -or
        -not (Test-Integer $Journal.hard_deadline_tick) -or
        -not (Test-Integer $Journal.stopwatch_frequency) -or
        -not (Test-ExactTickContract ([Int64]$Journal.start_tick) ([Int64]$Journal.mutation_cutoff_tick) ([Int64]$Journal.kill_tick) ([Int64]$Journal.hard_deadline_tick) ([Int64]$Journal.stopwatch_frequency)) -or
        [Int64]$Journal.hard_deadline_tick -gt $HardDeadlineTick -or
        -not (Test-Sha256 $Journal.receipt_sha256)) { throw 'unsafe journal' }
    foreach ($Name in @(
        'previous_destination_sha256', 'previous_state_sha256', 'expected_staging_sha256',
        'expected_destination_sha256', 'expected_state_sha256'
    )) {
        if ($Journal.$Name -cne 'absent' -and -not (Test-Sha256 $Journal.$Name)) { throw 'unsafe journal hash' }
    }
    $OperationNames = @('move_destination_to_previous', 'move_staging_to_destination', 'write_state')
    Assert-ExactProperties $Journal.operations $OperationNames 'journal operations'
    $ActualFlags = New-Object 'Collections.Generic.List[bool]'
    foreach ($Name in $OperationNames) {
        $Operation = $Journal.operations.$Name
        Assert-ExactProperties $Operation @('intent', 'applied') 'journal operation'
        if ($Operation.intent -isnot [bool] -or $Operation.applied -isnot [bool] -or
            ($Operation.applied -and -not $Operation.intent)) { throw 'unsafe journal operation' }
        $ActualFlags.Add([bool]$Operation.intent)
        $ActualFlags.Add([bool]$Operation.applied)
    }
    [bool[]]$ExpectedFlags = @($false, $false, $false, $false, $false, $false)
    $Enabled = [Array]::IndexOf($Phases, [string]$Journal.phase)
    if ($Enabled -ge 2) {
        $Transition = $Enabled - 2
        for ($Index = 0; $Index -le $Transition -and $Index -lt $ExpectedFlags.Count; $Index++) {
            $ExpectedFlags[$Index] = $true
        }
    }
    if ($Journal.phase -ceq 'committed') {
        for ($Index = 0; $Index -lt $ExpectedFlags.Count; $Index++) { $ExpectedFlags[$Index] = $true }
    }
    for ($Index = 0; $Index -lt $ExpectedFlags.Count; $Index++) {
        if ($ActualFlags[$Index] -ne $ExpectedFlags[$Index]) { throw 'unsafe journal transition' }
    }
    $TransactionRoot = Join-Path (Join-Path $StateRoot 'transactions') ([string]$Journal.transaction_id)
    if (-not (Test-PathEqual $Journal.staging_path (Join-Path $TransactionRoot 'staging')) -or
        -not (Test-PathEqual $Journal.previous_path (Join-Path $TransactionRoot 'previous')) -or
        -not (Test-PathEqual $Journal.state_path $StatePath) -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath([string]$Journal.destination_path)), [IO.Path]::GetFullPath($SkillsRoot))) {
        throw 'unsafe journal path'
    }
    foreach ($Path in @($Journal.staging_path, $Journal.previous_path, $Journal.destination_path, $Journal.state_path)) {
        if (Test-ReparseAtOrAbove $Path) { throw 'unsafe journal reparse path' }
    }
}

function Test-JournalLayout {
    param(
        [int]$Step,
        [string]$DestinationNow,
        [string]$PreviousNow,
        [string]$StagingNow,
        [string]$StateNow,
        [string]$OldDestination,
        [string]$ExpectedStaging,
        [string]$NewDestination,
        [string]$OldState,
        [string]$NewState
    )
    $DestinationExpected = if ($Step -ge 2) { $NewDestination } elseif ($Step -ge 1) { 'absent' } else { $OldDestination }
    $PreviousExpected = if ($Step -ge 1) { $OldDestination } else { 'absent' }
    $StagingExpected = if ($Step -ge 2) { 'absent' } else { $ExpectedStaging }
    $StateExpected = if ($Step -ge 3) { $NewState } else { $OldState }
    return (
        $DestinationNow -ceq $DestinationExpected -and
        $PreviousNow -ceq $PreviousExpected -and
        $StagingNow -ceq $StagingExpected -and
        $StateNow -ceq $StateExpected
    )
}

function Remove-JournalEntry {
    param([string]$Path)
    if (Test-ReparseTree $Path) { throw 'reparse path' }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    } elseif (Test-Path -LiteralPath $Path -PathType Leaf) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Remove-JournalDirectory {
    param([string]$Path)
    if (Test-ReparseTree $Path) { throw 'reparse path' }
    if (Test-Path -LiteralPath $Path -PathType Leaf) { throw 'directory path is a file' }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Assert-BeforeHardDeadline {
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $HardDeadlineTick) {
        throw 'SKIPPED_DEADLINE'
    }
}

function Invoke-JournalRecovery {
    if (-not (Test-Path -LiteralPath $JournalPath -PathType Leaf)) { return $true }
    try {
        Assert-BeforeHardDeadline
        $Journal = Read-StrictJsonFile $JournalPath
        Assert-JournalShape $Journal
        if ((Get-Sha256File $ReceiptPath) -cne [string]$Journal.receipt_sha256) { throw 'receipt differs' }
        $DestinationNow = Get-Fingerprint ([string]$Journal.destination_path)
        $PreviousNow = Get-Fingerprint ([string]$Journal.previous_path)
        $StagingNow = Get-Fingerprint ([string]$Journal.staging_path)
        $StateNow = Get-Fingerprint ([string]$Journal.state_path)
        $OldDestination = [string]$Journal.previous_destination_sha256
        $ExpectedStaging = [string]$Journal.expected_staging_sha256
        $NewDestination = [string]$Journal.expected_destination_sha256
        $OldState = [string]$Journal.previous_state_sha256
        $NewState = [string]$Journal.expected_state_sha256
        $ActualStep = -1
        if ($Journal.phase -ceq 'created') {
            if ($DestinationNow -cne $OldDestination -or $PreviousNow -cne 'absent' -or
                $StateNow -cne $OldState) { throw 'created journal layout differs' }
            if ($StagingNow -cne 'absent' -and
                -not (Test-Path -LiteralPath ([string]$Journal.staging_path) -PathType Container)) {
                throw 'created staging is not a directory'
            }
            $ActualStep = 0
        } else {
            $DurableStep = if ([bool]$Journal.operations.write_state.applied) { 3 } elseif (
                [bool]$Journal.operations.move_staging_to_destination.applied
            ) { 2 } elseif ([bool]$Journal.operations.move_destination_to_previous.applied) { 1 } else { 0 }
            $MaximumStep = if ([string]$Journal.phase -clike '*_intent') { $DurableStep + 1 } else { $DurableStep }
            for ($Candidate = $MaximumStep; $Candidate -ge $DurableStep; $Candidate--) {
                if (Test-JournalLayout $Candidate $DestinationNow $PreviousNow $StagingNow $StateNow `
                    $OldDestination $ExpectedStaging $NewDestination $OldState $NewState) {
                    $ActualStep = $Candidate
                    break
                }
            }
        }
        if ($ActualStep -lt 0) { throw 'journal layout differs' }
        if ($ActualStep -eq 3) {
            if ($PreviousNow -ne 'absent') {
                Assert-BeforeHardDeadline
                Remove-JournalEntry ([string]$Journal.previous_path)
            }
            if ($StagingNow -ne 'absent') {
                Assert-BeforeHardDeadline
                Remove-JournalEntry ([string]$Journal.staging_path)
            }
        } else {
            if ($ActualStep -ge 2) {
                Assert-BeforeHardDeadline
                Remove-JournalEntry ([string]$Journal.destination_path)
            }
            if ($ActualStep -ge 1 -and $OldDestination -cne 'absent') {
                Assert-BeforeHardDeadline
                Move-Item -LiteralPath $Journal.previous_path -Destination $Journal.destination_path
            }
            if ($StagingNow -ne 'absent') {
                Assert-BeforeHardDeadline
                if ($Journal.phase -ceq 'created') {
                    Remove-JournalDirectory ([string]$Journal.staging_path)
                } else {
                    Remove-JournalEntry ([string]$Journal.staging_path)
                }
            }
        }
        if ((Get-Fingerprint ([string]$Journal.destination_path)) -cne $(if ($ActualStep -eq 3) { $NewDestination } else { $OldDestination }) -or
            (Get-Fingerprint ([string]$Journal.state_path)) -cne $(if ($ActualStep -eq 3) { $NewState } else { $OldState }) -or
            (Get-Fingerprint ([string]$Journal.previous_path)) -cne 'absent' -or
            (Get-Fingerprint ([string]$Journal.staging_path)) -cne 'absent') { throw 'recovery fingerprint differs' }
        $TransactionRoot = Split-Path -Parent ([string]$Journal.staging_path)
        if (Test-Path -LiteralPath $TransactionRoot) {
            Assert-BeforeHardDeadline
            if (Test-ReparseTree $TransactionRoot) { throw 'reparse path' }
            try { Remove-Item -LiteralPath $TransactionRoot -Force -ErrorAction Stop } catch { }
        }
        Assert-BeforeHardDeadline
        Remove-Item -LiteralPath $JournalPath -Force
        return $true
    } catch {
        return $false
    }
}

function Set-JournalPhase {
    param($Journal, [string]$Phase, [string]$Operation, [string]$Flag)
    $Journal.phase = $Phase
    if ($Operation) { $Journal.operations.$Operation.$Flag = $true }
    Write-DurableJson $JournalPath $Journal
}

function New-OwnedToolRecord {
    param($Tool)
    $Destination = Join-Path $SkillsRoot ([string]$Tool.id)
    return [ordered]@{
        id = [string]$Tool.id
        destination = [IO.Path]::GetFullPath($Destination)
        ownership_marker = "session-tools-v1:claude:$($Tool.id)"
        files = @($Tool.files | ForEach-Object {
            [ordered]@{
                path = [string]$_.path
                sha256 = [string]$_.sha256
                bytes = [Int64]$_.bytes
            }
        })
    }
}

function Test-ToolMatches {
    param($Owned, $Tool)
    if ($null -eq $Owned -or [string]$Owned.id -cne [string]$Tool.id) {
        return $false
    }
    return (Get-ExpectedDirectoryFingerprint $Owned.files) -ceq
        (Get-ExpectedDirectoryFingerprint $Tool.files)
}

function Get-SortedOwnedTools {
    param($OwnedById)
    return @(
        $OwnedById.Keys |
            Sort-Object -CaseSensitive |
            ForEach-Object { $OwnedById[$_] }
    )
}

function Apply-VerifiedTool {
    param(
        $ArchiveData,
        $Tool,
        [byte[]]$ReleaseManifestBytes,
        [object[]]$NextTools,
        [bool]$Complete
    )
    $Destination = Join-Path $SkillsRoot ([string]$Tool.id)
    if (Test-ReparseAtOrAbove $Destination) { throw 'BLOCKED_UNMANAGED_COLLISION' }
    Assert-StateOwnership $Destination $Tool
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $MutationCutoffTick) { throw 'SKIPPED_DEADLINE' }
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf) -or (Test-ReparseAtOrAbove $ReceiptPath)) { throw 'BLOCKED_RECEIPT_REQUIRED' }
    $TransactionRoot = Join-Path (Join-Path $StateRoot 'transactions') $TransactionId
    $Staging = Join-Path $TransactionRoot 'staging'
    $Previous = Join-Path $TransactionRoot 'previous'
    $ExpectedDirectory = Get-ExpectedDirectoryFingerprint $Tool.files
    $State = [ordered]@{
        schema_version = 2
        target = 'claude'
        release_tag = $script:SelectedTag
        release_version = $script:SelectedVersion
        release_manifest_sha256 = Get-Sha256Bytes $ReleaseManifestBytes
        session_manifest_sha256 = Get-Sha256Bytes ([byte[]]$ArchiveData.ManifestBytes)
        verified_at = [DateTimeOffset]::UtcNow.ToString('o')
        tools = @($NextTools)
        complete = $Complete
    }
    $StateBytes = ConvertTo-JsonBytes $State
    $PreviousDestination = Get-Fingerprint $Destination
    $PreviousState = Get-Fingerprint $StatePath
    $Operations = [ordered]@{
        move_destination_to_previous = [ordered]@{ intent = $false; applied = $false }
        move_staging_to_destination = [ordered]@{ intent = $false; applied = $false }
        write_state = [ordered]@{ intent = $false; applied = $false }
    }
    $Journal = [ordered]@{
        schema_version = 1; target = 'claude'; transaction_id = $TransactionId; phase = 'created'
        receipt_sha256 = Get-Sha256File $ReceiptPath
        start_tick = $StartTick; mutation_cutoff_tick = $MutationCutoffTick; kill_tick = $KillTick
        hard_deadline_tick = $HardDeadlineTick; stopwatch_frequency = $StopwatchFrequency
        previous_destination_sha256 = $PreviousDestination; previous_state_sha256 = $PreviousState
        expected_staging_sha256 = $ExpectedDirectory; expected_destination_sha256 = $ExpectedDirectory
        expected_state_sha256 = Get-Sha256Bytes $StateBytes
        staging_path = [IO.Path]::GetFullPath($Staging); previous_path = [IO.Path]::GetFullPath($Previous)
        destination_path = [IO.Path]::GetFullPath($Destination); state_path = [IO.Path]::GetFullPath($StatePath)
        operations = $Operations
    }
    Write-DurableJson $JournalPath $Journal
    try {
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $MutationCutoffTick) { throw 'SKIPPED_DEADLINE' }
        [IO.Directory]::CreateDirectory($Staging) | Out-Null
        foreach ($Record in @($Tool.files)) {
            $Relative = ([string]$Record.path).Replace('/', '\')
            $File = Join-Path $Staging $Relative
            [IO.Directory]::CreateDirectory((Split-Path -Parent $File)) | Out-Null
            [IO.File]::WriteAllBytes($File, [byte[]]$ArchiveData.Entries["tools/$($Tool.id)/$($Record.path)"])
        }
        if ((Get-Fingerprint $Staging) -cne $ExpectedDirectory) { throw 'staging differs' }
        Set-JournalPhase $Journal 'staged' '' ''
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $MutationCutoffTick) { throw 'SKIPPED_DEADLINE' }
        Set-JournalPhase $Journal 'move_destination_intent' 'move_destination_to_previous' 'intent'
        if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination $Previous }
        Set-JournalPhase $Journal 'move_destination_applied' 'move_destination_to_previous' 'applied'
        Set-JournalPhase $Journal 'move_staging_intent' 'move_staging_to_destination' 'intent'
        [IO.Directory]::CreateDirectory($SkillsRoot) | Out-Null
        Move-Item -LiteralPath $Staging -Destination $Destination
        Set-JournalPhase $Journal 'move_staging_applied' 'move_staging_to_destination' 'applied'
        Set-JournalPhase $Journal 'state_write_intent' 'write_state' 'intent'
        Write-DurableBytes $StatePath $StateBytes
        Set-JournalPhase $Journal 'state_write_applied' 'write_state' 'applied'
        Set-JournalPhase $Journal 'committed' '' ''
        if ((Get-Fingerprint $Destination) -cne $ExpectedDirectory -or (Get-Fingerprint $StatePath) -cne $Journal.expected_state_sha256) { throw 'committed fingerprints differ' }
        Assert-BeforeHardDeadline
        if (Test-Path -LiteralPath $Previous) { Remove-JournalEntry $Previous }
        Assert-BeforeHardDeadline
        if (Test-Path -LiteralPath $TransactionRoot) {
            if (Test-ReparseTree $TransactionRoot) { throw 'reparse path' }
            Remove-Item -LiteralPath $TransactionRoot -Force
        }
        Assert-BeforeHardDeadline
        Remove-Item -LiteralPath $JournalPath -Force
    } catch {
        if ([Diagnostics.Stopwatch]::GetTimestamp() -lt $KillTick) { [void](Invoke-JournalRecovery) }
        throw
    }
}

$Lock = $null
try {
    [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
    $LockDeadline = [Math]::Min($MutationCutoffTick, [Diagnostics.Stopwatch]::GetTimestamp() + 2L * $StopwatchFrequency)
    while ($null -eq $Lock -and [Diagnostics.Stopwatch]::GetTimestamp() -lt $LockDeadline) {
        try {
            $Lock = New-Object IO.FileStream($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch [IO.IOException] { Start-Sleep -Milliseconds 100 }
    }
    if ($null -eq $Lock) { Write-Event '-' 'SKIPPED_LOCK_BUSY' 'lock-busy'; exit 0 }
    if (-not (Invoke-JournalRecovery)) {
        Write-Event '-' 'BLOCKED_SESSION_RECOVERY' 'journal-invalid'
        if ($ManagedPreflight) { [Console]::Error.WriteLine('BLOCKED_SESSION_RECOVERY'); exit 65 }
        exit 0
    }
    $GhCommand = Get-Command gh.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $GhCommand) { Write-Event '-' 'BLOCKED_GH_REQUIRED' 'gh-missing'; exit 0 }
    $Gh = [string]$GhCommand.Source
    $List = Invoke-BoundedProcess $Gh @('release', 'list', '--repo', $Repository, '--limit', '20', '--json', 'tagName,isDraft,isPrerelease,isImmutable,publishedAt') $MutationCutoffTick
    if ($List.TimedOut -or $List.ExitCode -ne 0) { Write-Event '-' 'SKIPPED_OFFLINE' 'release-list-failed'; exit 0 }
    try {
        $HasIllegalJsonWhitespace = $false
        foreach ($JsonCharacter in ([string]$List.Output).ToCharArray()) {
            $JsonCodePoint = [int][char]$JsonCharacter
            if ($JsonCodePoint -in @(0x000B, 0x000C, 0x0085, 0x00A0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000) -or
                ($JsonCodePoint -ge 0x2000 -and $JsonCodePoint -le 0x200A)) {
                $HasIllegalJsonWhitespace = $true
                break
            }
        }
        if ($HasIllegalJsonWhitespace) {
            Write-Event '-' 'REJECTED_RELEASE_LIST' 'non-rfc-json-whitespace'
            exit 0
        }
        [Foundation.SessionTools.StrictJsonGuard]::Validate([string]$List.Output)
        $Releases = @(([string]$List.Output | ConvertFrom-Json))
        $Stable = @()
        foreach ($Release in $Releases) {
            Assert-ExactProperties $Release @('tagName', 'isDraft', 'isPrerelease', 'isImmutable', 'publishedAt') 'release list record'
            if ($Release.isDraft -isnot [bool] -or $Release.isPrerelease -isnot [bool] -or
                $Release.isImmutable -isnot [bool]) { throw 'release list record differs' }
            if ($Release.isDraft -or $Release.isPrerelease) { continue }
            if ($Release.tagName -cnotmatch '^claude-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw 'release list record differs' }
            if (-not $Release.isImmutable) { throw 'release is mutable' }
            $Stable += $Release
        }
        if ($Stable.Count -eq 0) { Write-Event '-' 'NO_STABLE_RELEASE' 'no-stable'; exit 0 }
        $Selected = $Stable | Sort-Object { [version](($_.tagName) -replace '^claude-v', '') } -Descending | Select-Object -First 1
        $script:SelectedTag = [string]$Selected.tagName
        $script:SelectedVersion = $script:SelectedTag -replace '^claude-v', ''
        $script:CurrentState = $null
        if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
            try {
                $Current = Read-VerifiedState
                $script:CurrentState = $Current
                if ([version]$script:SelectedVersion -lt [version]([string]$Current.release_version)) {
                    Write-Event $script:SelectedTag 'NO_UPDATE' 'non-monotonic'
                    exit 0
                }
                $CurrentComplete = $Current.schema_version -eq 1 -or
                    [bool]$Current.complete
                if ($Current.release_tag -ceq $script:SelectedTag -and
                    $CurrentComplete) {
                    Write-Event $script:SelectedTag 'NO_UPDATE' 'same-tag'
                    exit 0
                }
            } catch {
                Write-Event $script:SelectedTag 'BLOCKED_STATE_DRIFT' 'state-invalid'
                exit 0
            }
        }
    } catch {
        Write-Event '-' 'REJECTED_RELEASE_LIST' 'strict-json'
        exit 0
    }
    $Verify = Invoke-BoundedProcess $Gh @('release', 'verify', $script:SelectedTag, '--repo', $Repository) $MutationCutoffTick
    if ($Verify.TimedOut -or $Verify.ExitCode -ne 0) { Write-Event $script:SelectedTag 'REJECTED_VERIFICATION' 'release-verify'; exit 0 }
    if (Test-ReparseTree $DownloadsPath) { Write-Event $script:SelectedTag 'REJECTED_PATH' 'download-reparse'; exit 0 }
    if (Test-Path -LiteralPath $DownloadsPath) { Remove-Item -LiteralPath $DownloadsPath -Recurse -Force }
    [IO.Directory]::CreateDirectory($DownloadsPath) | Out-Null
    $DownloadManifest = Invoke-BoundedProcess $Gh @('release', 'download', $script:SelectedTag, '--repo', $Repository, '--pattern', 'release-manifest.json', '--dir', $DownloadsPath) $MutationCutoffTick
    $ReleaseManifestPath = Join-Path $DownloadsPath 'release-manifest.json'
    if ($DownloadManifest.TimedOut -or $DownloadManifest.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $ReleaseManifestPath -PathType Leaf)) { Write-Event $script:SelectedTag 'REJECTED_DOWNLOAD' 'manifest-download'; exit 0 }
    $VerifyManifest = Invoke-BoundedProcess $Gh @('release', 'verify-asset', $script:SelectedTag, $ReleaseManifestPath, '--repo', $Repository) $MutationCutoffTick
    $AttestManifest = Invoke-BoundedProcess $Gh @('attestation', 'verify', $ReleaseManifestPath, '--repo', $Repository) $MutationCutoffTick
    if ($VerifyManifest.TimedOut -or $AttestManifest.TimedOut -or $VerifyManifest.ExitCode -ne 0 -or $AttestManifest.ExitCode -ne 0) { Write-Event $script:SelectedTag 'REJECTED_VERIFICATION' 'manifest-attestation'; exit 0 }
    try {
        $ReleaseManifestBytes = [IO.File]::ReadAllBytes($ReleaseManifestPath)
        $ReleaseManifest = Read-StrictJsonBytes $ReleaseManifestBytes
        Assert-ReleaseManifest $ReleaseManifest
    } catch {
        $ManifestCode = if ($_.Exception.Message -eq 'BLOCKED_MULTI_TOOL_ASSET') { 'BLOCKED_MULTI_TOOL_ASSET' } else { 'REJECTED_MANIFEST' }
        Write-Event $script:SelectedTag $ManifestCode 'strict-manifest'
        exit 0
    }
    $AssetName = [string]$ReleaseManifest.session_tools_asset.name
    $DownloadAsset = Invoke-BoundedProcess $Gh @('release', 'download', $script:SelectedTag, '--repo', $Repository, '--pattern', $AssetName, '--dir', $DownloadsPath) $MutationCutoffTick
    $AssetPath = Join-Path $DownloadsPath $AssetName
    if ($DownloadAsset.TimedOut -or $DownloadAsset.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $AssetPath -PathType Leaf)) { Write-Event $script:SelectedTag 'REJECTED_DOWNLOAD' 'asset-download'; exit 0 }
    $VerifyAsset = Invoke-BoundedProcess $Gh @('release', 'verify-asset', $script:SelectedTag, $AssetPath, '--repo', $Repository) $MutationCutoffTick
    $AttestAsset = Invoke-BoundedProcess $Gh @('attestation', 'verify', $AssetPath, '--repo', $Repository) $MutationCutoffTick
    if ($VerifyAsset.TimedOut -or $AttestAsset.TimedOut -or $VerifyAsset.ExitCode -ne 0 -or $AttestAsset.ExitCode -ne 0) { Write-Event $script:SelectedTag 'REJECTED_VERIFICATION' 'asset-attestation'; exit 0 }
    try {
        $ReleaseManifestBytesAfterVerification = [IO.File]::ReadAllBytes($ReleaseManifestPath)
        if ((Get-Sha256Bytes $ReleaseManifestBytesAfterVerification) -cne
            (Get-Sha256Bytes $ReleaseManifestBytes)) {
            throw 'verified manifest bytes changed'
        }
        $ReleaseManifestBytes = $ReleaseManifestBytesAfterVerification
        $ArchiveData = Read-SessionArchive $AssetPath $ReleaseManifest.session_tools_asset
        $OwnedById = @{}
        if ($null -ne $script:CurrentState) {
            foreach ($Owned in @($script:CurrentState.tools)) {
                $OwnedById[[string]$Owned.id] = $Owned
            }
        }
        $Pending = @()
        foreach ($Tool in @($ArchiveData.Tools)) {
            $Owned = if ($OwnedById.ContainsKey([string]$Tool.id)) {
                $OwnedById[[string]$Tool.id]
            } else { $null }
            if (-not (Test-ToolMatches $Owned $Tool)) { $Pending += $Tool }
        }
        if ($Pending.Count -eq 0 -and $null -ne $script:CurrentState -and
            $script:CurrentState.schema_version -eq 2 -and
            -not [bool]$script:CurrentState.complete) {
            $Pending = @($ArchiveData.Tools | Select-Object -Last 1)
        }
        for ($Index = 0; $Index -lt $Pending.Count; $Index++) {
            $Tool = $Pending[$Index]
            $OwnedById[[string]$Tool.id] = New-OwnedToolRecord $Tool
            $Complete = $Index -eq ($Pending.Count - 1)
            if ($Complete) {
                foreach ($ExpectedTool in @($ArchiveData.Tools)) {
                    if (-not $OwnedById.ContainsKey([string]$ExpectedTool.id) -or
                        -not (Test-ToolMatches $OwnedById[[string]$ExpectedTool.id] $ExpectedTool)) {
                        $Complete = $false
                        break
                    }
                }
            }
            Apply-VerifiedTool `
                $ArchiveData `
                $Tool `
                $ReleaseManifestBytes `
                (Get-SortedOwnedTools $OwnedById) `
                $Complete
        }
    } catch {
        $Code = [string]$_.Exception.Message
        if ($Code -ceq 'verified manifest bytes changed') { $Code = 'REJECTED_VERIFICATION' }
        if ($Code -notlike 'BLOCKED_*' -and $Code -notlike 'SKIPPED_*' -and $Code -notlike 'REJECTED_*') { $Code = 'REJECTED_ASSET' }
        Write-Event $script:SelectedTag $Code 'apply-rejected'
        exit 0
    }
    if ($Pending.Count -gt 0) {
        Write-Event $script:SelectedTag 'APPLIED' 'verified-snapshot'
        if ($HookFallback) { 'TOOLS_APPLIED_NEXT_SESSION' }
    } else {
        Write-Event $script:SelectedTag 'NO_UPDATE' 'verified-snapshot'
    }
    exit 0
} catch {
    if ($_.Exception.GetType().Name -ceq 'PropertyNotFoundException') {
        Write-Event '-' 'REJECTED_RELEASE_LIST' 'malformed-release-list'
    } else {
        Write-Event '-' 'SKIPPED_INTERNAL_ERROR' 'fail-open'
    }
    if ($ManagedPreflight -and (Test-Path -LiteralPath $JournalPath -PathType Leaf)) {
        [Console]::Error.WriteLine('BLOCKED_SESSION_RECOVERY')
        exit 65
    }
    exit 0
} finally {
    if ($null -ne $Lock) { $Lock.Dispose() }
}
