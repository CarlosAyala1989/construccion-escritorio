/**
 * Eel Bridge — Callbacks de Python → JavaScript (Patrón Observer).
 * Python emite eventos, JS los recibe y actualiza la UI.
 */

// Called when a new file is detected in the watch folder
eel.expose(onFileDetected);
function onFileDetected(data) {
    console.log('[BRIDGE] File detected:', data.name);
    refreshSessionFiles();
    updateDocCount();
}

// Called when a document finishes processing
eel.expose(onDocumentProcessed);
function onDocumentProcessed(data) {
    console.log('[BRIDGE] Document processed:', data.name, 'Encryption:', data.encryption);
    // Could show a toast notification here
}

// Called during batch processing to update progress
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
