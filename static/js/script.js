/* static/js/script.js */
let currentSessionId = null;

// --- Webview & Base Setup ---
window.addEventListener('pywebviewready', () => {
    const btn = document.getElementById('upload-btn');
    btn.disabled = false;
    btn.className = "btn btn-primary rounded-pill mb-2 shadow-sm py-2 fw-medium";
    btn.innerHTML = "<i class='bi bi-file-earmark-plus me-1'></i> สร้างห้องใหม่";
});
window.onload = loadSessions;

// --- Controller Interactivity Helpers ---
const uiState = (isEnabled) => {
    document.getElementById('query-input').disabled = !isEnabled;
    document.getElementById('send-btn').disabled = !isEnabled;
    document.getElementById('model-selector').classList.toggle('d-none', !isEnabled);
    document.getElementById('export-btn').classList.toggle('d-none', !isEnabled);
    document.getElementById('append-btn').classList.toggle('d-none', !isEnabled);
    if(isEnabled) document.getElementById('query-input').focus();
};

const showTyping = () => {
    const box = document.getElementById('chat-box');
    const div = document.createElement('div');
    div.id = 'typing-indicator';
    div.className = 'msg ai shadow-sm';
    div.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
};

const removeTyping = () => {
    const el = document.getElementById('typing-indicator');
    if(el) el.remove();
};

function appendMsg(role, text, pages = [], chunks = []) {
    removeTyping();
    const box = document.getElementById('chat-box');
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerHTML = `<span>${text.replace(/\n/g, '<br>')}</span>`;

    if (role === 'ai' && pages.length) {
        const badges = pages.map(p => `<span class="badge bg-light text-dark border me-1">หน้า ${p}</span>`).join('');
        div.innerHTML += `<div class="mt-3 pt-3 border-top text-secondary" style="font-size: 0.85rem;"><i class="bi bi-journal-bookmark-fill text-primary"></i> <b>อ้างอิง:</b> ${badges}</div>`;
    }

    if (role === 'ai' && chunks.length) {
        const chunksHtml = chunks.map(c => {
            let scoreHtml = '';

            if (c.score !== undefined) {
                let badgeColor = 'bg-secondary';
                if (c.score < 1.0) badgeColor = 'bg-success';
                else if (c.score < 1.3) badgeColor = 'bg-warning text-dark';
                else badgeColor = 'bg-danger';

                scoreHtml = `<span class="badge ${badgeColor} ms-2 fw-normal" style="font-size: 0.75rem;" title="L2 Distance (ยิ่งน้อยยิ่งแปลว่าคำถามตรงกับเนื้อหา)">Distance: ${c.score}</span>`;
            }

            return `<div class="border rounded p-2 mb-2 bg-white" style="font-size: 0.8rem; border-left: 3px solid var(--primary-color) !important;">
                <div class="fw-bold text-primary mb-1">${c.filename} (หน้า ${c.page} ${scoreHtml})</div>
                <div class="text-muted">${c.content.replace(/\n/g, '<br>')}</div>
            </div>`
        }).join('');

        div.innerHTML += `<details class="source-details"><summary><i class="bi bi-search me-1"></i> ดูข้อความต้นฉบับ</summary><div class="mt-2">${chunksHtml}</div></details>`;
    }
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

// --- API Communications ---
async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        const data = await res.json();
        if (data.ok) renderSessionList(data.sessions);
    } catch (err) { console.error(err); }
}

function renderSessionList(sessions) {
    const listDiv = document.getElementById('session-list');
    listDiv.innerHTML = sessions.map(s => `
        <div class="p-3 mb-2 rounded session-item d-flex justify-content-between align-items-center ${s.id === currentSessionId ? 'session-active' : 'bg-white'}" onclick="selectSession('${s.id}')">
            <div class="text-truncate" style="max-width: 80%;"><i class="bi bi-file-earmark-text me-2"></i> ${s.filenames.join(', ')}</div>
            <button class="btn btn-sm text-danger border-0 px-2" onclick="deleteSession('${s.id}', event)"><i class="bi bi-trash"></i></button>
        </div>
    `).join('');
}

async function selectSession(sessionId) {
    currentSessionId = sessionId;
    loadSessions();
    const res = await fetch(`/api/history/${sessionId}`);
    const data = await res.json();
    
    if (data.ok) {
        document.getElementById('current-doc-title').innerHTML = `<span class="badge bg-primary me-2 rounded-pill px-3 py-2 fw-normal">ใช้งานอยู่</span> <span class="text-dark fw-medium text-truncate" style="max-width: 400px;">${data.filenames.length} เอกสารในระบบ</span>`;
        document.getElementById('chat-box').innerHTML = '';
        if (!data.history.length) appendMsg('ai', 'พร้อมตอบคำถามแล้วครับ ✨');
        else data.history.forEach(msg => appendMsg(msg.role, msg.content, msg.pages, msg.chunks));
        uiState(true);
    }
}

async function pickFile(isAppend = false) {
    if (isAppend && !currentSessionId) return;
    const paths = await window.pywebview.api.pick_file();
    if (!paths || !paths.length) return;
    
    if (!isAppend) document.getElementById('chat-box').innerHTML = '';
    appendMsg('ai', 'กำลังประมวลผลฐานข้อมูลเอกสาร... <i class="bi bi-hourglass-split text-warning"></i>');
    uiState(false);

    try {
        const res = await fetch('/api/load', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ paths, session_id: isAppend ? currentSessionId : null }) });
        const data = await res.json();
        if (data.ok) checkStatus(data.session_id);
        else { alert(data.error); loadSessions(); }
    } catch (err) { alert("Error uploading file."); }
}

async function checkStatus(sessionId) {
    const res = await fetch(`/api/history/${sessionId}`);
    const data = await res.json();
    if (data.status === 'ready') {
        selectSession(sessionId);
        appendMsg('ai', 'วิเคราะห์เอกสารสำเร็จ! 🎉');
    } else if (data.status.startsWith('error')) {
        appendMsg('ai', 'เกิดข้อผิดพลาด: ' + data.status);
    } else setTimeout(() => checkStatus(sessionId), 1000);
}

async function send() {
    const input = document.getElementById('query-input');
    const query = input.value.trim();
    if (!query || !currentSessionId) return;

    appendMsg('user', query);
    input.value = '';
    uiState(false);
    showTyping();

    try {
        const res = await fetch('/api/ask', { method: 'POST', headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ query, session_id: currentSessionId, model: document.getElementById('model-selector').value }) 
        });
        const data = await res.json();
        if(data.ok) appendMsg('ai', data.answer, data.pages, data.chunks);
        else appendMsg('ai', 'เกิดข้อผิดพลาด: ' + data.error);
    } catch (err) { appendMsg('ai', 'เซิร์ฟเวอร์ไม่ตอบสนอง'); } 
    finally { uiState(true); }
}

let sesionToDelete = null;
let deleteModalInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    const confirmBtn = document.getElementById('confirm-delete-btn')
    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            if (!sessionToDelete) return;

            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>กำลังลบ...';
            confirmBtn.disabled = true;

            try {
                const res = await fetch(`/api/sessions/${sessionToDelete}`, {method: 'DELETE'});
                const data = await res.json()

                if (data.ok) {
                    if (currentSessionId === sessionToDelete) {
                        currentSessionId = null;
                        location.reload();
                    }
                    loadSessions();
                }
            } catch (err) {
                console.error("Error deleting session:", err)
            } finally {
                if (deleteModalInstance) deleteModalInstance.hide();
                sessionToDelete = null;
                confirmBtn.innerHTML = 'ลบถาวร';
                confirmBtn.disabled = true;
            }
        });
    }
});

async function deleteSession(id, e) {
    e.stopPropagation();
    sessionToDelete = id;
    if (!deleteModalInstance) {
        deleteModalInstance = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    }
    deleteModalInstance.show();
}

async function exportChat() {
    if (currentSessionId && await window.pywebview.api.save_chat(currentSessionId)) alert("บันทึกสำเร็จ!");
}

document.getElementById('query-input').addEventListener('keypress', e => { if(e.key === 'Enter') send(); });