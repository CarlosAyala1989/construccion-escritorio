# Inventario de símbolos

La auditoría identificó 19 clases y 168 funciones o métodos propios en la aplicación, además de 15 clases y 42 funciones o métodos de prueba.

| Área | Símbolo inicial | Clasificación | Nombre adoptado |
|---|---|---|---|
| Contexto | `DesktopSessionContext` | TRADUCIBLE_MULTIMODULO | `ContextoSesionEscritorio` |
| Contexto | `CaptureContextError` | TRADUCIBLE_MULTIMODULO | `ErrorContextoCaptura` |
| Documentos | `FileStructurer` | TRADUCIBLE_MULTIMODULO | `EstructuradorArchivos` |
| Pendientes | `PendingTray` | TRADUCIBLE_MULTIMODULO | `BandejaPendientes` |
| OCR | `OCREngine` | TRADUCIBLE_MULTIMODULO | `MotorOCR` |
| Visión | `VisionEngine` | TRADUCIBLE_MULTIMODULO | `MotorVision` |
| Cifrado | `CryptoEngine` | TRADUCIBLE_MULTIMODULO | `MotorCifrado` |
| Persistencia | `DatabaseManager` | TRADUCIBLE_MULTIMODULO | `AdministradorBaseDatos` |
| Escáner | `ScannerManager` | TRADUCIBLE_MULTIMODULO | `AdministradorEscaner` |
| Almacenamiento | `CloudUploader` | TRADUCIBLE_MULTIMODULO | `CargadorNube` |
| Seguridad | `SecureFileWriter` | TRADUCIBLE_MULTIMODULO | `EscritorArchivoSeguro` |
| HTTP | `SaaSAPIClient` | TRADUCIBLE_LOCAL | `ClienteAPISaaS` |
| Eel | `get_workspaces`, `start_session`, etc. | CONTRATO_CONGELADO | Sin cambio |
| MySQL/SQLite | tablas, columnas y estados | CONTRATO_CONGELADO | Sin cambio |
| Bibliotecas | APIs de Python, Eel, Google y navegador | EXTERNO | Sin cambio |

Las variables locales restantes se revisan por módulo; no se aplican sustituciones masivas porque varias claves representan datos persistidos o contratos con la web.
