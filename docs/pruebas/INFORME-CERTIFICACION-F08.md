# Informe de certificación F08 - Escritorio

## Dictamen

**APROBADO CON LIMITACIONES para publicación de la rama.** La validación productiva queda condicionada al hardware WIA, OCR de imagen real y servicios externos.

Base verificada: `refactor/espanol-latam-escritorio-v01` en `cb0461f27106b1fa763cf14eb1b9ee79c37e2ab9`.

Commit de corrección: `1d07d6416c85f151a067a7b05f72b38e7a17a46a`.

## Entorno controlado

- Python 3.13.4 y MySQL 8.0.46 compartido con la web en `127.0.0.1:3307`.
- SQLite y clave local aislados mediante `GOBERNANZA_DATA_DIR` bajo `D:\Docuzen_2026\.f08-data`.
- Usuario, TOTP, espacio y documentos exclusivamente ficticios.
- Cuatro PDF sintéticos no sensibles bajo `D:\Docuzen_2026\.f08-artifacts\desktop\pdfs`.
- Eel real en `127.0.0.1:8765`, automatizado con Playwright sobre Chrome.
- Evidencias visuales en `D:\Docuzen_2026\.f08-evidencias\desktop-login.png` y `desktop-session.png`.

## Resultados

| Prueba | Resultado |
|---|---|
| `python -m pytest -q` | 35/35 aprobadas |
| Cuatro pruebas de PDF antes omitidas | 4/4 ejecutadas y aprobadas con documentos sintéticos |
| Eel: carga de interfaz y puente Python/JavaScript | Aprobado |
| Login con contraseña y TOTP | Aprobado |
| Consulta MySQL y selección de espacio | Aprobado; un espacio disponible |
| Inicio de sesión documental | Aprobado; panel activo y estado conectado |
| Cola/bitácora SQLite cifrada y rutas de archivos | Aprobado por regresión automatizada |
| Cierre del proceso y puerto Eel | Aprobado; puerto 8765 liberado |

La única consola observada fue el 404 no funcional de `favicon.ico`; no afectó el flujo.

## Defecto comprobado y corregido

El escritorio buscaba `.env` y `.env.local` dentro del repositorio web hermano. Esto ampliaba el alcance de secretos y acoplaba ambos repositorios. Se eliminaron exclusivamente esas dos rutas. La regresión verifica que solo se consultan el entorno raíz controlado, el repositorio de escritorio y su directorio de datos; las variables de proceso mantienen prioridad. El login Eel/MySQL volvió a aprobar después del cambio.

## Integración efectiva

- La integración activa continúa siendo MySQL directo más SQLite local; `ClienteAPISaaS` y `/api/sync/*` no tienen consumidor activo en el flujo actual.
- El escritorio escribió `LOGIN` y `SESSION_STARTED` en la misma MySQL y la web los mostró en actividad reciente.
- No se modificaron contratos Eel, tablas, columnas, estados persistidos ni formatos criptográficos.

## Limitaciones y riesgos pendientes

- No se utilizó un escáner WIA físico; captura física queda pendiente de validación externa.
- Los PDF sintéticos contienen texto incrustado. El binario Tesseract existe, pero `pdftoppm` no está disponible en PATH; por ello no se certifica OCR integral sobre escaneos raster ni marcas de agua diagonales reales.
- No se ejecutaron Google Drive real, Ghostscript real, instalador Windows completo ni recuperación ante una interrupción externa real.
- El canal nativo de automatización de Windows no estuvo disponible. La interfaz Eel sí fue validada mediante navegador real conectado al servidor Eel.

## Propuesta de publicación (no ejecutada)

```powershell
git status --short
git log --oneline --decorate -5
git push -u origin refactor/espanol-latam-escritorio-v01
```

Después del push, abrir PR hacia la rama objetivo y exigir CI más una prueba manual firmada con WIA/Poppler. No se realizó push, PR, merge ni despliegue durante F08.
