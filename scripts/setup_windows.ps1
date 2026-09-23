# Windows x64 portable project directory; no global PATH or environment activation.
param([switch]$CpuOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location $taskRoot
if (-not [Environment]::Is64BitProcess) { throw 'Run 64-bit PowerShell.' }
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) { throw 'Install Visual Studio C++ Build Tools, then use an x64 Native Tools terminal to run this script.' }
function Run-Native($exe, $arguments) { & $exe @arguments; if ($LASTEXITCODE -ne 0) { throw "$exe failed ($LASTEXITCODE)" } }
New-Item -Force -ItemType Directory '.runtime/bin','.runtime/downloads' | Out-Null
$mamba = Join-Path $taskRoot '.runtime/bin/micromamba.exe'
if (-not (Test-Path $mamba)) {
  Run-Native 'curl.exe' @('-fL','--retry','1','https://micro.mamba.pm/api/micromamba/win-64/2.8.1','-o','.runtime/downloads/micromamba.tar.bz2')
  Run-Native 'tar.exe' @('-xjf','.runtime/downloads/micromamba.tar.bz2','-C','.runtime','Library/bin/micromamba.exe')
  Move-Item '.runtime/Library/bin/micromamba.exe' $mamba
}
$core = Join-Path $taskRoot '.runtime/envs/core'
Run-Native $mamba @('create','-y','-p',$core,'-c','conda-forge','--strict-channel-priority','python=3.11','pip','ffmpeg=9','git','nodejs=22','7zip')
$env:PATH = "$core;$core/Library/bin;$core/Scripts;$env:PATH"
$python = Join-Path $core 'python.exe'
Run-Native $python @('-m','pip','install','--retries','1','-e','.[dev]')
Run-Native $python @('scripts/setup_rubberband.py','--prefix',$core)
if ($CpuOnly) { $env:OTTO_TORCH_INDEX = 'https://download.pytorch.org/whl/cpu' }
Run-Native $python @('scripts/setup_inference.py')
Run-Native $python @('scripts/prepare_models.py')
Run-Native $python @('scripts/setup_player.py')
Push-Location desktop
Run-Native 'npm.cmd' @('install','--ignore-scripts')
Run-Native 'node.exe' @('node_modules/electron/install.js')
Run-Native 'npm.cmd' @('run','build')
Pop-Location
Write-Host 'Setup finished. Start with launch-windows.cmd. Windows/CUDA requires hardware acceptance.'
