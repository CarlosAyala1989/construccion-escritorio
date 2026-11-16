# Inglés residual

La comparación AST registra 177 definiciones propias retiradas y sustituidas por nombres en español. El porcentaje de conversión de la matriz aprobada es **177/177 (100 %)**. El denominador excluye contratos, nombres impuestos por frameworks y APIs externas.

## Excepciones justificadas

- **Eel JavaScript → Python:** `login`, `logout`, `get_current_user`, `get_workspaces`, `select_workspace`, `start_session`, `end_session`, `import_files`, `get_scanners`, `scan_document`, `resume_capture`, `pick_and_import_files`, `export_files`, `get_session_files`, `get_pending_review`, `get_queue_items`, `correct_document`, `get_app_status`, `sync_now` y `get_config`.
- **Callbacks Eel Python → JavaScript:** `onFileDetected`, `onDocumentProcessed` y `onProcessingProgress`, junto con sus claves serializadas.
- **Adaptadores con nombre contractual:** `AdministradorBaseDatos.get_config`, `AdministradorBaseDatos.get_queue_items`, `ClienteAPISaaS.get_config`, `CargadorNube.upload`, `AdministradorEscaner.import_files`, `get_scanners`, `resume_capture`, `watch_folder` y `temp_folder` reflejan contratos Eel o estructuras consumidas.
- **Python y unittest:** `__init__`, `__name__`, `setUp`, métodos de aserción y excepciones estándar son obligatorios.
- **Watchdog y DB-API:** `on_created`, `cursor`, `execute`, `fetchone` y `close` implementan interfaces externas.
- **Protocolos y bibliotecas:** Eel, MySQL, SQLite, Google Drive, OAuth, HTTP, PDF, OCR, AES-GCM, SHA-256, WIA y TOTP no se traducen.
- **Persistencia:** tablas, columnas, rutas, variables de entorno, claves JSON y estados como `SUCCESS`, `PENDING` o `DESKTOP_SCANNER` permanecen congelados.

No quedan pendientes genéricos dentro de la matriz aprobada. Los nombres de archivos históricos se conservan para no romper imports, workflows ni empaquetado.
