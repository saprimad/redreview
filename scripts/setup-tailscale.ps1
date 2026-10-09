# Run in an Administrator PowerShell session on the Windows host.
# Starts RedReview in WSL, verifies HTTP, then configures Tailscale-only forwarding.
[CmdletBinding()]
param([string]$Distribution = '', [string]$TailscaleIP = '', [string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$Port = 8844
if (-not $ProjectRoot) { throw 'Pass -ProjectRoot with your WSL checkout path.' }
if (-not $TailscaleIP) { $TailscaleIP = (& tailscale.exe ip -4 | Select-Object -First 1).Trim() }
if (-not $TailscaleIP) { throw 'Pass -TailscaleIP or connect Tailscale first.' }
$RuleName = 'RedReview-Tailscale-8844'
$GroupName = 'RedReview'
$WslArgs = @()
if ($Distribution) { $WslArgs = @('--distribution', $Distribution) }

function Invoke-WslCommand {
    param([string[]]$Arguments)
    $result = & wsl.exe @WslArgs --exec @Arguments
    if ($LASTEXITCODE -ne 0) { throw "WSL command failed (exit $LASTEXITCODE). Check the distribution and project path." }
    return $result
}
function Start-RedReview {
    param([string]$BindAddress)
    Invoke-WslCommand -Arguments @('python3', "$ProjectRoot/scripts/start-tailscale.py", '--bind', $BindAddress, '--allow-host', "${TailscaleIP}:$Port", '--restart') | Write-Host
}
function Test-RedReview {
    param([string]$Address)
    try {
        $uri = "http://${Address}:$Port/api/health"
        $request = [System.Net.WebRequest]::Create($uri)
        $request.Proxy = $null
        $request.Timeout = 5000
        $response = $request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try { $body = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
            return [int]$response.StatusCode -eq 200 -and $body.app -eq 'redreview'
        } finally { $response.Dispose() }
    } catch { return $false }
}
function Invoke-Netsh {
    param([string[]]$Arguments)
    & netsh.exe @Arguments | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "netsh failed (exit $LASTEXITCODE); forwarding was not verified." }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an Administrator PowerShell session. No browser is needed.'
}
$address = @(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $TailscaleIP -ErrorAction SilentlyContinue)
if ($address.Count -ne 1) { throw "Windows does not currently own $TailscaleIP. Connect Tailscale and verify the host IP." }
$adapter = Get-NetAdapter -IncludeHidden | Where-Object { $_.ifIndex -eq $address[0].InterfaceIndex } | Select-Object -First 1
if ($adapter.InterfaceDescription -notmatch 'Tailscale' -and $adapter.Name -notmatch 'Tailscale') {
    throw "$TailscaleIP is not assigned to a recognised Tailscale adapter; no firewall change was made."
}
if (@(Get-NetFirewallProfile -PolicyStore ActiveStore | Where-Object { $_.Enabled -ne 'True' -or $_.DefaultInboundAction -eq 'Allow' }).Count) {
    throw 'Windows Firewall must be enabled with default inbound blocking before this Tailscale-only rule can be applied. Existing global policy was not changed.'
}
$priorRule = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($priorRule -and $priorRule.Group -ne $GroupName) { throw "Firewall rule name conflict: $RuleName" }

Write-Host 'Current portproxy configuration:'
Invoke-Netsh -Arguments @('interface','portproxy','show','v4tov4')
$registry = 'HKLM:\SYSTEM\CurrentControlSet\Services\PortProxy\v4tov4\tcp'
$entryName = "$TailscaleIP/$Port"
$oldTarget = $null
if (Test-Path $registry) {
    $oldTarget = (Get-ItemProperty -Path $registry).PSObject.Properties[$entryName].Value
    $wideTarget = (Get-ItemProperty -Path $registry).PSObject.Properties["0.0.0.0/$Port"].Value
    if ($wideTarget) { throw "A wildcard portproxy already uses port $Port. Inspect it before applying this scoped setup." }
}
$unexpected = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object {
    $_.LocalAddress -in @('0.0.0.0','::') -or ($_.LocalAddress -eq $TailscaleIP -and -not $oldTarget)
})
if ($unexpected.Count) { throw "An unrelated or wildcard listener already occupies port $Port; it was not modified." }

# Prefer the existing Windows-to-WSL localhost relay; keeps Linux loopback-only.
Start-RedReview -BindAddress '127.0.0.1'
$Backend = '127.0.0.1'
if (-not (Test-RedReview -Address $Backend)) {
    # Direct-IP fallback only in confirmed NAT mode, not mirrored networking.
    $mode = ((Invoke-WslCommand -Arguments @('wslinfo','--networking-mode')) -join '').Trim()
    if ($mode -ne 'nat') { throw 'Windows localhost forwarding failed and WSL is not confirmed NAT mode. No broad Linux listener or Windows forwarding rule was added.' }
    $candidates = ((Invoke-WslCommand -Arguments @('hostname','-I')) -join ' ') -split '\s+'
    $Backend = $candidates | Where-Object { $_ -match '^(172\.|192\.168\.|10\.)' } | Select-Object -First 1
    if (-not $Backend) { throw 'Cannot determine the private NAT address of this WSL distribution.' }
    Start-RedReview -BindAddress $Backend
    if (-not (Test-RedReview -Address $Backend)) { throw 'Windows cannot reach the WSL backend. Inspect WSL/Hyper-V firewall policy; no public forwarding rule was added.' }
}
Write-Host "Verified RedReview HTTP from Windows at http://${Backend}:$Port"

# Only replace a previous route owned by this setup, not another service.
$statePath = ((Invoke-WslCommand -Arguments @('wslpath','-w',"$ProjectRoot/.data/tailscale-forwarding.json")) -join '').Trim()
$ownedState = $null
if (Test-Path $statePath) { $ownedState = Get-Content -Raw $statePath | ConvertFrom-Json }
$newTarget = "$Backend/$Port"
if ($oldTarget -and $oldTarget -ne $newTarget -and (-not $ownedState -or $ownedState.target -ne $oldTarget)) {
    throw "An existing route for ${TailscaleIP}:$Port points elsewhere. It was not overwritten."
}
$helper = Get-Service iphlpsvc
if ($helper.Status -ne 'Running') { Start-Service iphlpsvc }

$ruleParameters = @{
    Name = $RuleName
    Group = $GroupName
    DisplayName = 'RedReview - Tailscale only TCP 8844'
    Direction = 'Inbound'
    Action = 'Allow'
    Enabled = 'True'
    Profile = 'Any'
    Protocol = 'TCP'
    LocalPort = $Port
    LocalAddress = $TailscaleIP
    RemoteAddress = '100.64.0.0/10'
    InterfaceAlias = $adapter.Name
    EdgeTraversalPolicy = 'Block'
}
if ($priorRule) {
    # Set-NetFirewallRule updates the owned rule rather than replacing other rules.
    $ruleParameters.Remove('Group')
    $ruleParameters.Remove('DisplayName')
    $ruleParameters['NewDisplayName'] = 'RedReview - Tailscale only TCP 8844'
    Set-NetFirewallRule @ruleParameters | Out-Null
} else {
    New-NetFirewallRule @ruleParameters | Out-Null
}
$operation = 'add'
if ($oldTarget) { $operation = 'set' }
Invoke-Netsh -Arguments @('interface','portproxy',$operation,'v4tov4',"listenaddress=$TailscaleIP","listenport=$Port","connectaddress=$Backend","connectport=$Port",'protocol=tcp')
@{ target = $newTarget; listener = "$TailscaleIP/$Port" } | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath

$verified = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    if (Test-RedReview -Address $TailscaleIP) { $verified = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $verified) { throw 'Forwarding/rule were applied, but the Windows Tailscale-IP HTTP check failed. Inspect portproxy, IP Helper and firewall policy; iPhone access is not verified.' }
Write-Host "Verified HTTP 200 through Windows Tailscale IP. Open in Safari: http://${TailscaleIP}:$Port/"
Write-Host 'The iPhone must have Tailscale connected and tailnet policy must permit TCP 8844 to this host.'
Write-Host 'No browser was launched. Rerun after restarting WSL or Windows, especially if the NAT address changes.'
