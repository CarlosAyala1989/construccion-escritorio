# Pruebas y evidencias

Validaciones ejecutadas durante la refactorización:

- Análisis sintáctico AST de todos los archivos Python propios: aprobado.
- Pruebas focalizadas RF-03, RF-07, RF-08, nomenclatura y carga: aprobadas.
- Suite `python -m unittest discover -s tests -v`: 34 pruebas descubiertas, 30 aprobadas y 4 omitidas por falta de documentos reales; sin fallos.
- `node --check web/js/app.js`: aprobado.
- `node --check web/js/eel_bridge.js`: aprobado.
- `git diff --check`: aprobado.

Las pruebas con documentos reales se omiten si no están configuradas las variables `INFORME_RIESGO_TEST_PDF`, `RESERVADO_TEST_PDF`, `SECRETO_TEST_PDF` y `SECRETO_ROJO_TEST_PDF`.

No se afirma validación de MySQL real, Google Drive real, escáner WIA, arranque gráfico completo ni instalador Windows sin ejecutar esos escenarios en infraestructura controlada.
