param([ValidateSet('Install','Repair','Uninstall')][string]$Action='Install', [string]$SandboxRoot)
$ErrorActionPreference='Stop'
$dest=Join-Path $env:LOCALAPPDATA 'CodexThreadProviderCard'
$scope='User'
if($SandboxRoot){$dest=Join-Path ([IO.Path]::GetFullPath($SandboxRoot)) 'CodexThreadProviderCard'; $scope='Process'}
$exe=Join-Path $dest 'Backend.exe'
$entry='CODEX_CLI_PATH'
$active=[Environment]::GetEnvironmentVariable($entry,$scope)
$payload=Join-Path $PSScriptRoot 'payload'
$mark=Join-Path $dest '.provider-card-install-v1'
function Assert-ManagedDirectory {
    if((Test-Path -LiteralPath $dest) -and ((Get-Item -LiteralPath $dest).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Unexpected installation directory link.'}
    if((Test-Path -LiteralPath $dest) -and !(Test-Path -LiteralPath $mark -PathType Leaf)){throw 'The destination is occupied by another installation.'}
}
function Read-Manifest($base){
    $manifest=Get-Content -LiteralPath (Join-Path $base 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if($manifest.product -ne 'CodexThreadProviderCard' -or !$manifest.files){throw 'Invalid release manifest.'}
    foreach($f in $manifest.files){
        if($f.path -notmatch '^(runtime/)?[A-Za-z0-9_.-]+$' -or $f.path -match '(^|/)\.\.?(\/|$)' -or $f.sha256 -notmatch '^[a-f0-9]{64}$'){throw 'Invalid release entry.'}
    }
    return $manifest
}
function FileDigest([string]$Path){
    $stream=[IO.File]::OpenRead($Path)
    $algo=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($algo.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$algo.Dispose()}
}
function Verify($base,$manifest){
    foreach($f in $manifest.files){$path=Join-Path $base $f.path; if(!(Test-Path -LiteralPath $path -PathType Leaf) -or (FileDigest $path) -ne $f.sha256){throw "Invalid or missing release file: $($f.path)"}}
}
function Assert-NotInUse {
    $runtime=Join-Path $dest 'runtime\python.exe'
    $card=Join-Path $dest 'ProviderCard.exe'
    foreach($proc in [Diagnostics.Process]::GetProcesses()){
        try{if($proc.ProcessName -notin @('Backend','ProviderCard','python')){continue};$location=$proc.MainModule.FileName}catch{continue}finally{$proc.Dispose()}
        if($location -in @($exe,$runtime,$card)){throw 'Fully quit Codex and allow up to 20 seconds for the card to close before updating or uninstalling.'}
    }
}
Assert-ManagedDirectory
if($Action -eq 'Uninstall'){
    if(!(Test-Path -LiteralPath $mark)){Write-Host 'Already uninstalled.';return}
    Assert-NotInUse
    $manifest=Read-Manifest $dest
    if($active -eq $exe){[Environment]::SetEnvironmentVariable($entry,$null,$scope)}
    foreach($f in $manifest.files){$path=Join-Path $dest $f.path; if(Test-Path -LiteralPath $path -PathType Leaf){Remove-Item -LiteralPath $path -Force}}
    foreach($name in @('runtime','manifest.json','.provider-card-install-v1')){$path=Join-Path $dest $name; if(Test-Path -LiteralPath $path){if((Test-Path -LiteralPath $path -PathType Container) -and (Get-ChildItem -LiteralPath $path -Force)){continue};Remove-Item -LiteralPath $path -Force}}
    if(!(Get-ChildItem -LiteralPath $dest -Force)){Remove-Item -LiteralPath $dest}
    Write-Host 'Uninstalled. Reopen Codex. Saved provider credentials can be removed in Windows Credential Manager under ThreadProviderCard/Bindings/v1/.';return
}
if($active -and $active -ne $exe){throw 'Another Codex launcher is configured. The existing launcher has been preserved.'}
$manifest=Read-Manifest $payload
Verify $payload $manifest
& (Join-Path $payload 'Backend.exe') --card-doctor
if($LASTEXITCODE -ne 0){throw 'The Codex package or the API-key provider configuration is unsupported. See README.'}
if(!(Test-Path -LiteralPath $dest)){New-Item -ItemType Directory -Path $dest | Out-Null; [IO.File]::WriteAllText($mark,'CodexThreadProviderCard v1')}
if(@($manifest.files | Where-Object { $installed=Join-Path $dest $_.path; (Test-Path -LiteralPath $installed) -and (FileDigest $installed) -ne $_.sha256 }).Count){Assert-NotInUse}
foreach($f in $manifest.files){
    $path=Join-Path $dest $f.path; $folder=Split-Path -Parent $path
    if(!(Test-Path -LiteralPath $folder)){New-Item -ItemType Directory -Path $folder|Out-Null}
    if(!(Test-Path -LiteralPath $path) -or (FileDigest $path) -ne $f.sha256){Copy-Item -LiteralPath (Join-Path $payload $f.path) -Destination $path -Force}
}
Copy-Item -LiteralPath (Join-Path $payload 'manifest.json') -Destination (Join-Path $dest 'manifest.json') -Force
Verify $dest $manifest
if($active -ne $exe){[Environment]::SetEnvironmentVariable($entry,$exe,$scope)}
Write-Host 'Installed and verified. Fully quit and reopen Codex. If Explorer retains its old environment, sign out and sign in once.'

