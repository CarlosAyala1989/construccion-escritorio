# Arquitectura

`main.py` prepara directorios, inicia el sincronizador y levanta Eel. `src/controller.py` coordina autenticación, sesión, captura, OCR, políticas, cifrado, estructuración, cola y carga. La interfaz en `web/` consume las funciones expuestas por Eel y recibe tres callbacks de progreso.

Capas principales:

- `src/core/`: OCR, visión, cifrado, escritura temporal segura y organización documental.
- `src/database/`: MySQL remoto, SQLite local, caché, cola, sesión y bitácora.
- `src/hardware/`: vigilancia, importación y captura física.
- `src/sync/`: almacenamiento local/Google Drive y cliente HTTP SaaS.
- `web/`: presentación y puente Eel.

El formato seguro temporal, la clave local, las tablas físicas, las rutas API y las claves serializadas son límites de compatibilidad y no se modifican por motivos lingüísticos.
