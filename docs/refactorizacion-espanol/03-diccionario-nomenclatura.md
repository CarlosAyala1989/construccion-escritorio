# Diccionario de nomenclatura

| Concepto | Python | JavaScript | Contrato externo |
|---|---|---|---|
| usuario | `usuario` | `usuario` | `user`, `userId` congelados cuando provienen de MySQL/JSON |
| espacio de trabajo | `espacio_trabajo` | `espacioTrabajo` | `Workspace`, `workspaceId` congelados |
| documento | `documento` | `documento` | nombres de campos existentes congelados |
| política de seguridad | `politica_seguridad` | `politicaSeguridad` | `SecurityPolicy` congelado |
| configuración | `configuracion` | `configuracion` | `Config` y claves camelCase congeladas |
| nomenclatura | `nomenclatura` | `nomenclatura` | `NomenclatureField` congelado |
| bitácora de auditoría | `bitacora_auditoria` | `bitacoraAuditoria` | `AuditLog` y estados congelados |
| cola de pendientes | `cola_pendientes` | `colaPendientes` | esquema SQLite congelado |
| sesión | `sesion` | `sesion` | claves Eel y estados persistidos congelados |
| cifrado | `cifrado` | `cifrado` | formato, bytes mágicos y algoritmos congelados |
| almacenamiento | `almacenamiento` | `almacenamiento` | API de Google Drive congelada |
| operaciones | `obtener`, `validar`, `subir`, `sincronizar` | equivalentes camelCase | rutas HTTP congeladas |

Los identificadores no llevan tildes. Python usa `snake_case`, las clases usan `PascalCase` y las constantes usan `UPPER_SNAKE_CASE`.
