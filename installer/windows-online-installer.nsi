Unicode true

!include "LogicLib.nsh"

!ifndef APP_VERSION
!define APP_VERSION "1.0.0"
!endif

!ifndef STAGING_DIR
!define STAGING_DIR "build/windows-online-installer"
!endif

!ifndef OUT_FILE
!define OUT_FILE "dist/windows/GobernanzaDocumentalSetup.exe"
!endif

Name "Gobernanza Documental"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\GobernanzaDocumental"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Caption "Gobernanza Documental Instalacion / Actualizacion"
UninstallCaption "Gobernanza Documental Desinstalacion"

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "Gobernanza Documental"
VIAddVersionKey "CompanyName" "Gobernanza Documental"
VIAddVersionKey "FileDescription" "Instalador online de Gobernanza Documental"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"

Page directory
Page instfiles

UninstPage uninstConfirm
UninstPage instfiles

Function .onInit
    IfFileExists "$LOCALAPPDATA\GobernanzaDocumental\Uninstall.exe" 0 done
        MessageBox MB_ICONINFORMATION|MB_OK "Se detecto una instalacion previa. Este instalador la actualizara/reinstalara sin que tengas que abrir el desinstalador."
    done:
FunctionEnd

Function un.onInit
    MessageBox MB_ICONQUESTION|MB_YESNO "Este archivo es el desinstalador de Gobernanza Documental. Para actualizar o reinstalar, cancela esta ventana y ejecuta GobernanzaDocumentalSetup-actualizado.exe.$\r$\n$\r$\nQuieres desinstalar ahora?" IDYES continue
    Abort
    continue:
FunctionEnd

Section "Instalar"
    SetShellVarContext current

    DetailPrint "Preparando carpeta de instalacion..."
    IfFileExists "$INSTDIR\Uninstall.exe" 0 fresh_install
        DetailPrint "Instalacion previa detectada; actualizando archivos de la aplicacion..."
    fresh_install:
    CreateDirectory "$INSTDIR"
    RMDir /r "$INSTDIR\app"
    RMDir /r "$INSTDIR\installer"

    SetOutPath "$INSTDIR"
    File /r "${STAGING_DIR}/app"
    File /r "${STAGING_DIR}/installer"
    File "${STAGING_DIR}/GobernanzaDocumental.exe"

    CreateDirectory "$INSTDIR\data"
    CopyFiles /SILENT "$INSTDIR\installer\app.env" "$INSTDIR\data\.env"

    DetailPrint "Instalando Python, dependencias, OCR y Poppler..."
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\bootstrap-windows.ps1" -InstallRoot "$INSTDIR"'
    Pop $0
    ${If} $0 != 0
        MessageBox MB_ICONSTOP "No se pudo completar la instalacion de requisitos. Revisa el log en:$\r$\n$INSTDIR\data\logs\install.log"
        Abort
    ${EndIf}

    CreateDirectory "$SMPROGRAMS\Gobernanza Documental"
    CreateShortCut "$SMPROGRAMS\Gobernanza Documental\Gobernanza Documental.lnk" "$INSTDIR\GobernanzaDocumental.exe" "" "$INSTDIR\GobernanzaDocumental.exe" 0
    CreateShortCut "$DESKTOP\Gobernanza Documental.lnk" "$INSTDIR\GobernanzaDocumental.exe" "" "$INSTDIR\GobernanzaDocumental.exe" 0

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GobernanzaDocumental" "DisplayName" "Gobernanza Documental"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GobernanzaDocumental" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GobernanzaDocumental" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GobernanzaDocumental" "DisplayVersion" "${APP_VERSION}"

    DetailPrint "Instalacion terminada."
SectionEnd

Section "Uninstall"
    SetShellVarContext current
    Delete "$DESKTOP\Gobernanza Documental.lnk"
    RMDir /r "$SMPROGRAMS\Gobernanza Documental"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GobernanzaDocumental"
    RMDir /r "$INSTDIR"
SectionEnd
