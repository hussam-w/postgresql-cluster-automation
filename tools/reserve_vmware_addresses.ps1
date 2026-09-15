# This helper produces a reviewable candidate only; it never edits VMware or restarts DHCP.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Settings
)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Settings -Raw | ConvertFrom-Json
$original = Get-Content -LiteralPath $Source -Raw
if ((Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash -ne $config.expected_source_sha256) {
    throw 'Source fingerprint differs from the reviewed DHCP configuration.'
}
if (Test-Path -LiteralPath $Output) { throw 'Output exists; preserve it and choose a new candidate path.' }
if ([string]::IsNullOrWhiteSpace($config.old_range_statement) -or [string]::IsNullOrWhiteSpace($config.replacement_range_statements)) {
    throw 'Supply the exact old range statement and reviewed replacement ranges excluding reservations.'
}
$pattern = [regex]::Escape($config.old_range_statement)
if ([regex]::Matches($original, $pattern).Count -ne 1) { throw 'Expected exactly one matching DHCP range.' }
if ($original.Contains('# BEGIN PG HA RESERVED ADDRESSES')) { throw 'Existing managed reservations require manual reconciliation.' }
$candidate = $original.Replace($config.old_range_statement, $config.replacement_range_statements)
$candidate += "`r`n# BEGIN PG HA RESERVED ADDRESSES`r`n"
if (@($config.reservations).Count -eq 0) { throw 'Explicit reservations are required.' }
$names = @{}
$addresses = @{}
$macs = @{}
foreach ($binding in $config.reservations) {
    if ($binding.name -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]*$' -or $binding.mac -notmatch '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$') { throw 'Invalid reservation name or MAC.' }
    $address = [System.Net.IPAddress]::Parse($binding.ip)
    if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'IPv4 is required.' }
    if ($names.ContainsKey($binding.name) -or $addresses.ContainsKey($binding.ip) -or $macs.ContainsKey($binding.mac)) { throw 'Duplicate reservation identity.' }
    $names[$binding.name] = $true
    $addresses[$binding.ip] = $true
    $macs[$binding.mac] = $true
    $candidate += "host pg-ha-$($binding.name) {`r`n hardware ethernet $($binding.mac);`r`n fixed-address $address;`r`n}`r`n"
}
$candidate += "# END PG HA RESERVED ADDRESSES`r`n"
# Exclusive creation also prevents a race from overwriting an existing candidate.
$stream = [System.IO.File]::Open($Output, [System.IO.FileMode]::CreateNew)
try {
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($candidate)
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
Write-Output 'Candidate created. Validate pool exclusions, subnet placement, existing bindings and DHCP syntax before separately approved installation.'
