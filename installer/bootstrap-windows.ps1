param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AppDir = Join-Path $InstallRoot "app"
$DataDir = Join-Path $InstallRoot "data"
$ToolsDir = Join-Path $InstallRoot "tools"
$DownloadsDir = Join-Path $InstallRoot "downloads"
$VenvDir = Join-Path $InstallRoot "venv"
$LogDir = Join-Path $DataDir "logs"

foreach ($Dir in @($DataDir, $ToolsDir, $DownloadsDir, $LogDir)) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}

$InstallLog = Join-Path $LogDir "install.log"

function Write-Step {
    param([string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $Line
    Add-Content -Path $InstallLog -Value $Line -Encoding UTF8
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    Write-Step "Descargando $Url"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null

    $TempFile = "$OutFile.download"
    foreach ($Path in @($OutFile, $TempFile)) {
        if (Test-Path $Path) {
            Remove-Item $Path -Force
        }
    }

    try {
        Invoke-WebRequest `
            -Uri $Url `
            -OutFile $TempFile `
            -UseBasicParsing `
            -Headers @{ "User-Agent" = "GobernanzaDocumentalInstaller/1.0" }
    }
    catch {
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -L --fail --retry 3 --retry-delay 2 -o $TempFile $Url
            if ($LASTEXITCODE -ne 0) {
                throw "curl no pudo descargar $Url"
            }
        }
        else {
            throw
        }
    }

    if (-not (Test-Path $TempFile) -or (Get-Item $TempFile).Length -eq 0) {
        throw "La descarga quedo vacia: $Url"
    }

    Move-Item -Force $TempFile $OutFile
}

function Test-WindowsExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [long]$MinimumBytes = 1048576
    )

    if (-not (Test-Path $Path)) {
        return $false
    }

    $Item = Get-Item $Path
    if ($Item.Length -lt $MinimumBytes) {
        return $false
    }

    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Bytes = New-Object byte[] 2
        [void]$Stream.Read($Bytes, 0, 2)
        return ($Bytes[0] -eq 0x4D -and $Bytes[1] -eq 0x5A)
    }
    finally {
        $Stream.Dispose()
    }
}

function Test-PythonVersion {
    param([string]$PythonExe)
    if (-not (Test-Path $PythonExe)) {
        return $false
    }

    $NormalizedPath = $PythonExe.Replace("/", "\")
    if ($NormalizedPath -match "\\Microsoft\\WindowsApps\\python3?\.exe$") {
        return $false
    }

    try {
        & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-ExistingPython {
    $Launchers = @()
    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        foreach ($VersionArg in @("-3.12", "-3.11", "-3")) {
            try {
                $Candidate = & $PyLauncher.Source $VersionArg -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $Candidate -and (Test-PythonVersion $Candidate.Trim())) {
                    return $Candidate.Trim()
                }
            }
            catch {
            }
        }
    }

    foreach ($Name in @("python.exe", "python3.exe")) {
        $Cmd = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Cmd -and (Test-PythonVersion $Cmd.Source)) {
            return $Cmd.Source
        }
    }

    return $null
}

function Install-PrivatePython {
    $PythonDir = Join-Path $ToolsDir "Python312"
    $PythonExe = Join-Path $PythonDir "python.exe"
    if (Test-PythonVersion $PythonExe) {
        return $PythonExe
    }

    $Installer = Join-Path $DownloadsDir "python-3.12.10-amd64.exe"
    Invoke-Download `
        -Url "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" `
        -OutFile $Installer

    Write-Step "Instalando Python 3.12 local"
    $Args = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_pip=1",
        "Include_tcltk=1",
        "Include_test=0",
        "SimpleInstall=1",
        "TargetDir=$PythonDir"
    )
    $Process = Start-Process -FilePath $Installer -ArgumentList $Args -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "El instalador de Python termino con codigo $($Process.ExitCode)"
    }

    if (-not (Test-PythonVersion $PythonExe)) {
        throw "No se encontro Python instalado en $PythonExe"
    }

    return $PythonExe
}

function Install-PythonRequirements {
    param([string]$PythonExe)

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-Step "Creando entorno virtual"
        & $PythonExe -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo crear el entorno virtual"
        }
    }

    Write-Step "Actualizando pip"
    & $VenvPython -m pip install --upgrade pip wheel setuptools
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo actualizar pip"
    }

    Write-Step "Instalando dependencias Python"
    & $VenvPython -m pip install -r (Join-Path $AppDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron instalar las dependencias Python"
    }

    $PywinPostInstall = Join-Path $VenvDir "Scripts\pywin32_postinstall.py"
    if (Test-Path $PywinPostInstall) {
        Write-Step "Registrando componentes pywin32"
        & $VenvPython $PywinPostInstall -install *> $null
    }
}

function Get-TesseractRoot {
    $Candidates = @(
        (Join-Path $ToolsDir "Tesseract-OCR"),
        (Join-Path $env:LOCALAPPDATA "Programs\Tesseract-OCR"),
        (Join-Path $env:ProgramFiles "Tesseract-OCR")
    )
    if (${env:ProgramFiles(x86)}) {
        $Candidates += (Join-Path ${env:ProgramFiles(x86)} "Tesseract-OCR")
    }

    foreach ($Candidate in $Candidates) {
        if (Test-Path (Join-Path $Candidate "tesseract.exe")) {
            return $Candidate
        }
    }

    $Cmd = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($Cmd) {
        return Split-Path -Parent $Cmd.Source
    }

    $SearchRoots = @(
        $ToolsDir,
        (Join-Path $env:LOCALAPPDATA "Programs"),
        (Join-Path $env:LOCALAPPDATA "GobernanzaDocumental")
    )
    foreach ($Root in $SearchRoots) {
        if (-not (Test-Path $Root)) {
            continue
        }

        $Found = Get-ChildItem -Path $Root -Filter "tesseract.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "Tesseract" } |
            Select-Object -First 1
        if ($Found) {
            return (Split-Path -Parent $Found.FullName)
        }
    }

    return $null
}

function Wait-TesseractRoot {
    param(
        [int]$TimeoutSeconds = 90,
        [int]$IntervalSeconds = 3
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $Existing = Get-TesseractRoot
        if ($Existing) {
            return $Existing
        }

        Start-Sleep -Seconds $IntervalSeconds
    } while ((Get-Date) -lt $Deadline)

    return $null
}

function Ensure-TesseractLanguage {
    param([string]$TesseractRoot)
    if (-not $TesseractRoot) {
        return
    }

    $TessData = Join-Path $TesseractRoot "tessdata"
    New-Item -ItemType Directory -Force -Path $TessData | Out-Null

    $Spa = Join-Path $TessData "spa.traineddata"
    if (-not (Test-Path $Spa)) {
        try {
            Invoke-Download `
                -Url "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/spa.traineddata" `
                -OutFile $Spa
        }
        catch {
            Write-Step "Advertencia: no se pudo descargar spa.traineddata: $($_.Exception.Message)"
        }
    }
}

function Install-Tesseract {
    $Existing = Get-TesseractRoot
    if ($Existing) {
        Write-Step "Tesseract detectado en $Existing"
        Ensure-TesseractLanguage $Existing
        return $Existing
    }

    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($Winget) {
        Write-Step "Instalando Tesseract OCR con winget"
        & $Winget.Source install `
            --id UB-Mannheim.TesseractOCR `
            --exact `
            --silent `
            --scope user `
            --accept-package-agreements `
            --accept-source-agreements

        if ($LASTEXITCODE -ne 0) {
            & $Winget.Source install `
                --id UB-Mannheim.TesseractOCR `
                --exact `
                --silent `
                --accept-package-agreements `
                --accept-source-agreements
        }

        $Existing = Wait-TesseractRoot -TimeoutSeconds 60
        if ($Existing) {
            Ensure-TesseractLanguage $Existing
            return $Existing
        }
    }

    Write-Step "Instalando Tesseract OCR desde instalador directo"
    $TesseractInstaller = Join-Path $DownloadsDir "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    $TesseractUrls = @(
        "https://downloads.sourceforge.net/project/tesseract-ocr.mirror/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
        "https://sourceforge.net/projects/tesseract-ocr.mirror/files/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe/download"
    )

    $TesseractDownloaded = $false
    foreach ($Url in $TesseractUrls) {
        try {
            Invoke-Download -Url $Url -OutFile $TesseractInstaller
            if (Test-WindowsExecutable -Path $TesseractInstaller -MinimumBytes 10000000) {
                $TesseractDownloaded = $true
                break
            }

            Remove-Item $TesseractInstaller -Force -ErrorAction SilentlyContinue
            Write-Step "Descarga invalida de Tesseract desde $Url"
        }
        catch {
            Remove-Item $TesseractInstaller -Force -ErrorAction SilentlyContinue
            Write-Step "No se pudo descargar Tesseract desde ${Url}: $($_.Exception.Message)"
        }
    }

    if (-not $TesseractDownloaded) {
        Write-Step "Advertencia: no se pudo descargar un instalador valido de Tesseract OCR; la instalacion continuara sin OCR local"
        return $null
    }

    $TesseractTarget = Join-Path $ToolsDir "Tesseract-OCR"
    try {
        $Process = Start-Process -FilePath $TesseractInstaller -ArgumentList "/S /D=$TesseractTarget" -Wait -PassThru
    }
    catch {
        Write-Step "Advertencia: no se pudo ejecutar el instalador de Tesseract OCR: $($_.Exception.Message)"
        return $null
    }

    Write-Step "Instalador de Tesseract OCR termino con codigo $($Process.ExitCode)"
    if ($Process.ExitCode -ne 0) {
        Write-Step "Advertencia: el instalador de Tesseract OCR no termino correctamente"
        return $null
    }

    Write-Step "Esperando confirmacion de Tesseract OCR"
    $Existing = Wait-TesseractRoot -TimeoutSeconds 120
    if (-not $Existing) {
        Write-Step "Advertencia: no se encontro Tesseract despues de instalarlo; la instalacion continuara sin OCR local"
        return $null
    }

    Ensure-TesseractLanguage $Existing
    return $Existing
}

function Get-PopplerBin {
    $Existing = Get-ChildItem -Path $ToolsDir -Filter "pdftoppm.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Existing) {
        return (Split-Path -Parent $Existing.FullName)
    }

    $Cmd = Get-Command pdftoppm.exe -ErrorAction SilentlyContinue
    if ($Cmd) {
        return Split-Path -Parent $Cmd.Source
    }

    return $null
}

function Install-Poppler {
    $Existing = Get-PopplerBin
    if ($Existing) {
        Write-Step "Poppler detectado en $Existing"
        return $Existing
    }

    $ReleaseApi = "https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest"
    Write-Step "Buscando ultima version de Poppler para Windows"
    $Release = Invoke-RestMethod -Uri $ReleaseApi -Headers @{ "User-Agent" = "GobernanzaDocumentalInstaller" }
    $Asset = $Release.assets |
        Where-Object { $_.name -match "\.zip$" -and $_.name -match "Release" } |
        Select-Object -First 1

    if (-not $Asset) {
        throw "No se encontro un ZIP de Poppler en la ultima release"
    }

    $ZipPath = Join-Path $DownloadsDir $Asset.name
    Invoke-Download -Url $Asset.browser_download_url -OutFile $ZipPath

    $PopplerRoot = Join-Path $ToolsDir "poppler"
    if (Test-Path $PopplerRoot) {
        Remove-Item $PopplerRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $PopplerRoot | Out-Null

    Write-Step "Extrayendo Poppler"
    Expand-Archive -Path $ZipPath -DestinationPath $PopplerRoot -Force

    $Bin = Get-PopplerBin
    if (-not $Bin) {
        throw "No se encontro pdftoppm.exe despues de instalar Poppler"
    }

    return $Bin
}

function Write-Launcher {
    param(
        [string]$PopplerBin,
        [string]$TesseractRoot
    )

    $Launcher = Join-Path $InstallRoot "GobernanzaDocumental.cmd"
    $PythonExe = Join-Path $VenvDir "Scripts\python.exe"
    $PathParts = @()

    if ($PopplerBin) {
        $PathParts += $PopplerBin
    }
    if ($TesseractRoot) {
        $PathParts += $TesseractRoot
    }

    $ExtraPath = [string]::Join(";", $PathParts)
    $TessData = if ($TesseractRoot) { Join-Path $TesseractRoot "tessdata" } else { "" }

    $Content = @"
@echo off
set "GOBERNANZA_INSTALL_ROOT=$InstallRoot"
set "GOBERNANZA_DATA_DIR=$DataDir"
set "OCR_LANG=spa+eng"
set "PYTHONIOENCODING=utf-8"
if not "$TessData"=="" set "TESSDATA_PREFIX=$TessData"
set "PATH=$ExtraPath;%PATH%"
if not exist "$LogDir" mkdir "$LogDir"
"$PythonExe" "$AppDir\main.py" >> "$LogDir\app.log" 2>&1
"@
    Set-Content -Path $Launcher -Value $Content -Encoding ASCII

    $VbsLauncher = Join-Path $InstallRoot "GobernanzaDocumental.vbs"
    $VbsContent = @"
Set shell = CreateObject("WScript.Shell")
shell.Run Chr(34) & "$Launcher" & Chr(34), 0, False
"@
    Set-Content -Path $VbsLauncher -Value $VbsContent -Encoding ASCII
}

Write-Step "Preparando instalacion en $InstallRoot"

$Python = Get-ExistingPython
if (-not $Python) {
    $Python = Install-PrivatePython
}
else {
    Write-Step "Python detectado en $Python"
}

Install-PythonRequirements $Python
$TesseractRoot = Install-Tesseract
$PopplerBin = Install-Poppler
Write-Launcher -PopplerBin $PopplerBin -TesseractRoot $TesseractRoot

Write-Step "Instalacion completada"
