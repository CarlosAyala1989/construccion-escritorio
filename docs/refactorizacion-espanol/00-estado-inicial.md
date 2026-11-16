# Estado inicial

- Repositorio: `construccion-escritorio`.
- Rama base: `master`.
- SHA base: `e41b9105f37188092186f358bf16ad4255c373ce`.
- Rama de trabajo: `refactor/espanol-latam-escritorio-v01`.
- Árbol inicial: limpio y sincronizado con `origin/master`.

La aplicación usa Python, Eel, HTML, CSS, JavaScript, MySQL y SQLite. Integra OCR mediante Tesseract/Poppler, OpenCV, cifrado AES-GCM, autenticación bcrypt/TOTP, Google Drive, vigilancia de archivos y escaneo WIA. El empaquetado usa PyInstaller y el instalador usa NSIS y PowerShell.

La línea base inicial descubrió 29 pruebas: 22 aprobadas, 3 con errores por dependencias ausentes y 4 omitidas por falta de documentos reales configurados. Tras instalar las dependencias se descubrieron 31 pruebas; la evidencia final se registra en `08-pruebas-y-evidencias.md`.
