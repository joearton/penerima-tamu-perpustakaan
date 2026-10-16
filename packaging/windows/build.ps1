# Build installer Windows: dist\PenerimaTamuPerpustakaan-<versi>-setup.exe
# Butuh: Python 3.11+ dan Inno Setup 6 (https://jrsoftware.org/isdl.php)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $Root

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Gagal: $Exe $Arguments" }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) { Invoke-Checked "python" @("-m", "venv", ".venv") }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
Invoke-Checked $Py @("-m", "pip", "install", "-q", "-e", ".[build]")
$env:LV_HOME = $Root
Invoke-Checked $Py @("-m", "library_visitor", "--download-models")
Invoke-Checked $Py @("-m", "PyInstaller", "--noconfirm", "--clean", "packaging\penerima-tamu.spec")

$Version = & $Py -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
$Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 belum terpasang: https://jrsoftware.org/isdl.php" }
Invoke-Checked $Iscc @("/DAppVersion=$Version", "packaging\windows\installer.iss")
Write-Host "Selesai: dist\PenerimaTamuPerpustakaan-$Version-setup.exe"
