/**
 * History Manager - Completed translations history
 *
 * Lists the jobs that finished successfully (newest first) and offers the
 * download / open / reveal actions for their output files. The list is a
 * read-only view of `GET /api/history`; paused, interrupted and failed jobs
 * stay in the "Paused Translations" section instead.
 */

import { ApiClient } from '../core/api-client.js';
import { MessageLogger } from '../ui/message-logger.js';
import { DomHelpers } from '../ui/dom-helpers.js';
import { FileActions } from '../files/file-actions.js';
import { t, getCurrentLocale, applyToDOM } from '../i18n/i18n.js';

/**
 * Fetch the translated-files listing without letting its failure sink the
 * history render: a missing or erroring file list only means no output file
 * can be confirmed, and the history itself is still worth showing.
 * @returns {Promise<Set<string>>} Filenames present in translated_files/
 */
async function loadAvailableFiles() {
    try {
        const data = await ApiClient.getFileList();
        const files = (data && data.files) || [];
        return new Set(files.map(file => file.filename));
    } catch (error) {
        console.warn('Could not load the file list for the history availability check:', error);
        return new Set();
    }
}

export const HistoryManager = {
    /**
     * Build one row for a completed job: name and output file on the left,
     * completion date, then the file actions. Output files that were removed are
     * labelled as such, and offer no actions.
     * @param {Object} item - History item from GET /api/history
     * @param {Set<string>} availableFiles - Filenames still present in translated_files/
     * @returns {HTMLElement} Row element for the job
     */
    buildHistoryCard(item, availableFiles) {
        const inputFilename = item.input_filename || t('translation:job_card_unknown');
        const outputFilename = item.output_filename || '';

        // Same display name as the resumable cards: drop the 16-hex upload
        // prefix and the extension, then upper-case the first letter.
        const inputMatch = inputFilename.match(/^([a-f0-9]{16})_(.+)$/);
        const inputOriginalName = inputMatch ? inputMatch[2] : inputFilename;
        const baseName = inputOriginalName.replace(/\.[^.]+$/, '') || inputOriginalName;
        const title = baseName.charAt(0).toUpperCase() + baseName.slice(1);

        const completedRaw = item.completed_at || item.updated_at || '';
        const completedDate = completedRaw
            ? new Date(completedRaw).toLocaleString(getCurrentLocale())
            : t('translation:job_card_na');
        const available = Boolean(outputFilename) && availableFiles.has(outputFilename);

        const row = document.createElement('div');
        row.className = 'history-row';
        row.innerHTML = `
            <div class="history-row__main">
                <span class="history-row__title" title="${DomHelpers.escapeHtml(title)}">${DomHelpers.escapeHtml(title)}</span>
                ${available
                    ? `<span class="history-row__file" title="${DomHelpers.escapeHtml(outputFilename)}">${DomHelpers.escapeHtml(outputFilename)}</span>`
                    : '<span class="history-row__missing" data-i18n="translation:history_status_removed"></span>'}
            </div>
            <time class="history-row__date" datetime="${DomHelpers.escapeHtml(String(completedRaw))}">${DomHelpers.escapeHtml(completedDate)}</time>
            <div class="history-row__actions"></div>
        `;

        if (available) {
            row.querySelector('.history-row__actions').appendChild(FileActions.createActionGroup({
                actions: ['download', 'open', 'reveal'],
                filename: outputFilename,
                variant: 'compact',
            }));
        }
        return row;
    },

    /**
     * Load and display the completed translations history.
     *
     * The section stays hidden while there is nothing to show. A failed load is
     * shown inside the section, with its reason, so it is never silent.
     */
    async loadHistory() {
        const section = DomHelpers.getElement('historySection');
        const loading = DomHelpers.getElement('historyLoading');
        const listContainer = DomHelpers.getElement('historyList');
        const errorBox = DomHelpers.getElement('historyEmpty');
        const show = (el, visible) => el && el.classList.toggle('hidden', !visible);

        show(loading, true);
        show(listContainer, false);
        show(errorBox, false);

        try {
            const [data, availableFiles] = await Promise.all([
                ApiClient.getJobHistory(50),
                loadAvailableFiles(),
            ]);
            const history = (data && data.history) || [];
            show(loading, false);

            if (history.length === 0) {
                show(section, false);
                return;
            }
            if (!listContainer) {
                console.error('Error: historyList element not found');
                return;
            }

            show(section, true);
            show(listContainer, true);
            listContainer.innerHTML = '';
            history.forEach((item) => {
                listContainer.appendChild(this.buildHistoryCard(item, availableFiles));
            });
            applyToDOM(listContainer);
            MessageLogger.addLog(t('translation:history_count_log', { count: history.length }));
        } catch (error) {
            show(loading, false);
            show(section, true);
            show(listContainer, false);
            if (errorBox) {
                errorBox.classList.remove('hidden');
                errorBox.innerHTML = `<p class="history-error">${DomHelpers.escapeHtml(t('translation:history_load_error', { error: error.message || String(error) }))}</p>`;
            }
            console.error('Error loading translation history:', error);
        }
    },

    /**
     * Initialize history manager
     */
    initialize() {
        // Load the history on initialization
        this.loadHistory();

        // Card copy (status badge, type / chunks / date lines) is baked in via
        // t() at render time rather than through reactive data-i18n markup, and
        // the dates are formatted with the current locale. Re-render the whole
        // list on locale switch so it follows the rest of the UI.
        window.addEventListener('localeChanged', () => {
            this.loadHistory();
        });
    }
};
