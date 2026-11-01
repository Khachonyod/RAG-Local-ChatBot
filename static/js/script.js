/* static/js/script.js */
let currentSessionId = null;
let currentSessionReady = false;
let sessionSelection = 0;
let isSending = false;
let vecWeight = 0.7;

// ==================== UTILITIES ====================
const getElement = (id) => {
    const element = document.getElementById(id);
    if (!element) throw new Error(`ไม่พบองค์ประกอบ #${id}`);
    return element;
};

function getErrorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}

// ==================== THEME MANAGEMENT ====================
function initTheme() {
    const saved = localStorage.getItem('rag-theme');
    // ถ้าไม่เคยเลือก ให้ตรวจ OS preference
    const preferred = saved || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(preferred);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    setTheme(current === 'dark' ? 'light' : 'dark');
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('rag-theme', theme);

    const icon = document.getElementById('theme-icon');
    if (icon) {
        icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    }
}

// ==================== TOAST NOTIFICATIONS ====================
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: 'bi-check-circle-fill',
        error: 'bi-x-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        info: 'bi-info-circle-fill'
    };

    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;

    const icon = document.createElement('i');
    icon.className = `bi ${icons[type] || icons.info} toast-icon`;

    const msg = document.createElement('span');
    msg.className = 'toast-message';
    msg.textContent = message;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    closeBtn.addEventListener('click', () => dismissToast(toast));

    toast.append(icon, msg, closeBtn);
    container.appendChild(toast);

    // Auto dismiss
    const timer = setTimeout(() => dismissToast(toast), duration);
    toast._timer = timer;
}

function dismissToast(toast) {
    if (!toast || !toast.parentElement) return;
    clearTimeout(toast._timer);
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
}

// ==================== UI STATE MANAGEMENT ====================
const uiState = (enabled) => {
    getElement('query-input').disabled = !enabled;
    getElement('send-btn').disabled = !enabled || isSending;
    getElement('model-selector').classList.toggle('d-none', !enabled);
    getElement('export-btn').classList.toggle('d-none', !enabled);
    getElement('append-btn').classList.toggle('d-none', !enabled);
    getElement('weight-control-wrapper').classList.toggle('d-none', !enabled);
    if (enabled) getElement('query-input').focus();
};

// ==================== TEXT HELPERS ====================
function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function appendHighlightedText(container, text, terms) {
    const safeText = typeof text === 'string' ? text : String(text ?? '');
    const uniqueTerms = [...new Set(
        (Array.isArray(terms) ? terms : [])
            .filter(term => typeof term === 'string' && term.length >= 2)
    )].sort((a, b) => b.length - a.length);

    if (!uniqueTerms.length) {
        container.textContent = safeText;
        return;
    }

    const pattern = new RegExp(uniqueTerms.map(escapeRegex).join('|'), 'gi');
    let lastIndex = 0;
    for (const match of safeText.matchAll(pattern)) {
        const index = match.index;
        container.append(document.createTextNode(safeText.slice(lastIndex, index)));
        const mark = document.createElement('mark');
        mark.className = 'hl-match';
        mark.textContent = match[0];
        container.append(mark);
        lastIndex = index + match[0].length;
    }
    container.append(document.createTextNode(safeText.slice(lastIndex)));
}

// ==================== SOURCE DISPLAY ====================
function appendSources(container, pages = [], chunks = [], queryTerms = []) {
    if (Array.isArray(pages) && pages.length) {
        const references = document.createElement('div');
        references.className = 'references-bar';

        const icon = document.createElement('i');
        icon.className = 'bi bi-journal-bookmark-fill';
        icon.style.color = 'var(--primary)';
        const label = document.createElement('b');
        label.textContent = ' อ้างอิง: ';
        references.append(icon, label);

        pages.forEach(page => {
            const badge = document.createElement('span');
            badge.className = 'page-badge';
            badge.textContent = `หน้า ${page}`;
            references.append(badge);
        });
        container.append(references);
    }

    if (Array.isArray(chunks) && chunks.length) {
        const details = document.createElement('details');
        details.className = 'source-details';
        const summary = document.createElement('summary');
        const searchIcon = document.createElement('i');
        searchIcon.className = 'bi bi-search me-1';
        summary.append(searchIcon, document.createTextNode(`ดูข้อความต้นฉบับ (${chunks.length} chunks)`));
        const chunkList = document.createElement('div');
        chunkList.className = 'mt-2';

        chunks.forEach(chunk => {
            const card = document.createElement('div');
            card.className = 'source-chunk-card';

            const heading = document.createElement('div');
            heading.className = 'fw-bold mb-1';
            heading.style.color = 'var(--primary)';
            heading.style.fontSize = '0.8rem';
            heading.append(document.createTextNode(`${chunk.filename ?? ''} (หน้า ${chunk.page ?? ''}`));

            if (chunk.score !== undefined && chunk.score !== null) {
                const score = document.createElement('span');
                const scoreValue = Number.parseFloat(chunk.score);
                const badgeClass = scoreValue >= 70 ? 'high' : scoreValue >= 40 ? 'medium' : 'low';
                score.className = `score-badge ${badgeClass}`;
                score.title = 'ความแม่นยำ (ยิ่งมากยิ่งแปลว่าคำถามตรงกับเนื้อหา)';
                score.textContent = `${chunk.score}`;
                heading.append(score);
            }
            heading.append(document.createTextNode(')'));

            const content = document.createElement('div');
            content.style.cssText = 'white-space: pre-wrap; color: var(--text-secondary); font-size: 0.78rem; margin-top: 4px;';
            appendHighlightedText(content, chunk.content, queryTerms);
            card.append(heading, content);
            chunkList.append(card);
        });

        details.append(summary, chunkList);
        container.append(details);
    }
}

// ==================== MESSAGE RENDERING ====================
function addCopyButton(msgDiv) {
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.title = 'คัดลอกข้อความ';
    btn.innerHTML = '<i class="bi bi-clipboard"></i>';
    btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const textEl = msgDiv.querySelector('.stream-text') || msgDiv.querySelector('span');
        const text = textEl ? textEl.textContent : '';
        try {
            await navigator.clipboard.writeText(text);
            btn.innerHTML = '<i class="bi bi-check2"></i>';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.innerHTML = '<i class="bi bi-clipboard"></i>';
                btn.classList.remove('copied');
            }, 2000);
        } catch {
            showToast('ไม่สามารถคัดลอกข้อความได้', 'error');
        }
    });
    msgDiv.appendChild(btn);
}

function appendMsg(role, text, pages = [], chunks = [], queryTerms = []) {
    // ซ่อน empty state ทันทีที่มีข้อความ
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    const box = getElement('chat-box');
    const div = document.createElement('div');
    const normalizedRole = role === 'user' ? 'user' : 'ai';
    div.className = `msg ${normalizedRole}`;

    if (normalizedRole === 'ai') {
        const aiIcon = document.createElement('span');
        aiIcon.className = 'ai-icon';
        aiIcon.innerHTML = '<i class="bi bi-robot"></i>';
        div.append(aiIcon);
    }

    const content = document.createElement('span');
    content.style.whiteSpace = 'pre-wrap';
    content.textContent = typeof text === 'string' ? text : String(text ?? '');
    div.append(content);

    if (normalizedRole === 'ai') {
        appendSources(div, pages, chunks, queryTerms);
        addCopyButton(div);
    }

    box.append(div);
    box.scrollTop = box.scrollHeight;
}

// ==================== API COMMUNICATIONS ====================
async function fetchJson(url, options) {
    const response = await fetch(url, options);
    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error(`เซิร์ฟเวอร์ตอบกลับไม่ถูกต้อง (HTTP ${response.status})`);
    }
    if (!response.ok || !data || data.ok !== true) {
        throw new Error(data && data.error ? data.error : `คำขอล้มเหลว (HTTP ${response.status})`);
    }
    return data;
}

// ==================== SESSION MANAGEMENT ====================
async function loadSessions() {
    try {
        const data = await fetchJson('/api/sessions');
        renderSessionList(Array.isArray(data.sessions) ? data.sessions : []);
    } catch (error) {
        console.error('Error loading sessions:', error);
    }
}

function renderSessionList(sessions) {
    const listDiv = getElement('session-list');
    listDiv.replaceChildren();

    sessions.forEach(session => {
        const item = document.createElement('div');
        item.className = `session-item ${session.id === currentSessionId ? 'session-active' : ''}`;
        item.setAttribute('role', 'listitem');
        item.addEventListener('click', () => selectSession(session.id));

        const title = document.createElement('div');
        title.style.cssText = 'overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80%;';
        const fileIcon = document.createElement('i');
        fileIcon.className = 'bi bi-file-earmark-text me-2';
        title.append(fileIcon, document.createTextNode(
            Array.isArray(session.filenames) ? session.filenames.join(', ') : ''
        ));

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn-delete-session';
        deleteButton.setAttribute('aria-label', 'ลบห้องสนทนา');
        deleteButton.innerHTML = '<i class="bi bi-trash3"></i>';
        deleteButton.addEventListener('click', event => deleteSession(session.id, event));

        item.append(title, deleteButton);
        listDiv.append(item);
    });
}

async function selectSession(sessionId) {
    const selection = ++sessionSelection;
    currentSessionId = sessionId;
    currentSessionReady = false;
    uiState(false);
    void loadSessions();

    try {
        const data = await fetchJson(`/api/history/${encodeURIComponent(sessionId)}`);
        if (selection !== sessionSelection) return;

        const sessionHasError = typeof data.status === 'string' && data.status.startsWith('error');
        currentSessionReady = data.status === 'ready';

        // อัปเดตหัวข้อ navbar
        const title = getElement('current-doc-title');
        title.replaceChildren();

        const badge = document.createElement('span');
        if (currentSessionReady) {
            badge.className = 'status-badge active';
            badge.textContent = 'ใช้งานอยู่';
        } else if (sessionHasError) {
            badge.className = 'status-badge error';
            badge.textContent = 'เกิดข้อผิดพลาด';
        } else {
            badge.className = 'status-badge processing';
            badge.textContent = 'กำลังประมวลผล';
        }

        const description = document.createElement('span');
        description.className = 'doc-title';
        description.textContent = `${Array.isArray(data.filenames) ? data.filenames.length : 0} เอกสารในระบบ`;
        title.append(badge, description);

        // แสดงประวัติแชท
        const chatBox = getElement('chat-box');
        chatBox.replaceChildren();
        const history = Array.isArray(data.history) ? data.history : [];

        if (!history.length) {
            appendMsg('ai', currentSessionReady
                ? 'พร้อมตอบคำถามแล้วครับ ✨'
                : sessionHasError ? `เกิดข้อผิดพลาด: ${data.status}` : 'กำลังประมวลผลเอกสาร กรุณารอสักครู่...');
        } else {
            history.forEach(message => appendMsg(
                message.role, message.content, message.pages, message.chunks, message.query_terms
            ));
        }
        uiState(currentSessionReady);
    } catch (error) {
        if (selection !== sessionSelection) return;
        console.error('Error selecting session:', error);
        showToast(`เปิดห้องสนทนาไม่สำเร็จ: ${getErrorMessage(error)}`, 'error');
        currentSessionId = null;
        currentSessionReady = false;
        uiState(false);
    }
}

// ==================== FILE PICKING ====================
async function pickFile(isAppend = false) {
    if (isAppend && !currentSessionId) return;
    const previousSessionId = currentSessionId;

    try {
        if (!window.pywebview || !window.pywebview.api) {
            throw new Error('ไม่สามารถเชื่อมต่อกับตัวเลือกไฟล์ได้');
        }
        const paths = await window.pywebview.api.pick_file();
        if (!paths || !paths.length) return;

        if (!isAppend) {
            currentSessionId = null;
            currentSessionReady = false;
            getElement('chat-box').replaceChildren();
        }
        appendMsg('ai', 'กำลังประมวลผลฐานข้อมูลเอกสาร...');
        uiState(false);

        const data = await fetchJson('/api/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paths, session_id: isAppend ? currentSessionId : null })
        });
        currentSessionId = data.session_id;
        currentSessionReady = false;
        await loadSessions();
        await checkStatus(data.session_id);
    } catch (error) {
        console.error('Error uploading file:', error);
        showToast(`อัปโหลดไฟล์ไม่สำเร็จ: ${getErrorMessage(error)}`, 'error');
        if (previousSessionId) {
            await selectSession(previousSessionId);
        } else {
            currentSessionId = null;
            currentSessionReady = false;
            getElement('chat-box').replaceChildren();
            showEmptyState();
            uiState(false);
        }
    }
}

async function checkStatus(sessionId) {
    while (currentSessionId === sessionId) {
        const data = await fetchJson(`/api/history/${encodeURIComponent(sessionId)}`);
        if (data.status === 'ready') {
            await selectSession(sessionId);
            if (currentSessionId === sessionId) {
                showToast('วิเคราะห์เอกสารสำเร็จ! 🎉', 'success');
            }
            return;
        }
        if (typeof data.status === 'string' && data.status.startsWith('error')) {
            appendMsg('ai', `เกิดข้อผิดพลาด: ${data.status}`);
            showToast('เกิดข้อผิดพลาดในการประมวลผลเอกสาร', 'error');
            return;
        }
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
}

// ==================== CHAT / STREAMING ====================
async function send() {
    if (isSending || !currentSessionId || !currentSessionReady) return;
    const input = getElement('query-input');
    const query = input.value.trim();
    if (!query) return;

    appendMsg('user', query);
    input.value = '';
    isSending = true;
    uiState(false);

    const box = getElement('chat-box');
    const aiDiv = document.createElement('div');
    aiDiv.className = 'msg ai';

    const aiIcon = document.createElement('span');
    aiIcon.className = 'ai-icon';
    aiIcon.innerHTML = '<i class="bi bi-robot"></i>';
    aiDiv.append(aiIcon);

    const typing = document.createElement('div');
    typing.className = 'typing-indicator stream-typing';
    for (let index = 0; index < 3; index += 1) typing.append(document.createElement('span'));

    const textSpan = document.createElement('span');
    textSpan.className = 'stream-text';
    textSpan.style.whiteSpace = 'pre-wrap';

    aiDiv.append(typing, textSpan);
    box.appendChild(aiDiv);
    box.scrollTop = box.scrollHeight;
    let fullText = '';
    let streamCompleted = false;

    try {
        const res = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                session_id: currentSessionId,
                model: getElement('model-selector').value,
                vec_weight: vecWeight
            })
        });

        if (!res.ok || !res.body) {
            let message = `เชื่อมต่อสตรีมไม่สำเร็จ (HTTP ${res.status})`;
            try {
                const errorData = await res.json();
                if (errorData.error) message = errorData.error;
            } catch {
                // Keep the HTTP status message when the server did not return JSON.
            }
            throw new Error(message);
        }

        await consumeEventStream(res, payload => {
            if (payload.error) throw new Error(payload.error);
            if (payload.token !== undefined && payload.token !== null) {
                typing.remove();
                fullText += String(payload.token);
                textSpan.textContent = fullText;
                box.scrollTop = box.scrollHeight;
            }
            if (payload.done) {
                typing.remove();
                appendSources(aiDiv, payload.pages, payload.chunks, payload.query_terms);
                addCopyButton(aiDiv);
                streamCompleted = true;
                box.scrollTop = box.scrollHeight;
            }
        });
        if (!streamCompleted) throw new Error('การตอบกลับถูกตัดก่อนจบ');
    } catch (error) {
        typing.remove();
        textSpan.textContent += `${fullText ? '\n' : ''}เกิดข้อผิดพลาด: ${getErrorMessage(error)}`;
        console.error('Error sending message:', error);
        showToast(`เกิดข้อผิดพลาด: ${getErrorMessage(error)}`, 'error');
    } finally {
        isSending = false;
        uiState(currentSessionReady);
    }
}

async function consumeEventStream(response, onPayload) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const processEvent = (eventText) => {
        const data = eventText.split(/\r?\n/)
            .filter(line => line.startsWith('data:'))
            .map(line => line.slice(5).replace(/^ /, ''))
            .join('\n');
        if (!data) return;
        onPayload(JSON.parse(data));
    };

    while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer)) !== null) {
            processEvent(buffer.slice(0, boundary.index));
            buffer = buffer.slice(boundary.index + boundary[0].length);
        }
        if (done) break;
    }

    if (buffer.trim()) processEvent(buffer);
}

// ==================== EMPTY STATE ====================
function showEmptyState() {
    const box = getElement('chat-box');
    const existing = document.getElementById('empty-state');
    if (existing) return;

    const div = document.createElement('div');
    div.className = 'empty-state';
    div.id = 'empty-state';
    div.innerHTML = `
        <div class="empty-state-icon"><i class="bi bi-file-earmark-text"></i></div>
        <h3>เริ่มต้นใช้งาน</h3>
        <p>อัปโหลดเอกสารทางด้านซ้ายเพื่อเริ่มถาม-ตอบกับ AI ระบบรองรับไฟล์หลากหลายรูปแบบ</p>
        <div class="supported-formats">
            <span class="format-tag">PDF</span>
            <span class="format-tag">DOCX</span>
            <span class="format-tag">TXT</span>
            <span class="format-tag">CSV</span>
            <span class="format-tag">Excel</span>
        </div>
    `;
    box.appendChild(div);
}

// ==================== DELETE SESSION ====================
let sessionToDelete = null;
let deleteModalInstance = null;

function deleteSession(id, e) {
    e.stopPropagation();
    sessionToDelete = id;
    if (!deleteModalInstance) {
        const modal = getElement('deleteConfirmModal');
        if (!window.bootstrap || !window.bootstrap.Modal) {
            showToast('ไม่สามารถเปิดหน้าต่างยืนยันการลบได้', 'error');
            return;
        }
        deleteModalInstance = new window.bootstrap.Modal(modal);
    }
    deleteModalInstance.show();
}

// ==================== EXPORT CHAT ====================
async function exportChat() {
    if (!currentSessionId) return;
    try {
        if (!window.pywebview || !window.pywebview.api) {
            throw new Error('ไม่สามารถเชื่อมต่อกับตัวบันทึกไฟล์ได้');
        }
        if (await window.pywebview.api.save_chat(currentSessionId)) {
            showToast('บันทึกไฟล์ PDF สำเร็จ!', 'success');
        }
    } catch (error) {
        console.error('Error exporting chat:', error);
        showToast(`ส่งออกแชทไม่สำเร็จ: ${getErrorMessage(error)}`, 'error');
    }
}

// ==================== INITIALIZATION ====================
window.addEventListener('pywebviewready', () => {
    const btn = getElement('upload-btn');
    btn.disabled = false;
    btn.innerHTML = "<i class='bi bi-file-earmark-plus'></i> สร้างห้องใหม่";
});

document.addEventListener('DOMContentLoaded', () => {
    // เริ่มต้น theme
    initTheme();

    // โหลด sessions
    loadSessions();

    // Weight slider
    getElement('weight-slider').addEventListener('input', (event) => {
        const semanticPct = Number.parseInt(event.target.value, 10);
        if (!Number.isFinite(semanticPct)) return;
        vecWeight = semanticPct / 100;
        getElement('weight-display').textContent = `Vector ${semanticPct}% / BM25 ${100 - semanticPct}%`;
    });

    // Enter key to send
    getElement('query-input').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            send();
        }
    });

    // Delete confirmation handler
    const confirmBtn = document.getElementById('confirm-delete-btn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            if (!sessionToDelete) return;

            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>กำลังลบ...';
            confirmBtn.disabled = true;
            let deleted = false;

            try {
                await fetchJson(`/api/sessions/${encodeURIComponent(sessionToDelete)}`, { method: 'DELETE' });
                deleted = true;
                showToast('ลบห้องสนทนาสำเร็จ', 'success');
                if (currentSessionId === sessionToDelete) {
                    currentSessionId = null;
                    currentSessionReady = false;
                    sessionSelection += 1;
                    location.reload();
                    return;
                }
                await loadSessions();
            } catch (error) {
                console.error('Error deleting session:', error);
                showToast(`ลบห้องสนทนาไม่สำเร็จ: ${getErrorMessage(error)}`, 'error');
            } finally {
                if (deleted && deleteModalInstance) deleteModalInstance.hide();
                if (deleted) sessionToDelete = null;
                confirmBtn.innerHTML = 'ลบถาวร';
                confirmBtn.disabled = false;
            }
        });
    }
});