$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$VenvPath = Join-Path $ProjectRoot ".venv-windows"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv $VenvPath
    } else {
        python -m venv $VenvPath
    }
}

& $PythonExe -m pip install --upgrade pip wheel setuptools
& $PythonExe -m pip install -r requirements.txt
& $PythonExe -m pip install pyinstaller

if (Test-Path "build") {
    Remove-Item "build" -Recurse -Force
}

if (Test-Path "dist\windows") {
    Remove-Item "dist\windows" -Recurse -Force
}

& $PythonExe -m PyInstaller --noconfirm --clean --distpath "dist\windows" --workpath "build\windows" build.spec

$ExePath = Join-Path $ProjectRoot "dist\windows\GobernanzaDocumental.exe"
if (-not (Test-Path $ExePath)) {
    throw "No se genero el ejecutable esperado: $ExePath"
}

Write-Host ""
Write-Host "Ejecutable generado:"
Write-Host $ExePath
