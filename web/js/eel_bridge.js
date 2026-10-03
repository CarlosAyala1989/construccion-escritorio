/**
 * Eel Bridge — Callbacks de Python → JavaScript (Patrón Observer).
 * Python emite eventos, JS los recibe y actualiza la UI.
 */

// Se ejecuta cuando se detecta un archivo nuevo en la carpeta vigilada.
eel.expose(onFileDetected);
function onFileDetected(data) {
    console.log('[BRIDGE] File detected:', data.name);
    refreshSessionFiles();
    updateDocCount();
}

// Se ejecuta cuando termina el procesamiento de un documento.
eel.expose(onDocumentProcessed);
function onDocumentProcessed(data) {
    console.log('[BRIDGE] Document processed:', data.name, 'Encryption:', data.encryption);
    // Aquí se podría mostrar una notificación emergente.
}

// Se ejecuta durante el procesamiento por lotes para actualizar el progreso.
eel.expose(onProcessingProgress);
function onProcessingProgress(data) {
    const fill = document.getElementById('progressFill');
    const text = document.getElementById('progressText');
    if (fill && text) {
        const pct = Math.round((data.current / data.total) * 100);
        fill.style.width = pct + '%';
        text.textContent = `Procesando ${data.current} de ${data.total}: ${data.name}`;
    }
}
