# Compatibilidad

Se conservaron sin modificación:

- Las tablas y columnas MySQL y SQLite.
- Los valores persistidos de roles, estados, proveedores y tipos de política.
- Las claves JSON y diccionarios compartidos.
- Las rutas `/api/sync/*` y `/api/stats`.
- Los nombres expuestos por Eel y sus callbacks.
- Las variables de entorno.
- El prefijo `DZENC1:`, los bytes mágicos, versión, nonce, etiqueta y derivación de claves.
- Las rutas persistentes y la estructura de la cola local.

La interoperabilidad real con MySQL, Google Drive y la aplicación web requiere credenciales e infraestructura de prueba. No se usó producción ni se ejecutaron migraciones.
