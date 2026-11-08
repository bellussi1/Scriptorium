/**
 * Persistent literary queue view and the two controlled queue actions:
 * enqueueing books from the Calibre inventory and reordering pending entries.
 *
 * The queue is written by the local CLI/wrapper. This module never starts,
 * pauses or validates a translation job.
 */

import { t } from '../i18n/i18n.js';

const QUEUE_URL = '/api/literary/queue';
const LIBRARY_URL = '/api/literary/library';
const ADD_URL = '/api/literary/queue/books';
const MODELS_URL = '/api/models?provider=ollama';
const REFRESH_MS = 10000;
const PROVIDERS = ['ollama', 'openai', 'gemini', 'deepseek', 'openrouter', 'mistral', 'poe', 'nim'];

const STATUS_KEYS = {
    pending: 'status_pending',
    translating: 'status_translating',
    preparing: 'status_preparing',
    completed: 'status_completed',
    failed: 'status_failed',
    needs_review: 'status_needs_review',
    paused: 'status_paused',
    validating: 'status_validating',
    reviewing: 'status_reviewing',
};

let refreshTimer = null;
let libraryBooks = [];
let lastBooks = [];
let availableModels = [];
let editingBookId = null;
let modelsLoaded = false;
let modelsLoading = false;
let actionInFlight = false;

function byId(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));
}

function formatNumber(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat().format(number);
}

function formatDate(value) {
    if (!value) return '—';
    const raw = String(value);
    const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T') + 'Z';
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return escapeHtml(raw);
    return date.toLocaleString();
}

function statusKey(book) {
    return String(book.job_state || book.status || 'pending').toLowerCase();
}

function statusLabel(book) {
    const key = statusKey(book);
    return t(`queue:${STATUS_KEYS[key] || 'status_unknown'}`);
}

function modelLabel(book) {
    const model = String(book.model || '');
    if (!model) return '—';
    return model.split('/').pop();
}

function modelOptionsFor(current) {
    const names = [];
    if (current) names.push(current);
    for (const model of availableModels) {
        if (model && !names.includes(model)) names.push(model);
    }
    const options = names
        .map((model) => `<option value="${escapeHtml(model)}" ${model === current ? 'selected' : ''}>${escapeHtml(model)}</option>`)
        .join('');
    return `${options}<option value="__custom__">${escapeHtml(t('queue:custom_model'))}</option>`;
}

function modelCell(book) {
    if (book.status !== 'pending') {
        return `<span title="${escapeHtml(book.model || '')}">${escapeHtml(modelLabel(book))}</span>`;
    }
    const current = String(book.model || '');
    const label = escapeHtml(t('queue:change_model'));
    return `
        <select class="queue-model-select" data-model-book-id="${book.id}"
                title="${label}" aria-label="${label}">
            ${modelOptionsFor(current)}
        </select>
    `;
}

function refreshModelSelects() {
    for (const select of document.querySelectorAll('#queueTableBody [data-model-book-id]')) {
        const bookId = Number(select.dataset.modelBookId);
        const book = lastBooks.find((item) => item.id === bookId);
        if (!book) continue;
        select.innerHTML = modelOptionsFor(String(book.model || ''));
    }
}

function progressCell(book) {
    const total = Number(book.total_chapters || 0);
    const current = Number(book.current_chapter || 0);
    if (total <= 0) return '<span class="queue-muted">—</span>';
    const pct = Math.max(0, Math.min(100, Math.round((current / total) * 100)));
    const chunks = t('queue:chunks', { current, total });
    return `
        <div class="queue-progress" title="${escapeHtml(chunks)}">
            <span style="width: ${pct}%"></span>
        </div>
        <span class="queue-progress-text">${escapeHtml(chunks)} · ${pct}%</span>
    `;
}

function renderSummary(data) {
    const summary = data.summary || {};
    const byStatus = summary.by_status || {};
    const cards = [
        [t('queue:books'), formatNumber(summary.books)],
        [t('queue:words'), formatNumber(summary.words)],
        [t('queue:translating'), formatNumber(byStatus.translating || 0)],
        [t('queue:needs_review'), formatNumber(byStatus.needs_review || 0)],
    ];
    byId('queueSummary').innerHTML = cards
        .map(([label, value]) => `
            <div class="queue-stat">
                <span class="queue-stat-value">${escapeHtml(value)}</span>
                <span class="queue-stat-label">${escapeHtml(label)}</span>
            </div>
        `)
        .join('');
    byId('queueUpdatedAt').textContent = data.generated_at
        ? t('queue:updated', { time: formatDate(data.generated_at) })
        : '';
}

function actionButtons(book, isFirst, isLast) {
    const buttons = [];
    if (book.artifact) {
        const downloadLabel = escapeHtml(t('queue:download'));
        buttons.push(`
            <button type="button" class="queue-move-btn queue-download-btn"
                    data-download-book-id="${book.id}"
                    data-download-name="${escapeHtml(book.artifact.filename || '')}"
                    title="${downloadLabel}" aria-label="${downloadLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">download</span>
            </button>
        `);
    }
    if (book.status === 'pending') {
        const upLabel = escapeHtml(t('queue:move_up'));
        const downLabel = escapeHtml(t('queue:move_down'));
        buttons.push(`
            <button type="button" class="queue-move-btn" data-move="up" data-book-id="${book.id}"
                    title="${upLabel}" aria-label="${upLabel}" ${isFirst ? 'disabled' : ''}>
                <span class="material-symbols-outlined" aria-hidden="true">arrow_upward</span>
            </button>
            <button type="button" class="queue-move-btn" data-move="down" data-book-id="${book.id}"
                    title="${downLabel}" aria-label="${downLabel}" ${isLast ? 'disabled' : ''}>
                <span class="material-symbols-outlined" aria-hidden="true">arrow_downward</span>
            </button>
        `);
    }
    return buttons.length ? buttons.join('') : '<span class="queue-muted">—</span>';
}

function renderRows(data) {
    const body = byId('queueTableBody');
    const empty = byId('queueEmpty');
    const tableWrap = document.querySelector('#tab-queue .queue-table-wrap');
    const books = Array.isArray(data.books) ? data.books : [];
    lastBooks = books;
    const pending = books.filter((book) => book.status === 'pending');
    const firstPending = pending.length ? pending[0].id : null;
    const lastPending = pending.length ? pending[pending.length - 1].id : null;

    if (!books.length) {
        body.innerHTML = '';
        empty.classList.remove('hidden');
        if (tableWrap) tableWrap.classList.add('hidden');
        return;
    }

    empty.classList.add('hidden');
    if (tableWrap) tableWrap.classList.remove('hidden');
    body.innerHTML = books
        .map((book) => {
            const series = book.series
                ? `${escapeHtml(book.series)} #${escapeHtml(book.series_index ?? '')}`
                : '<span class="queue-muted">—</span>';
            const translationId = book.translation_id
                ? `<code>${escapeHtml(book.translation_id)}</code>`
                : '<span class="queue-muted">—</span>';
            return `
                <tr>
                    <td>
                        <div class="queue-book-title">${escapeHtml(book.title)}</div>
                        <div class="queue-book-author">${escapeHtml(book.author || '')}</div>
                    </td>
                    <td>${series}</td>
                    <td><span class="queue-status queue-status-${escapeHtml(statusKey(book))}">${escapeHtml(statusLabel(book))}</span></td>
                    <td>${progressCell(book)}</td>
                    <td>${modelCell(book)}</td>
                    <td>${translationId}</td>
                    <td class="queue-updated-cell">${formatDate(book.job_updated_at || book.updated_at)}</td>
                    <td class="queue-actions-cell">${actionButtons(book, book.id === firstPending, book.id === lastPending)}</td>
                </tr>
            `;
        })
        .join('');
}

function renderEvents(data) {
    const list = byId('queueEvents');
    const events = Array.isArray(data.events) ? data.events : [];
    if (!events.length) {
        list.innerHTML = `<li class="queue-muted">${escapeHtml(t('queue:no_events'))}</li>`;
        return;
    }
    list.innerHTML = events
        .map((event) => `
            <li class="queue-event queue-event-${escapeHtml(event.level || 'info')}">
                <span class="queue-event-time">${formatDate(event.created_at)}</span>
                <span>${escapeHtml(event.message || '')}</span>
            </li>
        `)
        .join('');
}

function showError(message) {
    const error = byId('queueError');
    error.textContent = t('queue:load_error', { message });
    error.classList.remove('hidden');
}

function clearError() {
    const error = byId('queueError');
    error.textContent = '';
    error.classList.add('hidden');
}

function showLibraryError(message) {
    const error = byId('queueLibraryError');
    error.textContent = t('queue:library_error', { message });
    error.classList.remove('hidden');
}

function clearLibraryError() {
    const error = byId('queueLibraryError');
    error.textContent = '';
    error.classList.add('hidden');
}

function setActionStatus(message, isError = false) {
    const status = byId('queueActionStatus');
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('is-error', Boolean(isError));
}

function apiHeaders() {
    return { 'X-API-Token': window.__API_TOKEN__ || '' };
}

function libraryBookLabel(book) {
    const series = book.series
        ? ` — ${book.series}${book.series_index != null ? ` #${book.series_index}` : ''}`
        : '';
    return `${book.title} — ${book.author || '?'}${series} · ${formatNumber(book.word_count)}`;
}

function filteredLibrary() {
    const input = byId('queueLibrarySearch');
    const term = String(input?.value || '').trim().toLowerCase();
    if (!term) return libraryBooks;
    return libraryBooks.filter((book) =>
        [book.title, book.author, book.series]
            .some((value) => String(value || '').toLowerCase().includes(term))
    );
}

function renderLibrary() {
    const select = byId('queueLibrarySelect');
    const empty = byId('queueLibraryEmpty');
    if (!select) return;
    const books = filteredLibrary();
    select.innerHTML = books
        .map((book) => `<option value="${escapeHtml(book.calibre_id)}">${escapeHtml(libraryBookLabel(book))}</option>`)
        .join('');
    if (empty) empty.classList.toggle('hidden', books.length > 0);
    const addButton = byId('queueAddBtn');
    if (addButton) addButton.disabled = books.length === 0 || actionInFlight;
}

async function loadLibrary() {
    clearLibraryError();
    try {
        const response = await fetch(LIBRARY_URL, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        libraryBooks = Array.isArray(data.books) ? data.books : [];
        renderLibrary();
    } catch (error) {
        libraryBooks = [];
        renderLibrary();
        showLibraryError(error.message || String(error));
    }
}

function applySnapshot(data) {
    renderSummary(data);
    renderRows(data);
    renderEvents(data);
}

async function refresh() {
    const button = byId('queueRefreshBtn');
    if (button) button.disabled = true;
    clearError();
    try {
        const response = await fetch(QUEUE_URL, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.status === 'error') throw new Error(data.error || 'server error');
        applySnapshot(data);
    } catch (error) {
        showError(error.message || String(error));
    } finally {
        if (button) button.disabled = false;
    }
}

async function addSelectedBooks() {
    if (actionInFlight) return;
    const select = byId('queueLibrarySelect');
    const ids = select ? [...select.selectedOptions].map((option) => Number(option.value)) : [];
    if (!ids.length) {
        setActionStatus(t('queue:add_none'), true);
        return;
    }

    const button = byId('queueAddBtn');
    actionInFlight = true;
    if (button) button.disabled = true;
    clearLibraryError();
    setActionStatus(t('queue:adding'));
    try {
        const response = await fetch(ADD_URL, {
            method: 'POST',
            headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ calibre_ids: ids }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applySnapshot(data);
        const parts = [t('queue:added', { count: (data.added || []).length })];
        if ((data.duplicates || []).length) {
            parts.push(t('queue:duplicates', { count: data.duplicates.length }));
        }
        if ((data.not_found || []).length) {
            parts.push(t('queue:not_found', { count: data.not_found.length }));
        }
        setActionStatus(parts.join(' '));
        await loadLibrary();
    } catch (error) {
        setActionStatus(t('queue:action_error', { message: error.message || String(error) }), true);
    } finally {
        actionInFlight = false;
        renderLibrary();
    }
}

function showModelError(message) {
    const error = byId('queueModelError');
    if (!error) return;
    error.textContent = message;
    error.classList.remove('hidden');
}

function clearModelError() {
    const error = byId('queueModelError');
    if (!error) return;
    error.textContent = '';
    error.classList.add('hidden');
}

function closeModelModal() {
    const modal = byId('queueModelModal');
    if (modal) modal.classList.add('hidden');
    editingBookId = null;
    clearModelError();
}

function openModelModal(bookId) {
    const book = lastBooks.find((item) => item.id === bookId);
    if (!book || book.status !== 'pending') return;
    editingBookId = book.id;
    const label = byId('queueModelBook');
    if (label) label.textContent = `${book.title} — ${book.author || ''}`.trim();
    const modelInput = byId('queueModelInput');
    if (modelInput) modelInput.value = book.model || '';
    const providerInput = byId('queueProviderInput');
    if (providerInput) providerInput.value = book.provider || 'ollama';
    clearModelError();
    const modal = byId('queueModelModal');
    if (modal) modal.classList.remove('hidden');
    if (modelInput) modelInput.focus();
    loadModelOptions();
}

async function loadModelOptions() {
    const providers = byId('queueProviderOptions');
    if (providers && !providers.dataset.ready) {
        providers.innerHTML = PROVIDERS
            .map((provider) => `<option value="${escapeHtml(provider)}"></option>`)
            .join('');
        providers.dataset.ready = '1';
    }
    if (modelsLoaded || modelsLoading) return;
    modelsLoading = true;
    try {
        const response = await fetch(MODELS_URL, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        if (!response.ok) return;
        const data = await response.json().catch(() => ({}));
        const names = Array.isArray(data.model_names)
            ? data.model_names
            : (Array.isArray(data.models)
                ? data.models.map((model) => (typeof model === 'string' ? model : (model.id || model.name)))
                : []);
        const list = byId('queueModelOptions');
        if (!list) return;
        availableModels = names.filter(Boolean);
        list.innerHTML = availableModels
            .map((name) => `<option value="${escapeHtml(name)}"></option>`)
            .join('');
        modelsLoaded = true;
        refreshModelSelects();
    } catch (error) {
        // Suggestions are optional; typing the model name still works.
    } finally {
        modelsLoading = false;
    }
}

async function patchBookModel(bookId, model, provider) {
    const response = await fetch(`${ADD_URL}/${bookId}`, {
        method: 'PATCH',
        headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, provider }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') {
        throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
}

async function saveModel() {
    if (!editingBookId) return;
    const modelInput = byId('queueModelInput');
    const providerInput = byId('queueProviderInput');
    const model = String(modelInput?.value || '').trim();
    const provider = String(providerInput?.value || '').trim();
    if (!model) {
        showModelError(t('queue:model_required'));
        return;
    }

    const button = byId('queueModelSave');
    if (button) button.disabled = true;
    clearModelError();
    try {
        const data = await patchBookModel(editingBookId, model, provider);
        applySnapshot(data);
        closeModelModal();
        setActionStatus(t('queue:model_updated'));
    } catch (error) {
        showModelError(t('queue:model_error', { message: error.message || String(error) }));
    } finally {
        if (button) button.disabled = false;
    }
}

async function changeBookModel(bookId, model) {
    const book = lastBooks.find((item) => item.id === bookId);
    if (!book) return;
    if (!model) {
        setActionStatus(t('queue:model_required'), true);
        return;
    }
    const provider = String(book.provider || 'ollama');
    const select = document.querySelector(`[data-model-book-id="${bookId}"]`);
    if (select) select.disabled = true;
    try {
        const data = await patchBookModel(bookId, model, provider);
        applySnapshot(data);
        setActionStatus(t('queue:model_updated'));
    } catch (error) {
        if (select) select.value = String(book.model || '');
        setActionStatus(t('queue:model_error', { message: error.message || String(error) }), true);
    } finally {
        if (select) select.disabled = false;
    }
}

async function downloadArtifact(bookId, filename) {
    const button = document.querySelector(`[data-download-book-id="${bookId}"]`);
    if (button) button.disabled = true;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/download`, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename || 'book.epub';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        setActionStatus(t('queue:download_started', { filename: filename || 'book.epub' }));
    } catch (error) {
        setActionStatus(t('queue:download_error', { message: error.message || String(error) }), true);
    } finally {
        if (button) button.disabled = false;
    }
}

async function moveBook(bookId, direction) {
    if (actionInFlight) return;
    actionInFlight = true;
    setActionStatus(t('queue:moving'));
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/move`, {
            method: 'POST',
            headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ direction }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applySnapshot(data);
        setActionStatus(t('queue:moved'));
    } catch (error) {
        setActionStatus(t('queue:move_error', { message: error.message || String(error) }), true);
    } finally {
        actionInFlight = false;
    }
}

function initialize() {
    const button = byId('queueRefreshBtn');
    if (button) button.addEventListener('click', refresh);

    const addButton = byId('queueAddBtn');
    if (addButton) addButton.addEventListener('click', addSelectedBooks);

    const search = byId('queueLibrarySearch');
    if (search) search.addEventListener('input', renderLibrary);

    const table = byId('queueTableBody');
    if (table) {
        table.addEventListener('click', (event) => {
            const download = event.target.closest('[data-download-book-id]');
            if (download) {
                downloadArtifact(
                    Number(download.dataset.downloadBookId),
                    download.dataset.downloadName || ''
                );
                return;
            }
            const move = event.target.closest('[data-move]');
            if (!move || move.disabled) return;
            moveBook(Number(move.dataset.bookId), move.dataset.move);
        });
        table.addEventListener('change', (event) => {
            const select = event.target.closest('[data-model-book-id]');
            if (!select) return;
            const bookId = Number(select.dataset.modelBookId);
            if (select.value === '__custom__') {
                const book = lastBooks.find((item) => item.id === bookId);
                select.value = String(book?.model || '');
                openModelModal(bookId);
                return;
            }
            changeBookModel(bookId, select.value);
        });
    }

    const modelModal = byId('queueModelModal');
    if (modelModal) {
        modelModal.addEventListener('click', (event) => {
            if (event.target === modelModal) closeModelModal();
        });
    }
    const modelClose = byId('queueModelModalClose');
    if (modelClose) modelClose.addEventListener('click', closeModelModal);
    const modelCancel = byId('queueModelCancel');
    if (modelCancel) modelCancel.addEventListener('click', closeModelModal);
    const modelSave = byId('queueModelSave');
    if (modelSave) modelSave.addEventListener('click', saveModel);

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        const modal = byId('queueModelModal');
        if (modal && !modal.classList.contains('hidden')) closeModelModal();
    });

    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
        const tab = byId('tab-queue');
        if (!tab || tab.classList.contains('hidden')) return;
        if (document.visibilityState !== 'visible') return;
        refresh();
    }, REFRESH_MS);
    window.QueueManager = QueueManager;
}

function open() {
    return Promise.all([refresh(), loadLibrary(), loadModelOptions()]);
}

export const QueueManager = { initialize, open, refresh, loadLibrary };
