/**
 * App.js — Lógica principal de la interfaz de escritorio.
 * Manejo del DOM, navegación entre pantallas, y comunicación con Python vía Eel.
 */

// ─── Estado ───────────────────────────────────────────
let selectedWorkspaceId = null;
let selectedWorkspaceName = null;
let sessionActive = false;
let refreshInterval = null;
let capturePaused = false;

// ─── Inicialización ───────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    await checkStatus();
    // Comprueba si ya hay una sesión iniciada.
    const user = await eel.get_current_user()();
    if (user) {
        showDashboard(user);
    }
});

// ─── Consulta de estado ───────────────────────────────
async function checkStatus() {
    try {
        const status = await eel.get_app_status()();
        const badge = document.getElementById('statusBadge');
        if (status.online) {
            badge.textContent = 'Conectado';
            badge.className = 'status-badge status-online';
        } else {
            badge.textContent = 'Sin conexión (Offline)';
            badge.className = 'status-badge status-offline';
        }
        updateCapturePauseState(status.capture_paused, status.pause_reason);
    } catch (e) {
        console.error('Status check failed:', e);
    }
}

// ─── Inicio de sesión ─────────────────────────────────
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const totpCode = document.getElementById('loginTotpCode').value.replace(/\D/g, '').slice(0, 6);
    const errorEl = document.getElementById('loginError');
    const btn = document.getElementById('btnLogin');

    btn.textContent = 'Conectando...';
    btn.disabled = true;
    errorEl.classList.add('hidden');

    try {
        const result = await eel.login(email, password, totpCode)();
        if (result.success) {
            showDashboard(result.user);
        } else {
            errorEl.textContent = result.error;
            errorEl.classList.remove('hidden');
        }
    } catch (err) {
        errorEl.textContent = 'Error de conexión con el servidor.';
        errorEl.classList.remove('hidden');
    }

    btn.textContent = 'Iniciar Sesión';
    btn.disabled = false;
}

// ─── Cierre de sesión ─────────────────────────────────
async function handleLogout() {
    if (sessionActive) {
        if (!confirm('Tienes una sesión activa. ¿Deseas cerrar sesión de todas formas?')) return;
    }

    try {
        const result = await eel.logout()();
        if (!result.success) {
            alert(result.error || 'No se pudo cerrar sesión.');
            return;
        }
    } catch (e) {
        console.error('Logout error:', e);
        return;
    }

    sessionActive = false;
    selectedWorkspaceId = null;
    selectedWorkspaceName = null;
    if (refreshInterval) clearInterval(refreshInterval);

    // Restablece todas las pantallas.
    document.getElementById('screenDashboard').classList.add('hidden');
    document.getElementById('panelSession').classList.add('hidden');
    document.getElementById('panelProgress').classList.add('hidden');
    document.getElementById('panelResults').classList.add('hidden');
    document.getElementById('panelWorkspaces').classList.remove('hidden');
    document.getElementById('screenLogin').classList.remove('hidden');
    document.getElementById('userDisplay').classList.add('hidden');
    document.getElementById('btnLogout').classList.add('hidden');

    // Limpia los campos del formulario.
    document.getElementById('loginEmail').value = '';
    document.getElementById('loginPassword').value = '';
    document.getElementById('loginTotpCode').value = '';
}

// ─── Muestra el panel principal ───────────────────────
async function showDashboard(user) {
    document.getElementById('screenLogin').classList.add('hidden');
    document.getElementById('screenDashboard').classList.remove('hidden');
    document.getElementById('userDisplay').textContent = user.name;
    document.getElementById('userDisplay').classList.remove('hidden');
    document.getElementById('btnLogout').classList.remove('hidden');

    await loadWorkspaces();
    await checkStatus();
}

// ─── Espacios de trabajo ──────────────────────────────
async function loadWorkspaces() {
    const workspaces = await eel.get_workspaces()();
    const grid = document.getElementById('workspaceGrid');

    if (!workspaces || workspaces.length === 0) {
        grid.innerHTML = '<p class="text-muted">No tienes espacios de trabajo asignados. Contacta al administrador.</p>';
        return;
    }

    grid.innerHTML = workspaces.map(ws => `
        <div class="workspace-item ${selectedWorkspaceId === ws.id ? 'selected' : ''}"
             onclick="selectWorkspace('${ws.id}', '${ws.name}')">
            <h3>${ws.name}</h3>
            <p>${ws.cloudPath || 'Sin ruta'}</p>
        </div>
    `).join('');

    // Añade el botón de inicio si hay un espacio seleccionado.
    if (selectedWorkspaceId) {
        const existing = document.getElementById('btnStartSession');
        if (!existing) {
            const btn = document.createElement('button');
            btn.id = 'btnStartSession';
            btn.className = 'btn btn-primary mt-2';
            btn.textContent = '▶ Iniciar Sesión de Escaneo';
            btn.onclick = handleStartSession;
            document.getElementById('panelWorkspaces').appendChild(btn);
        }
    }
}

// RF-03
async function selectWorkspace(id, name) {
    const result = await eel.select_workspace(id, name)();
    if (result.success) {
        selectedWorkspaceId = id;
        selectedWorkspaceName = name;
        await loadWorkspaces();
    }
}

// ─── Sesión ───────────────────────────────────────────
// RF-03
async function handleStartSession() {
    if (!selectedWorkspaceId) {
        alert('Selecciona un espacio de trabajo primero.');
        return;
    }

    const result = await eel.start_session()();
    if (result.success) {
        sessionActive = true;
        document.getElementById('panelWorkspaces').classList.add('hidden');
        document.getElementById('panelSession').classList.remove('hidden');
        document.getElementById('sessionWorkspaceName').textContent = selectedWorkspaceName;
        document.getElementById('watchFolderPath').textContent = result.watch_folder;

        // Inicia la actualización periódica.
        refreshInterval = setInterval(refreshSessionFiles, 3000);
    } else {
        alert(result.error);
    }
}

async function handleEndSession() {
    if (!confirm('¿Cerrar la sesión? Se procesarán y subirán todos los documentos pendientes.')) return;

    // Muestra el panel de progreso.
    document.getElementById('panelSession').classList.add('hidden');
    document.getElementById('panelProgress').classList.remove('hidden');

    const result = await eel.end_session()();

    if (!result.success) {
        document.getElementById('panelProgress').classList.add('hidden');
        document.getElementById('panelSession').classList.remove('hidden');
        alert(result.error || 'No se pudo cerrar la sesión.');
        return;
    }

    // Muestra los resultados.
    document.getElementById('panelProgress').classList.add('hidden');
    document.getElementById('panelResults').classList.remove('hidden');

    const content = document.getElementById('resultsContent');
    content.innerHTML = `
        <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:10px; text-align:center;">
            <div class="card">
                <div style="font-size:24px; font-weight:bold; color:#059669;">${result.processed || 0}</div>
                <div class="text-muted">Procesados</div>
            </div>
            <div class="card">
                <div style="font-size:24px; font-weight:bold; color:#2563eb;">${result.uploaded || 0}</div>
                <div class="text-muted">Subidos</div>
            </div>
            <div class="card">
                <div style="font-size:24px; font-weight:bold; color:#dc2626;">${result.errors || 0}</div>
                <div class="text-muted">Errores</div>
            </div>
        </div>
        <p class="text-muted mt-2">Logs sincronizados: ${result.logs_synced || 0}</p>
    `;

    sessionActive = false;
    if (refreshInterval) clearInterval(refreshInterval);
}

// ─── Importación de archivos ──────────────────────────
async function handleImportFiles() {
    try {
        const result = await eel.pick_and_import_files()();
        if (result.success) {
            if (result.count > 0) {
                alert(`✅ ${result.count} archivo(s) importado(s) correctamente.`);
                refreshSessionFiles();
            } else {
                // El usuario canceló el cuadro de diálogo.
            }
        } else {
            alert(`Error: ${result.error}`);
        }
    } catch (e) {
        alert('Error al importar archivos. Asegúrate de que la aplicación tiene permisos.');
        console.error('Import error:', e);
    }
}

// ─── Exportación de archivos / escáner ────────────────

async function openScannerModal() {
    if (!sessionActive) {
        alert('Debes iniciar sesión de escaneo primero.');
        return;
    }
    
    document.getElementById('scannerModal').classList.remove('hidden');
    const select = document.getElementById('scannerSelect');
    select.innerHTML = '<option value="">Buscando dispositivos...</option>';
    document.getElementById('btnConfirmScan').disabled = true;

    try {
        const scanners = await eel.get_scanners()();
        if (scanners && scanners.length > 0) {
            select.innerHTML = scanners.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
            // En Windows, se puede dejar vacío el selector para que WIA muestre su propio cuadro si el usuario lo prefiere.
            select.innerHTML += '<option value="">Selección del sistema (por defecto)</option>';
            document.getElementById('btnConfirmScan').disabled = false;
        } else {
            select.innerHTML = '<option value="">No se encontraron escáneres, intenta selección del sistema</option>';
            document.getElementById('btnConfirmScan').disabled = false;
        }
    } catch (e) {
        select.innerHTML = '<option value="">Error al buscar dispositivos</option>';
        document.getElementById('btnConfirmScan').disabled = false;
    }
}

function closeScannerModal() {
    document.getElementById('scannerModal').classList.add('hidden');
}

async function executeScan() {
    closeScannerModal();
    
    // Deshabilita la interfaz durante el escaneo.
    const btn = document.getElementById('btnScanDoc');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Escaneando...';
    }

    const deviceId = document.getElementById('scannerSelect').value || null;

    try {
        const result = await eel.scan_document(deviceId)();
        if (result.success) {
            refreshSessionFiles();
        } else {
            updateCapturePauseState(result.paused, result.pause_reason || result.error);
            alert(`Error al escanear: ${result.error}`);
        }
    } catch (e) {
        alert('Error inesperado al invocar el escaner.');
        console.error('Scan error:', e);
    } finally {
        if (btn) {
            btn.disabled = capturePaused;
            btn.textContent = '🖨 Escanear Físico';
        }
    }
}

// RF-05
async function handleResumeCapture() {
    const button = document.getElementById('btnResumeCapture');
    if (button) button.disabled = true;

    try {
        const result = await eel.resume_capture()();
        updateCapturePauseState(result.paused, result.reason || result.error);
        if (!result.success) {
            alert(result.error || 'No se pudo reanudar la captura.');
        } else if (result.processed > 0) {
            await refreshSessionFiles();
        }
    } catch (error) {
        alert('No se pudo reanudar la captura.');
    } finally {
        if (button) button.disabled = false;
    }
}

// RF-05
function updateCapturePauseState(paused, reason) {
    const alert = document.getElementById('capturePausedAlert');
    const reasonElement = document.getElementById('capturePauseReason');
    const scanButton = document.getElementById('btnScanDoc');
    if (!alert || !reasonElement) return;

    capturePaused = Boolean(paused);
    alert.classList.toggle('hidden', !capturePaused);
    reasonElement.textContent = reason || 'Revisa el escáner antes de continuar.';
    if (scanButton) scanButton.disabled = capturePaused;
}

async function handleExportFiles() {
    try {
        const result = await eel.export_files()();
        if (result.success) {
            if (result.count > 0) {
                alert(`✅ ${result.count} archivo(s) exportado(s) a:\n${result.destination}`);
            } else {
                // El usuario canceló o no hay archivos.
            }
        } else {
            alert(`Error: ${result.error}`);
        }
    } catch (e) {
        alert('Error al exportar archivos.');
        console.error('Export error:', e);
    }
}

// ─── Navegación por pestañas ──────────────────────────
function switchTab(tabName) {
    // Actualiza los botones de las pestañas.
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');

    // Muestra u oculta el contenido de las pestañas.
    document.getElementById('tabFiles').classList.add('hidden');
    document.getElementById('tabReview').classList.add('hidden');
    document.getElementById('tabQueue').classList.add('hidden');
    document.getElementById('tab' + tabName.charAt(0).toUpperCase() + tabName.slice(1)).classList.remove('hidden');

    // Actualiza los datos.
    if (tabName === 'files') refreshSessionFiles();
    if (tabName === 'review') refreshPendingReview();
    if (tabName === 'queue') refreshQueue();
}

// ─── Funciones de actualización ───────────────────────
async function refreshSessionFiles() {
    try {
        const status = await eel.get_app_status()();
        updateCapturePauseState(status.capture_paused, status.pause_reason);
        const files = await eel.get_session_files()();
        const tbody = document.getElementById('filesTableBody');

        if (!files || files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No hay archivos en la sesión.</td></tr>';
            return;
        }

        tbody.innerHTML = files.map(f => `
            <tr>
                <td>${f.name}</td>
                <td>${formatSize(f.size)}</td>
                <td><span class="badge badge-blue">${f.ext.toUpperCase()}</span></td>
            </tr>
        `).join('');

        updateDocCount(files.length);
    } catch (e) { /* Ignora los errores de actualización. */ }
}

// RF-08
async function refreshPendingReview() {
    try {
        const items = await eel.get_pending_review()();
        const tbody = document.getElementById('reviewTableBody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No hay documentos pendientes.</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(item => `
            <tr>
                <td>${item.original_name}</td>
                <td><span class="text-muted">${item.error_message || 'Sin detalle'}</span></td>
                <td>
                    <button class="btn btn-sm btn-primary"
                        onclick="openCorrection('${item.id}', '${item.original_name}', '${(item.error_message || '').replace(/'/g, '')}')">
                        ✏️ Corregir
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (e) { /* Ignora el error de actualización. */ }
}

async function refreshQueue() {
    try {
        const items = await eel.get_queue_items()();
        const tbody = document.getElementById('queueTableBody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Cola vacía.</td></tr>';
            return;
        }

        const statusMap = {
            'PENDING': ['Pendiente', 'badge-yellow'],
            'PENDING_REVIEW': ['Revisión', 'badge-red'],
            'PROCESSING': ['Procesando', 'badge-blue'],
            'PROCESSED': ['Pendiente de envío', 'badge-yellow'],
            'UPLOADED': ['Subido', 'badge-green'],
            'ERROR': ['Error', 'badge-red'],
        };

        tbody.innerHTML = items.map(item => {
            const [label, cls] = statusMap[item.status] || ['Desconocido', 'badge-yellow'];
            return `
                <tr>
                    <td>${item.original_name}</td>
                    <td><span class="badge ${cls}">${label}</span></td>
                    <td>${item.workspace_name || '—'}</td>
                    <td class="text-muted">${item.created_at || '—'}</td>
                </tr>
            `;
        }).join('');
    } catch (e) { /* Ignora el error de actualización. */ }
}

// ─── Funciones auxiliares ─────────────────────────────
function updateDocCount(count) {
    const el = document.getElementById('sessionDocCount');
    if (el) {
        if (typeof count === 'number') {
            el.textContent = count + ' documento' + (count !== 1 ? 's' : '');
        }
    }
}

function formatSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
}

// RF-08
function openCorrection(id, name, error) {
    window.open(`correction.html?id=${id}&name=${encodeURIComponent(name)}&error=${encodeURIComponent(error)}`, '_blank', 'width=650,height=450');
}

function resetToDashboard() {
    document.getElementById('panelResults').classList.add('hidden');
    document.getElementById('panelWorkspaces').classList.remove('hidden');
    document.getElementById('panelSession').classList.add('hidden');
    selectedWorkspaceId = null;
    selectedWorkspaceName = null;
    loadWorkspaces();
}
