/**
 * Persistent literary queue view and its controlled actions: enqueueing books
 * from the Calibre inventory, reordering pending entries and requesting a
 * pause after the current book.
 *
 * The queue is written by the local CLI/wrapper. This module never spawns a
 * process itself: the Run buttons write a request that the host-side agent
 * consumes, and the pause request is consumed by the runner between books.
 */

import { t } from '../i18n/i18n.js';
import { toast } from '../ui/toast.js';

const QUEUE_URL = '/api/literary/queue';
const LIBRARY_URL = '/api/literary/library';
const ADD_URL = '/api/literary/queue/books';
const CONTROL_URL = '/api/literary/queue/control';
const RUN_URL = '/api/literary/queue/run';
const MODELS_URL = '/api/models?provider=';
const REFRESH_MS = 10000;
// The queue supports local and cloud providers when QUEUE_ALLOW_CLOUD=true.
const PROVIDERS = ['ollama', 'gemini', 'deepseek', 'openrouter', 'mistral', 'poe', 'nim', 'litellm'];
const RUNNING_STATES = new Set(['preparing', 'translating', 'reviewing', 'validating']);
const RETRY_STATES = new Set(['failed', 'needs_review', 'paused']);

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
let modelsProvider = 'ollama';
let modelsLoading = false;
let actionInFlight = false;
let lastSnapshot = { books: [], summary: {}, events: [] };
let activeFilter = 'all';
let activeSeries = '';
let searchTerm = '';
let qualityBookId = null;
let logPreviewRequest = 0;
let controlState = {
    pause_after_book: false,
    requested_at: null,
    honored_at: null,
    honored_after: null,
};
let controlInFlight = false;

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
    const state = String(book.state || book.job_state || book.status || 'pending').toLowerCase();
    // The upstream checkpoint occasionally reports "interrupted" during a
    // retry while the process is still writing.  The backend marks those books
    // live; show them as translating and hide retry until the log goes quiet.
    if (state === 'paused' && book.live) return 'translating';
    return state;
}

function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
    if (minutes > 0) return `${minutes}m`;
    return `${total}s`;
}

function estimateEta(book) {
    const current = Number(book.current_chapter || 0);
    const total = Number(book.total_chapters || 0);
    const created = book.job_created_at;
    if (!created || current <= 0 || total <= 0 || current >= total) return '';
    const started = new Date(created.includes('T') ? created : created.replace(' ', 'T') + 'Z');
    if (Number.isNaN(started.getTime())) return '';
    const elapsed = (Date.now() - started.getTime()) / 1000;
    if (elapsed <= 0) return '';
    const rate = current / elapsed;
    if (rate <= 0) return '';
    return formatDuration((total - current) / rate);
}

function bookMatchesFilter(book) {
    const state = statusKey(book);
    if (activeFilter === 'running' && !RUNNING_STATES.has(state)) return false;
    if (activeFilter === 'pending' && state !== 'pending') return false;
    if (activeFilter === 'completed' && state !== 'completed') return false;
    if (activeFilter === 'review' && state !== 'needs_review') return false;
    if (activeSeries && String(book.series || '') !== activeSeries) return false;
    if (searchTerm) {
        const haystack = [book.title, book.author, book.series]
            .map((value) => String(value || '').toLowerCase())
            .join(' ');
        if (!haystack.includes(searchTerm)) return false;
    }
    return true;
}

function filteredBooks() {
    return (lastSnapshot.books || []).filter(bookMatchesFilter);
}

function stateLabel(book) {
    const key = statusKey(book);
    return t(`queue:${STATUS_KEYS[key] || 'status_unknown'}`);
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
        .map((model) => {
            // Keep the full id as the value; show only the final path segment
            // so the select fits the column without truncating mid-name.
            const label = String(model).split('/').pop();
            return `<option value="${escapeHtml(model)}" ${model === current ? 'selected' : ''}>${escapeHtml(label)}</option>`;
        })
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
        <span class="queue-progress-text">${current}/${total} · ${pct}%</span>
    `;
}

function renderSummary(data) {
    const summary = data.summary || {};
    const byStatus = summary.by_status || {};
    const running = (data.books || [])
        .filter((book) => book.live || RUNNING_STATES.has(statusKey(book)))
        .length;
    const cards = [
        [t('queue:books'), formatNumber(summary.books)],
        [t('queue:words'), formatNumber(summary.words)],
        [t('queue:translating'), formatNumber(running)],
        [t('queue:pending'), formatNumber(byStatus.pending || 0)],
        [t('queue:completed'), formatNumber(byStatus.completed || 0)],
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
    renderDistribution(summary, running);
    byId('queueUpdatedAt').textContent = data.generated_at
        ? t('queue:updated', { time: formatDate(data.generated_at) })
        : '';
}

function renderDistribution(summary, running) {
    const host = byId('queueDistribution');
    if (!host) return;
    const byStatus = summary.by_status || {};
    const segments = [
        ['translating', t('queue:translating'), running],
        ['pending', t('queue:pending'), byStatus.pending || 0],
        ['completed', t('queue:completed'), byStatus.completed || 0],
        ['needs_review', t('queue:needs_review'), byStatus.needs_review || 0],
        ['failed', t('queue:status_failed'), byStatus.failed || 0],
    ].filter(([, , count]) => Number(count) > 0);
    if (!segments.length) {
        host.classList.add('hidden');
        host.innerHTML = '';
        return;
    }
    const total = segments.reduce((sum, [, , count]) => sum + Number(count), 0);
    const bars = segments
        .map(([key, label, count]) => {
            const pct = total > 0 ? (Number(count) / total) * 100 : 0;
            return `<span class="queue-distribution-segment is-${key}" style="width: ${pct.toFixed(2)}%" title="${escapeHtml(`${label}: ${count}`)}"></span>`;
        })
        .join('');
    const legend = segments
        .map(([key, label, count]) => `
            <span class="queue-distribution-legend-item is-${key}">
                <i aria-hidden="true"></i>${escapeHtml(label)} <b>${escapeHtml(String(count))}</b>
            </span>
        `)
        .join('');
    host.innerHTML = `
        <div class="queue-distribution-bar">${bars}</div>
        <div class="queue-distribution-legend">${legend}</div>
    `;
    host.setAttribute(
        'aria-label',
        segments.map(([key, label, count]) => `${label}: ${count}`).join(' | ')
    );
    host.classList.remove('hidden');
}

function renderNow(data) {
    const container = byId('queueNow');
    if (!container) return;
    const books = Array.isArray(data.books) ? data.books : [];
    const active = books.find((book) => RUNNING_STATES.has(statusKey(book)) || book.live);
    const next = books.find((book) => statusKey(book) === 'pending');
    const book = active || next;
    if (!book) {
        container.innerHTML = `<div class="queue-now-empty">${escapeHtml(t('queue:now_idle'))}</div>`;
        container.classList.remove('hidden');
        return;
    }
    const isActive = Boolean(active);
    const rawState = statusKey(book);
    const state = isActive && rawState === 'paused' ? 'translating' : rawState;
    const nowStatusLabel = rawState === 'paused' && isActive
        ? t('queue:status_translating')
        : stateLabel(book);
    const total = Number(book.total_chapters || 0);
    const current = Number(book.current_chapter || 0);
    const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((current / total) * 100))) : 0;
    const eta = isActive ? estimateEta(book) : '';
    const series = book.series
        ? `${escapeHtml(book.series)} #${escapeHtml(book.series_index ?? '')}`
        : '';
    const showError = (state === 'failed' || state === 'needs_review') && book.error;
    const progress = total > 0
        ? `
            <div class="queue-progress queue-now-progress"><span style="width: ${pct}%"></span></div>
            <div class="queue-now-progress-line">
                <span>${escapeHtml(t('queue:chunks', { current, total }))}</span>
                <span>${escapeHtml(eta ? t('queue:now_eta', { time: eta }) : t('queue:now_unknown_eta'))}</span>
            </div>
        `
        : '';
    const logLine = isActive
        ? `
            <div class="queue-now-log" id="queueNowLog">
                <span class="queue-muted">${escapeHtml(t('queue:now_last_log'))}:</span>
                <code id="queueNowLogLine">—</code>
            </div>
        `
        : '';
    const errorLine = showError
        ? `<div class="queue-now-error-line"><span class="queue-now-error">${escapeHtml(t('queue:now_error', { message: book.error }))}</span></div>`
        : '';
    const buttons = [];
    if (isActive) {
        const pauseLabel = controlState.pause_now
            ? t('queue:pause_cancel')
            : t('queue:pause_now');
        buttons.push(`
            <button type="button" class="btn btn-secondary queue-now-btn queue-pause-now-btn"
                    data-now-pause="${book.id}">
                <span class="material-symbols-outlined" aria-hidden="true">pause_circle</span>
                <span data-now-pause-label>${escapeHtml(pauseLabel)}</span>
            </button>
        `);
    }
    if (book.artifact) {
        buttons.push(`
            <button type="button" class="btn btn-secondary queue-now-btn"
                    data-now-download="${book.id}"
                    data-now-download-name="${escapeHtml(book.artifact.filename || '')}">
                <span class="material-symbols-outlined" aria-hidden="true">download</span>
                ${escapeHtml(t('queue:now_download'))}
            </button>
        `);
    }
    buttons.push(`
        <button type="button" class="btn btn-secondary queue-now-btn" data-now-log="${book.id}">
            <span class="material-symbols-outlined" aria-hidden="true">article</span>
            ${escapeHtml(t('queue:now_view_log'))}
        </button>
    `);
    if (!isActive) {
        buttons.push(`
            <button type="button" class="btn btn-secondary queue-now-btn queue-remove-btn"
                    data-now-remove="${book.id}">
                <span class="material-symbols-outlined" aria-hidden="true">playlist_remove</span>
                ${escapeHtml(t('queue:remove'))}
            </button>
        `);
    }
    if (state === 'needs_review') {
        buttons.push(`
            <button type="button" class="btn btn-primary queue-now-btn" data-now-approve="${book.id}">
                <span class="material-symbols-outlined" aria-hidden="true">verified</span>
                ${escapeHtml(t('queue:now_approve'))}
            </button>
        `);
    }
    if (RETRY_STATES.has(state)) {
        const isPaused = state === 'paused';
        const actionLabel = t(isPaused ? 'queue:now_resume' : 'queue:now_retry');
        buttons.push(`
            <button type="button" class="btn btn-secondary queue-now-btn" data-now-retry="${book.id}">
                <span class="material-symbols-outlined" aria-hidden="true">${isPaused ? 'play_arrow' : 'restart_alt'}</span>
                ${escapeHtml(actionLabel)}
            </button>
        `);
    }
    container.innerHTML = `
        <div class="queue-now-head">
            <span class="queue-now-eyebrow">${escapeHtml(isActive ? t('queue:now_title') : t('queue:now_next'))}</span>
            <span class="queue-status queue-status-${escapeHtml(state)}">${escapeHtml(nowStatusLabel)}</span>
        </div>
        <div class="queue-now-body">
            <div class="queue-now-main">
                <div class="queue-now-title">${escapeHtml(book.title)}</div>
                <div class="queue-now-meta">
                    ${series ? `<span>${series}</span>` : ''}
                    <span>${escapeHtml(modelLabel(book))}</span>
                    ${book.translation_id ? `<code>${escapeHtml(book.translation_id)}</code>` : ''}
                </div>
                ${progress}
                ${logLine}
                ${errorLine}
            </div>
            <div class="queue-now-actions">${buttons.join('')}</div>
        </div>
    `;
    container.classList.remove('hidden');
    if (isActive && book.id) loadNowLog(book.id);
}

async function loadNowLog(bookId) {
    const requestId = ++logPreviewRequest;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/log?lines=1`, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        if (!response.ok) return;
        const payload = await response.json();
        const lines = Array.isArray(payload.lines) ? payload.lines : [];
        if (requestId !== logPreviewRequest) return;
        const target = byId('queueNowLogLine');
        if (target) target.textContent = lines.length ? lines[lines.length - 1] : t('queue:log_empty');
    } catch (error) {
        // A missing log must not break the queue view.
    }
}

function actionButtons(book, isFirst, isLast) {
    const buttons = [];
    if (book.artifact) {
        const downloadLabel = escapeHtml(t('queue:download'));
        const qualityLabel = escapeHtml(t('queue:quality_open'));
        buttons.push(`
            <button type="button" class="queue-move-btn queue-download-btn"
                    data-download-book-id="${book.id}"
                    data-download-name="${escapeHtml(book.artifact.filename || '')}"
                    title="${downloadLabel}" aria-label="${downloadLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">download</span>
            </button>
            <button type="button" class="queue-move-btn"
                    data-quality-book-id="${book.id}"
                    title="${qualityLabel}" aria-label="${qualityLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">query_stats</span>
            </button>
        `);
    }
    const state = statusKey(book);
    if (state === 'needs_review') {
        const approveLabel = escapeHtml(t('queue:now_approve'));
        buttons.push(`
            <button type="button" class="queue-move-btn queue-approve-btn"
                    data-approve-book-id="${book.id}"
                    title="${approveLabel}" aria-label="${approveLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">verified</span>
            </button>
        `);
    }
    if (RETRY_STATES.has(state)) {
        const isPaused = state === 'paused';
        const retryLabel = escapeHtml(t(isPaused ? 'queue:now_resume' : 'queue:now_retry'));
        buttons.push(`
            <button type="button" class="queue-move-btn${isPaused ? ' queue-resume-btn' : ''}"
                    data-retry-book-id="${book.id}"
                    title="${retryLabel}" aria-label="${retryLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">${isPaused ? 'play_arrow' : 'restart_alt'}</span>
            </button>
        `);
    }
    if (state === 'pending') {
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
    if (!book.live && !RUNNING_STATES.has(state)) {
        const removeLabel = escapeHtml(t('queue:remove'));
        buttons.push(`
            <button type="button" class="queue-move-btn queue-remove-btn"
                    data-remove-book-id="${book.id}"
                    title="${removeLabel}" aria-label="${removeLabel}">
                <span class="material-symbols-outlined" aria-hidden="true">playlist_remove</span>
            </button>
        `);
    }
    return buttons.length ? buttons.join('') : '<span class="queue-muted">—</span>';
}

function renderRows() {
    const body = byId('queueTableBody');
    const empty = byId('queueEmpty');
    const tableWrap = document.querySelector('#tab-queue .queue-table-wrap');
    const books = filteredBooks();
    const pending = (lastSnapshot.books || []).filter((book) => statusKey(book) === 'pending');
    const firstPending = pending.length ? pending[0].id : null;
    const lastPending = pending.length ? pending[pending.length - 1].id : null;

    if (!books.length) {
        body.innerHTML = '';
        if ((lastSnapshot.books || []).length) {
            empty.innerHTML = `<p>${escapeHtml(t('queue:no_matches'))}</p>`;
        }
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
            const nextBadge = book.is_next
                ? `<span class="queue-next-badge">${escapeHtml(t('queue:next_badge'))}</span>`
                : '';
            const title = book.artifact
                ? `<button type="button" class="queue-book-title queue-book-title-btn"
                           data-quality-book-id="${book.id}">
                       ${escapeHtml(book.title)}
                   </button>`
                : `<div class="queue-book-title">${escapeHtml(book.title)}</div>`;
            return `
                <tr>
                    <td class="queue-position">${book.position != null ? escapeHtml(book.position) : '—'}</td>
                    <td>
                        ${title}
                        <div class="queue-book-author">${escapeHtml(book.author || '')} ${nextBadge}</div>
                    </td>
                    <td class="queue-series-col">${series}</td>
                    <td><span class="queue-status queue-status-${escapeHtml(statusKey(book))}">${escapeHtml(statusLabel(book))}</span></td>
                    <td>${progressCell(book)}</td>
                    <td class="queue-model-col">${modelCell(book)}</td>
                    <td class="queue-updated-cell queue-updated-col">${formatDate(book.job_updated_at || book.updated_at)}</td>
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

function renderFilters() {
    const chips = byId('queueStatusFilters');
    if (chips) {
        const choices = [
            ['all', 'filter_all'],
            ['running', 'filter_running'],
            ['pending', 'filter_pending'],
            ['completed', 'filter_completed'],
            ['review', 'filter_review'],
        ];
        chips.innerHTML = choices
            .map(([value, key]) => `
                <button type="button" class="queue-chip ${activeFilter === value ? 'active' : ''}"
                        data-filter="${value}">
                    ${escapeHtml(t(`queue:${key}`))}
                </button>
            `)
            .join('');
    }
    const seriesSelect = byId('queueSeriesFilter');
    if (seriesSelect) {
        const series = [...new Set((lastSnapshot.books || [])
            .map((book) => String(book.series || ''))
            .filter(Boolean))].sort((a, b) => a.localeCompare(b));
        if (activeSeries && !series.includes(activeSeries)) activeSeries = '';
        seriesSelect.innerHTML = [
            `<option value="">${escapeHtml(t('queue:filter_all_series'))}</option>`,
            ...series.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
        ].join('');
        seriesSelect.value = activeSeries;
    }
}

function applySnapshot(data) {
    lastSnapshot = {
        books: Array.isArray(data.books) ? data.books : [],
        summary: data.summary || {},
        events: Array.isArray(data.events) ? data.events : [],
        agent: data.agent || {},
        runner: data.runner || {},
        run_request: data.run_request || null,
    };
    lastBooks = lastSnapshot.books;
    renderSummary(data);
    renderNow(data);
    renderFilters();
    renderRows();
    renderEvents(data);
    renderRunnerStatus(data);
}

function renderRunnerStatus(data) {
    const status = byId('queueRunnerStatus');
    const runNext = byId('queueRunBtn');
    if (!status) return;

    const agent = data.agent || {};
    const runner = data.runner || {};
    const online = Boolean(agent.online);
    const running = Boolean(runner.running);
    const pending = (data.books || []).some((book) => statusKey(book) === 'pending');

    let label = t('queue:runner_offline');
    let cls = 'is-offline';
    if (online) {
        label = running ? t('queue:runner_running') : t('queue:runner_online');
        cls = running ? 'is-running' : 'is-online';
    }
    status.textContent = label;
    status.className = `queue-runner-status ${cls}`;

    if (runNext) {
        runNext.disabled = actionInFlight || !pending || running;
        runNext.title = running
            ? t('queue:run_already_running')
            : (!online ? t('queue:run_agent_offline') : t('queue:run_next_title'));
    }
}

function renderControl() {
    const button = byId('queuePauseBtn');
    const label = byId('queuePauseLabel');
    const icon = byId('queuePauseIcon');
    const status = byId('queueControlStatus');
    const active = Boolean(controlState.pause_after_book);
    const stopping = Boolean(controlState.pause_now);

    if (button) {
        button.classList.toggle('is-requested', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
    if (label) {
        label.textContent = t(active ? 'queue:pause_cancel' : 'queue:pause_after_book');
    }
    if (icon) icon.textContent = active ? 'play_circle' : 'pause_circle';
    const nowLabel = document.querySelector('[data-now-pause-label]');
    if (nowLabel) {
        nowLabel.textContent = t(controlState.pause_now ? 'queue:pause_cancel' : 'queue:pause_now');
    }
    if (status) {
        status.classList.remove('is-error');
        if (stopping) {
            status.textContent = t('queue:pause_now_requested');
        } else if (active) {
            status.textContent = t('queue:pause_requested');
        } else if (controlState.pause_now_honored_after && controlState.pause_now_honored_after.title) {
            status.textContent = t('queue:paused_after', {
                title: controlState.pause_now_honored_after.title,
            });
        } else if (controlState.honored_after && controlState.honored_after.title) {
            status.textContent = t('queue:paused_after', {
                title: controlState.honored_after.title,
            });
        } else {
            status.textContent = t('queue:pause_idle_hint');
        }
    }
}

async function loadControl() {
    try {
        const response = await fetch(CONTROL_URL, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        controlState = await response.json();
    } catch (error) {
        // The queue table can still render; keep the last known control state.
    }
    renderControl();
}

async function togglePause() {
    if (controlInFlight) return;
    const button = byId('queuePauseBtn');
    const status = byId('queueControlStatus');
    const next = !controlState.pause_after_book;

    controlInFlight = true;
    if (button) button.disabled = true;
    if (status) status.classList.remove('is-error');
    try {
        const response = await fetch(CONTROL_URL, {
            method: 'POST',
            headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ pause_after_book: next }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        controlState = data;
        renderControl();
    } catch (error) {
        if (status) {
            status.textContent = t('queue:pause_error', {
                message: error.message || String(error),
            });
            status.classList.add('is-error');
        }
    } finally {
        controlInFlight = false;
        if (button) button.disabled = false;
    }
}

async function pauseNow(bookId) {
    if (controlInFlight) return;
    const button = document.querySelector(`[data-now-pause="${bookId}"]`);
    const status = byId('queueControlStatus');
    const next = !controlState.pause_now;

    controlInFlight = true;
    if (button) button.disabled = true;
    if (status) status.classList.remove('is-error');
    try {
        const response = await fetch(CONTROL_URL, {
            method: 'POST',
            headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ pause_now: next }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        controlState = data;
        renderControl();
        setTimeout(refresh, 1500);
    } catch (error) {
        if (status) {
            status.textContent = t('queue:pause_now_error', {
                message: error.message || String(error),
            });
            status.classList.add('is-error');
        }
    } finally {
        controlInFlight = false;
        if (button) button.disabled = false;
    }
}

async function refresh() {
    const button = byId('queueRefreshBtn');
    if (button) button.disabled = true;
    clearError();
    loadControl();
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
    loadModelOptions(providerInput?.value || 'ollama', true);
}

async function loadModelOptions(provider = 'ollama', force = false) {
    const providers = byId('queueProviderOptions');
    if (providers && !providers.dataset.ready) {
        providers.innerHTML = PROVIDERS
            .map((item) => `<option value="${escapeHtml(item)}"></option>`)
            .join('');
        providers.dataset.ready = '1';
    }
    const providerInput = byId('queueProviderInput');
    if (providerInput && !providerInput.dataset.modelBound) {
        providerInput.addEventListener('change', () => {
            loadModelOptions(providerInput.value.trim() || 'ollama', true);
        });
        providerInput.dataset.modelBound = '1';
    }
    if (modelsLoading) return;
    if (!force && modelsLoaded && provider === modelsProvider) return;
    modelsLoading = true;
    try {
        const response = await fetch(`${MODELS_URL}${encodeURIComponent(provider)}`, {
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
        modelsProvider = provider;
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
    const provider = String(providerInput?.value || 'ollama').trim() || 'ollama';
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
    // Preserve the book's provider when changing its model.
    const provider = book.provider || 'ollama';
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

function formatBytes(value) {
    const size = Number(value || 0);
    if (size <= 0) return '—';
    if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function qualityMetric(label, value) {
    return `
        <div class="queue-quality-metric">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `;
}

function renderQuality(payload) {
    const body = byId('queueQualityBody');
    if (!body) return;
    const book = payload.book || {};
    const artifact = payload.artifact || {};
    const metrics = payload.metrics || {};
    const report = payload.report || {};
    const log = payload.log || {};
    const state = payload.book?.state || '';
    const refreshBook = lastSnapshot.books.find((item) => item.id === qualityBookId) || {};
    const currentState = statusKey(refreshBook);
    const issues = Array.isArray(payload.issues) ? payload.issues : [];
    const epubcheck = payload.epubcheck || report.epubcheck || null;
    const epubcheckText = epubcheck
        ? `${Number(epubcheck.fatals || 0)} fatal / ${Number(epubcheck.errors || 0)} errors / ${Number(epubcheck.warnings || 0)} warnings`
        : t('queue:quality_not_recorded');
    const validation = report.validation || {};
    const refine = report.refine || {};
    const reader = report.reader_repair || {};
    const termRows = [
        [t('queue:quality_chantry'), metrics.chantry],
        [t('queue:quality_chantria'), metrics.chantria],
        [t('queue:quality_cielcin_upper'), metrics.cielcin_upper],
        [t('queue:quality_cielcin_lower'), metrics.cielcin_lower],
        [t('queue:quality_mericanii_upper'), metrics.mericanii_upper],
        [t('queue:quality_mericanii_lower'), metrics.mericanii_lower],
        [t('queue:quality_halfmortal'), metrics.halfmortal],
        [t('queue:quality_semimortal'), metrics.semimortal],
    ];
    const reportLines = [];
    if (validation.passed != null) {
        reportLines.push(t('queue:quality_gate', {
            status: validation.passed ? t('queue:quality_pass') : t('queue:quality_fail'),
            blocking: validation.blocking ?? 0,
            warnings: validation.warnings ?? 0,
        }));
    }
    if (refine && Object.keys(refine).length) {
        reportLines.push(t('queue:quality_refine', {
            accepted: refine.accepted ?? 0,
            rejected: refine.rejected ?? 0,
            flagged: refine.flagged ?? 0,
        }));
    }
    if (reader && Object.keys(reader).length) {
        reportLines.push(t('queue:quality_reader', {
            merged: reader.merged ?? 0,
            quotes: reader.quote_paragraphs ?? 0,
            splits: reader.artifact_changes?.split_dialogue_paragraphs ?? 0,
        }));
    }
    const actionButtonsHtml = [
        artifact.download_url
            ? `<button type="button" class="btn btn-primary" data-quality-download="${qualityBookId}"
                       data-quality-download-name="${escapeHtml(artifact.filename || '')}">
                   <span class="material-symbols-outlined" aria-hidden="true">download</span>
                   ${escapeHtml(t('queue:quality_download'))}
               </button>`
            : '',
        currentState === 'needs_review'
            ? `<button type="button" class="btn btn-secondary" data-quality-approve="${qualityBookId}">
                   ${escapeHtml(t('queue:now_approve'))}
               </button>`
            : '',
        RETRY_STATES.has(currentState)
            ? `<button type="button" class="btn btn-secondary" data-quality-retry="${qualityBookId}">
                   ${escapeHtml(t('queue:now_retry'))}
               </button>`
            : '',
    ].filter(Boolean).join('');
    body.innerHTML = `
        <div class="queue-quality-heading">
            <div>
                <h4>${escapeHtml(book.title || '')}</h4>
                <p>${escapeHtml([book.author, book.series, book.series_index != null ? `#${book.series_index}` : '']
                    .filter(Boolean).join(' · '))}</p>
                ${book.translation_id ? `<p><code>${escapeHtml(book.translation_id)}</code></p>` : ''}
            </div>
            <span class="queue-status queue-status-${escapeHtml(state)}">${escapeHtml(stateLabel(refreshBook))}</span>
        </div>
        <section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_artifact'))}</h5>
            <div class="queue-quality-artifact">
                <code>${escapeHtml(artifact.filename || '—')}</code>
                <span>${escapeHtml(artifact.kind || '—')} · ${escapeHtml(formatBytes(artifact.size))}</span>
            </div>
        </section>
        <section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_metrics'))}</h5>
            <div class="queue-quality-grid">
                ${qualityMetric(t('queue:quality_words'), formatNumber(metrics.words))}
                ${qualityMetric(t('queue:quality_chapters'), formatNumber(metrics.chapters))}
                ${qualityMetric(t('queue:quality_paragraphs'), formatNumber(metrics.paragraphs))}
                ${qualityMetric(t('queue:quality_curly'), `${formatNumber(metrics.curly_open)} / ${formatNumber(metrics.curly_close)}`)}
                ${qualityMetric(t('queue:quality_straight'), formatNumber(metrics.straight_quotes))}
                ${qualityMetric(t('queue:quality_brackets'), formatNumber(metrics.brackets))}
                ${qualityMetric(t('queue:quality_dashes'), formatNumber(metrics.em_dashes))}
                ${qualityMetric(t('queue:quality_epubcheck'), epubcheckText)}
            </div>
        </section>
        <section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_terms'))}</h5>
            <div class="queue-quality-grid">
                ${termRows.map(([label, value]) => qualityMetric(label, formatNumber(value))).join('')}
            </div>
        </section>
        <section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_issues'))}</h5>
            ${issues.length
                ? `<ul class="queue-quality-issues">${issues.slice(0, 10).map((issue) => `
                    <li class="queue-quality-issue-${escapeHtml(issue.severity || 'warning')}">
                        ${escapeHtml(issue.message || issue.code || '')}
                    </li>`).join('')}</ul>`
                : `<p class="queue-muted">${escapeHtml(t('queue:quality_no_issues'))}</p>`}
            ${(payload.quality_flags || []).length
                ? `<div class="queue-quality-flags">${payload.quality_flags.map((flag) => `<span>${escapeHtml(flag)}</span>`).join('')}</div>`
                : ''}
        </section>
        ${reportLines.length ? `<section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_report'))}</h5>
            <ul class="queue-quality-report">${reportLines.map((line) => `<li>${escapeHtml(line)}</li>`).join('')}</ul>
        </section>` : ''}
        <section class="queue-quality-section">
            <h5>${escapeHtml(t('queue:quality_log'))}</h5>
            <pre class="queue-quality-log">${escapeHtml((log.lines || []).join('\n') || t('queue:log_empty'))}</pre>
        </section>
        <div class="queue-quality-actions">${actionButtonsHtml}</div>
    `;
}

async function openQuality(bookId) {
    qualityBookId = bookId;
    const overlay = byId('queueQualityDrawer');
    const body = byId('queueQualityBody');
    if (!overlay || !body) return;
    overlay.classList.remove('hidden');
    body.innerHTML = `<p class="queue-muted">${escapeHtml(t('queue:quality_loading'))}</p>`;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/quality`, {
            headers: apiHeaders(),
            cache: 'no-store',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.status === 'error') {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        renderQuality(payload);
    } catch (error) {
        body.innerHTML = `<p class="queue-error">${escapeHtml(t('queue:quality_load_error', { message: error.message || String(error) }))}</p>`;
    }
}

function closeQuality() {
    const overlay = byId('queueQualityDrawer');
    if (overlay) overlay.classList.add('hidden');
    qualityBookId = null;
}

async function approveBook(bookId) {
    if (!window.confirm(t('queue:approve_confirm'))) return;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/approve`, {
            method: 'POST',
            headers: apiHeaders(),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applySnapshot(data);
        setActionStatus(t('queue:approved'));
        closeQuality();
    } catch (error) {
        setActionStatus(t('queue:action_approve_error', { message: error.message || String(error) }), true);
    }
}

async function runQueue() {
    if (actionInFlight) return;
    const pending = lastBooks.find((book) => statusKey(book) === 'pending');
    if (!pending) {
        setActionStatus(t('queue:run_none'), true);
        return;
    }
    if (!window.confirm(t('queue:run_next_confirm', { title: pending.title }))) return;

    actionInFlight = true;
    const button = byId('queueRunBtn');
    if (button) button.disabled = true;
    setActionStatus(t('queue:run_requesting'));
    try {
        const response = await fetch(RUN_URL, {
            method: 'POST',
            headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'next' }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        applySnapshot(data);
        const agent = data.agent || {};
        if (!agent.online) {
            setActionStatus(t('queue:run_agent_offline'), true);
        } else {
            setActionStatus(t('queue:run_requested'));
        }
    } catch (error) {
        setActionStatus(t('queue:run_error', { message: error.message || String(error) }), true);
    } finally {
        actionInFlight = false;
        renderRunnerStatus(lastSnapshot);
    }
}

async function retryBook(bookId) {
    const book = lastBooks.find((item) => item.id === bookId);
    const confirmKey = book && statusKey(book) === 'paused'
        ? 'queue:resume_confirm'
        : 'queue:retry_confirm';
    if (!window.confirm(t(confirmKey))) return;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}/retry`, {
            method: 'POST',
            headers: apiHeaders(),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applySnapshot(data);
        setActionStatus(t('queue:retried'));
        closeQuality();
    } catch (error) {
        setActionStatus(t('queue:action_retry_error', { message: error.message || String(error) }), true);
    }
}

async function removeBook(bookId) {
    if (actionInFlight) return;
    const book = lastBooks.find((item) => item.id === bookId);
    const title = book?.title || '';
    if (!window.confirm(t('queue:remove_confirm', { title }))) return;

    actionInFlight = true;
    try {
        const response = await fetch(`${ADD_URL}/${bookId}`, {
            method: 'DELETE',
            headers: apiHeaders(),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        applySnapshot(data);
        loadLibrary();
        toast.success(t('queue:removed', { title }));
    } catch (error) {
        toast.error(t('queue:action_remove_error', {
            message: error.message || String(error),
        }));
    } finally {
        actionInFlight = false;
    }
}

async function downloadKindleZip() {
    const button = byId('queueKindleZipBtn');
    if (button) button.disabled = true;
    try {
        const response = await fetch('/api/literary/queue/kindle.zip', {
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
        anchor.download = 'kindle-library.zip';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        setActionStatus(t('queue:kindle_zip_started'));
    } catch (error) {
        setActionStatus(t('queue:kindle_zip_error', { message: error.message || String(error) }), true);
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

    const runButton = byId('queueRunBtn');
    if (runButton) runButton.addEventListener('click', runQueue);

    const pauseButton = byId('queuePauseBtn');
    if (pauseButton) pauseButton.addEventListener('click', togglePause);
    window.addEventListener('localeChanged', renderControl);
    window.addEventListener('localeChanged', () => renderRunnerStatus(lastSnapshot));

    const addButton = byId('queueAddBtn');
    if (addButton) addButton.addEventListener('click', addSelectedBooks);

    const search = byId('queueLibrarySearch');
    if (search) search.addEventListener('input', renderLibrary);

    const statusFilters = byId('queueStatusFilters');
    if (statusFilters) {
        statusFilters.addEventListener('click', (event) => {
            const chip = event.target.closest('[data-filter]');
            if (!chip) return;
            activeFilter = chip.dataset.filter || 'all';
            renderFilters();
            renderRows();
        });
    }
    const seriesFilter = byId('queueSeriesFilter');
    if (seriesFilter) {
        seriesFilter.addEventListener('change', () => {
            activeSeries = seriesFilter.value || '';
            renderRows();
        });
    }
    const queueSearch = byId('queueSearch');
    if (queueSearch) {
        queueSearch.addEventListener('input', () => {
            searchTerm = String(queueSearch.value || '').trim().toLowerCase();
            renderRows();
        });
    }
    const kindleZip = byId('queueKindleZipBtn');
    if (kindleZip) kindleZip.addEventListener('click', downloadKindleZip);

    const now = byId('queueNow');
    if (now) {
        now.addEventListener('click', (event) => {
            const log = event.target.closest('[data-now-log]');
            if (log) {
                openQuality(Number(log.dataset.nowLog));
                return;
            }
            const download = event.target.closest('[data-now-download]');
            if (download) {
                downloadArtifact(
                    Number(download.dataset.nowDownload),
                    download.dataset.nowDownloadName || ''
                );
                return;
            }
            const approve = event.target.closest('[data-now-approve]');
            if (approve) {
                approveBook(Number(approve.dataset.nowApprove));
                return;
            }
            const pause = event.target.closest('[data-now-pause]');
            if (pause) {
                pauseNow(Number(pause.dataset.nowPause));
                return;
            }
            const retry = event.target.closest('[data-now-retry]');
            if (retry) {
                retryBook(Number(retry.dataset.nowRetry));
                return;
            }
            const remove = event.target.closest('[data-now-remove]');
            if (remove) removeBook(Number(remove.dataset.nowRemove));
        });
    }

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
            const quality = event.target.closest('[data-quality-book-id]');
            if (quality) {
                openQuality(Number(quality.dataset.qualityBookId));
                return;
            }
            const approve = event.target.closest('[data-approve-book-id]');
            if (approve) {
                approveBook(Number(approve.dataset.approveBookId));
                return;
            }
            const retry = event.target.closest('[data-retry-book-id]');
            if (retry) {
                retryBook(Number(retry.dataset.retryBookId));
                return;
            }
            const remove = event.target.closest('[data-remove-book-id]');
            if (remove) {
                removeBook(Number(remove.dataset.removeBookId));
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

    const qualityDrawer = byId('queueQualityDrawer');
    if (qualityDrawer) {
        qualityDrawer.addEventListener('click', (event) => {
            if (event.target === qualityDrawer) closeQuality();
        });
    }
    const qualityClose = byId('queueQualityClose');
    if (qualityClose) qualityClose.addEventListener('click', closeQuality);
    const qualityBody = byId('queueQualityBody');
    if (qualityBody) {
        qualityBody.addEventListener('click', (event) => {
            const download = event.target.closest('[data-quality-download]');
            if (download) {
                downloadArtifact(
                    Number(download.dataset.qualityDownload),
                    download.dataset.qualityDownloadName || ''
                );
                return;
            }
            const approve = event.target.closest('[data-quality-approve]');
            if (approve) {
                approveBook(Number(approve.dataset.qualityApprove));
                return;
            }
            const retry = event.target.closest('[data-quality-retry]');
            if (retry) retryBook(Number(retry.dataset.qualityRetry));
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
        const quality = byId('queueQualityDrawer');
        if (quality && !quality.classList.contains('hidden')) {
            closeQuality();
            return;
        }
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

    // If the user opened the Queue tab before the app finished booting, the
    // switchTopTab callback ran too early.  Load it now that the module is ready.
    const tab = byId('tab-queue');
    if (tab && !tab.classList.contains('hidden')) {
        open();
    }
}

function open() {
    // The queue snapshot is the critical path.  Library and Ollama model
    // discovery can be slow while the GPU is translating; they must not block
    // the Now panel and the table from rendering.
    loadLibrary().catch(() => {});
    loadModelOptions().catch(() => {});
    return refresh();
}

export const QueueManager = { initialize, open, refresh, loadLibrary };
