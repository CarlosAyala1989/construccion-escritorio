Unicode true

!ifndef OUT_FILE
!define OUT_FILE "build/windows-online-installer/GobernanzaDocumental.exe"
!endif

Name "Gobernanza Documental"
OutFile "${OUT_FILE}"
RequestExecutionLevel user
SilentInstall silent
SetCompress off

VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName" "Gobernanza Documental"
VIAddVersionKey "CompanyName" "Gobernanza Documental"
VIAddVersionKey "FileDescription" "Lanzador de Gobernanza Documental"
VIAddVersionKey "FileVersion" "1.0.0"
VIAddVersionKey "ProductVersion" "1.0.0"

Section
    Exec '"$SYSDIR\wscript.exe" "$EXEDIR\GobernanzaDocumental.vbs"'
SectionEnd
