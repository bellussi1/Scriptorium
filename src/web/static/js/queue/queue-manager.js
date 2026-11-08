/**
 * Read-only persistent literary queue view.
 *
 * The queue is written by the local CLI/wrapper. This module only reads
 * /api/literary/queue; it never starts, pauses or mutates a job.
 */

import { t } from '../i18n/i18n.js';

const API_URL = '/api/literary/queue';
const REFRESH_MS = 10000;

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

function renderRows(data) {
    const body = byId('queueTableBody');
    const empty = byId('queueEmpty');
    const tableWrap = document.querySelector('#tab-queue .queue-table-wrap');
    const books = Array.isArray(data.books) ? data.books : [];

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
                    <td title="${escapeHtml(book.model || '')}">${escapeHtml(modelLabel(book))}</td>
                    <td>${translationId}</td>
                    <td class="queue-updated-cell">${formatDate(book.job_updated_at || book.updated_at)}</td>
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

async function refresh() {
    const button = byId('queueRefreshBtn');
    if (button) button.disabled = true;
    clearError();
    try {
        const response = await fetch(API_URL, {
            headers: { 'X-API-Token': window.__API_TOKEN__ || '' },
            cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.status === 'error') throw new Error(data.error || 'server error');
        renderSummary(data);
        renderRows(data);
        renderEvents(data);
    } catch (error) {
        showError(error.message || String(error));
    } finally {
        if (button) button.disabled = false;
    }
}

function initialize() {
    const button = byId('queueRefreshBtn');
    if (button) button.addEventListener('click', refresh);
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
        const tab = byId('tab-queue');
        if (!tab || tab.classList.contains('hidden')) return;
        if (document.visibilityState !== 'visible') return;
        refresh();
    }, REFRESH_MS);
    window.QueueManager = QueueManager;
}

export const QueueManager = { initialize, refresh };
