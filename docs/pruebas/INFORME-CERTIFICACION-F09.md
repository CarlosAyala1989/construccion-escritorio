# Certificación F09 — aplicación de escritorio

Fecha: 2026-11-17 (America/Lima).

## Resultado

**BLOQUEADO para producción**, aunque tres vulnerabilidades del snapshot F08 quedaron corregidas y verificadas en la rama de trabajo.

## Correcciones aplicadas

- Eliminado el generador que leía `.env` web/escritorio y lo incrustaba en el instalador.
- Eliminadas las copias de `app.env` al staging y a `data/.env`.
- Caché `cached_config` cifrada con AES-256-GCM y migración transparente de JSON heredado.
- `local_queue.encryption_password` cifrado al escribir y descifrado al leer, incluida migración heredada.
- Clave local protegida mediante DPAPI ligada al usuario de Windows; la clave Base64 antigua migra atómicamente conservando el mismo material AES.
- Python 3.12.10, Tesseract 5.5, `spa.traineddata` y Poppler 26.09.0 quedaron fijados y verificados por SHA-256. El instalador aborta si OCR no puede instalarse de forma verificada.

## Pruebas

| Prueba | Resultado |
|---|---|
| `python -m pytest -q` | 38 aprobadas, 4 omitidas, 1 advertencia deprecación PyPDF2 |
| DPAPI real en Windows | Creación, migración legacy y reapertura aprobadas |
| AES-GCM | Round-trip y rechazo de manipulación aprobados |
| SQLite | Sin sentinelas de secretos en `cached_config` ni `encryption_password` |
| Parser PowerShell | Sin errores |
| Sintaxis del script Bash, normalizando CRLF en memoria | Aprobada |
| Escaneo Codex Security del snapshot `18f9b4fd4550fb0b81c7f30f981fd39e9e0f621f` | 1 crítico, 1 alto y 1 medio; los tres fueron objeto de las correcciones F09 |

Escaneo: `6ab012e7-7247-46d0-b3f2-7f1b59e122f2`.

## OCR y WIA reales

Tesseract 5.5 y Poppler 26.09 procesaron el corpus sintético real:

- digital: 2/2 tokens;
- raster: 1/2 (`F09` se interpretó como `FO9`);
- multipágina: 3/3 folios;
- baja calidad: 2/2;
- estructurado: 4/4 campos;
- PNG: reprodujo la ambigüedad `0/O`.

WIA enumeró tres equipos Brother, conectó con los tres y obtuvo un ítem por dispositivo. No se capturó una hoja porque no se pudo garantizar que cristal/ADF estuvieran libres de documentos reales. La captura física, ADF multipágina, desconexión/reanudación y limpieza de temporales siguen pendientes con hoja sintética.

## Bloqueos restantes

- Los secretos equivalentes siguen en texto claro en MySQL y deben cifrarse de manera coordinada con la web.
- No hay aprovisionamiento seguro postinstalación de una credencial mínima por dispositivo; retirar el secreto del EXE evita filtrarlo, pero una instalación nueva todavía requiere ese canal.
- No se reconstruyó ni firmó un instalador: PyInstaller/NSIS y certificado de firma no estaban disponibles.
- Google Drive real y reanudación de cargas no fueron certificados.
- Falta captura WIA física y un umbral formal de exactitud OCR sobre un corpus mayor.

## Rollback

Antes de distribuir una actualización, respaldar `data/local_queue.db` y `.local-encryption.key`. Para revertir el binario, conservar el directorio `data`; no volver a un binario que desconozca `DPAPI1:` después de migrar la clave. La salida segura es restaurar conjuntamente binario, SQLite y clave desde el mismo snapshot. Nunca borrar automáticamente documentos o carpetas de Drive durante rollback.
