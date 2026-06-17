# Empaquetado Windows

Este proyecto soporta dos formas de empaquetado para Windows:

- Instalador online liviano: genera un `.exe` pequeño en Linux. Al ejecutarse en Windows instala Python, dependencias Python, Poppler y Tesseract/OCR.
- Ejecutable PyInstaller: genera un `.exe` más pesado desde Windows.

## Instalador online desde Linux

Este es el flujo recomendado cuando quieres construir en Linux y pasar el `.exe`
a una computadora Windows para probarlo directamente.

```bash
cd construccion-escritorio
./scripts/build-online-installer-linux.sh
```

El instalador queda en:

```text
dist/windows/GobernanzaDocumentalSetup.exe
```

El instalador:

- Instala la app en `%LOCALAPPDATA%\GobernanzaDocumental`.
- Copia la conexión de base de datos desde `../construccion-web/.env` al archivo instalado `data\.env`.
- Crea un entorno virtual Python local.
- Descarga e instala Python 3.12.10 si Windows no tiene Python 3.11+.
- Instala las dependencias de `requirements.txt`.
- Instala Tesseract OCR y descarga `spa.traineddata`.
- Descarga la última build de Poppler para Windows.
- Crea accesos directos en el escritorio y en el menú inicio.
- Deja el lanzador de la app en `%LOCALAPPDATA%\GobernanzaDocumental\GobernanzaDocumental.exe`.

La computadora Windows necesita conexión a internet durante la instalación.
Si algo falla, el log queda en:

```text
%LOCALAPPDATA%\GobernanzaDocumental\data\logs\install.log
```

## Ejecutable PyInstaller desde Windows

## Requisitos

- Windows 10/11 de 64 bits.
- Python 3.11 o 3.12 instalado y disponible con el comando `py`.
- Google Chrome, Microsoft Edge o Chromium instalado para la interfaz Eel.
- Para OCR en PDFs escaneados: Tesseract y Poppler instalados en Windows y agregados al `PATH`.

## Generar el .exe

Desde PowerShell:

```powershell
cd construccion-escritorio
.\scripts\build-windows.ps1
```

O desde CMD:

```bat
cd construccion-escritorio
scripts\build-windows.cmd
```

El ejecutable queda en:

```text
dist\windows\GobernanzaDocumental.exe
```

## Datos de la app

En el instalador online, la cola local, archivos temporales, archivos procesados,
plantillas y logs se guardan en:

```text
%LOCALAPPDATA%\GobernanzaDocumental\data
```

En el ejecutable PyInstaller, se guardan en:

```text
%LOCALAPPDATA%\GobernanzaDocumental
```

Si necesitas configurar MySQL sin variables de entorno, crea este archivo:

```text
%LOCALAPPDATA%\GobernanzaDocumental\.env
```

Variables soportadas:

```env
DATABASE_URL=mysql://usuario:password@host:3306/base
```

o:

```env
MYSQL_HOST=host
MYSQL_PORT=3306
MYSQL_USER=usuario
MYSQL_PASSWORD=password
MYSQL_DATABASE=base
```
