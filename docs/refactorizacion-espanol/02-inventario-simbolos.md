# Inventario de símbolos

La auditoría comparó las definiciones Python del SHA inicial con la rama refactorizada. Se retiraron 177 nombres propios en inglés y se propagaron sus equivalentes en español por imports, llamadas y pruebas. La matriz se reproduce comparando las definiciones AST entre `e41b9105f37188092186f358bf16ad4255c373ce` y `HEAD`.

| Área | Ejemplos iniciales | Clasificación | Nombres adoptados |
|---|---|---|---|
| Contexto | `DesktopSessionContext`, `CaptureContextError` | TRADUCIBLE_MULTIMODULO | `ContextoSesionEscritorio`, `ErrorContextoCaptura` |
| Documentos | `FileStructurer`, `PendingTray` | TRADUCIBLE_MULTIMODULO | `EstructuradorArchivos`, `BandejaPendientes` |
| OCR y visión | `OCREngine`, `extract_text_from_pdf`, `VisionEngine` | TRADUCIBLE_MULTIMODULO | `MotorOCR`, `extraer_texto_pdf`, `MotorVision` |
| Cifrado | `CryptoEngine`, `SecureFileWriter`, `encrypt_local_payload` | TRADUCIBLE_MULTIMODULO | `MotorCifrado`, `EscritorArchivoSeguro`, `cifrar_contenido_local` |
| Persistencia | `DatabaseManager`, `authenticate_user`, `get_security_policies` | TRADUCIBLE_MULTIMODULO | `AdministradorBaseDatos`, `autenticar_usuario`, `obtener_politicas_seguridad` |
| Captura | `ScannerManager`, `scan_physical_document` | TRADUCIBLE_MULTIMODULO | `AdministradorEscaner`, `escanear_documento_fisico` |
| Almacenamiento | `CloudUploader`, `_upload_gdrive`, `compress_pdf` | TRADUCIBLE_MULTIMODULO | `CargadorNube`, `_subir_drive`, `comprimir_pdf` |
| HTTP interno | `SaaSAPIClient`, `report_upload`, `sync_logs` | TRADUCIBLE_LOCAL | `ClienteAPISaaS`, `informar_subida`, `sincronizar_bitacoras` |
| Pruebas | clases, auxiliares y casos propios | TRADUCIBLE_LOCAL | nombres descriptivos en español |
| Eel | `login`, `get_workspaces`, `start_session`, etc. | CONTRATO_CONGELADO | sin cambio; ver `tests/test_contratos_eel.py` |
| Persistencia | tablas, columnas, claves y estados | CONTRATO_CONGELADO | sin cambio |
| Frameworks | `__init__`, `setUp`, `on_created`, cursores DB-API | OBLIGATORIO_FRAMEWORK/EXTERNO | sin cambio |

Los nombres ingleses restantes están clasificados en `09-ingles-residual.md`; no se contabilizan como renombrables.
