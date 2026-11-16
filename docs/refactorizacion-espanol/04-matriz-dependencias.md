# Matriz de dependencias

| Productor | Consumidor | Contrato | Política |
|---|---|---|---|
| `src/controller.py` | `web/js/app.js` | funciones y respuestas Eel | CONGELADO; cambio únicamente atómico |
| `src/controller.py` | `web/js/eel_bridge.js` | callbacks de progreso | CONGELADO |
| MySQL web | `sqlite_manager.py` | tablas y columnas Prisma/MySQL | CONGELADO |
| `sqlite_manager.py` | controlador | diccionarios camelCase/snake_case | ADAPTADOR si se traduce internamente |
| `scanner.py` | `secure_file_writer.py` | sesión y archivo AES-GCM | CONGELADO |
| `controller.py` | `cloud_uploader.py` | configuración, espacio y resultado | claves externas congeladas |
| `saas_api.py` | aplicación web | `/api/sync/config`, `/upload`, `/logs` | CONGELADO |
| SQLite | sincronizador | cola, sesión y bitácora | esquema y estados congelados |
| `build.spec` | módulos Python | nombres de módulo para PyInstaller | actualizar si cambia un archivo |

No se renombraron archivos de módulo, por lo que los `hiddenimports` siguen siendo válidos.
