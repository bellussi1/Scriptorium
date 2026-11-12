/**
 * File Manager - File list management and operations
 *
 * Handles file list display, selection management, batch operations
 * (download/delete), and individual file actions.
 */

import { StateManager } from '../core/state-manager.js';
import { ApiClient } from '../core/api-client.js';
import { MessageLogger } from '../ui/message-logger.js';
import { DomHelpers } from '../ui/dom-helpers.js';
import { FileActions } from './file-actions.js';
import { t } from '../i18n/i18n.js';

export const FileManager = {
    /**
     * Initialize file manager
     */
    initialize() {
        this.setupEventListeners();
        this.refreshFileList();
    },

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // Listen for file list changes
        window.addEventListener('fileListChanged', () => {
            this.refreshFileList();
        });

        // Re-render the list when the UI locale changes: rows are built with
        // t() at render time, so a full refresh applies the new translations
        // (including the "Download N" / "Delete N" selection buttons).
        window.addEventListener('localeChanged', () => {
            this.refreshFileList();
        });

        // Select all checkbox
        const selectAllCheckbox = DomHelpers.getElement('selectAllFiles');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', () => {
                this.toggleSelectAll();
            });
        }

        // Batch download button
        const batchDownloadBtn = DomHelpers.getElement('batchDownloadBtn');
        if (batchDownloadBtn) {
            batchDownloadBtn.addEventListener('click', () => {
                this.downloadSelectedFiles();
            });
        }

        // Batch delete button
        const batchDeleteBtn = DomHelpers.getElement('batchDeleteBtn');
        if (batchDeleteBtn) {
            batchDeleteBtn.addEventListener('click', () => {
                this.deleteSelectedFiles();
            });
        }

        // Artifact filter: final editions only by default.
        const showAllArtifacts = DomHelpers.getElement('showAllArtifacts');
        if (showAllArtifacts) {
            showAllArtifacts.addEventListener('change', () => {
                this.refreshFileList();
            });
        }
    },

    /**
     * Refresh file list from server
     */
    async refreshFileList() {
        const loadingDiv = DomHelpers.getElement('fileListLoading');
        const containerDiv = DomHelpers.getElement('fileManagementContainer');
        const tableBody = DomHelpers.getElement('fileTableBody');
        const emptyDiv = DomHelpers.getElement('fileListEmpty');

        if (!tableBody) return;

        // Show loading, hide container (use inline style to override)
        if (loadingDiv) loadingDiv.style.display = 'block';
        if (containerDiv) containerDiv.style.display = 'none';

        try {
            const data = await ApiClient.getFileList();

            // Hide loading, show container (use inline style to override)
            if (loadingDiv) loadingDiv.style.display = 'none';
            if (containerDiv) containerDiv.style.display = 'block';

            // Clear existing table rows
            tableBody.innerHTML = '';

            StateManager.setState('files.selected', new Set());

            // Reset "Select All" checkbox
            const selectAllCheckbox = DomHelpers.getElement('selectAllFiles');
            if (selectAllCheckbox) {
                selectAllCheckbox.checked = false;
            }

            this.updateFileSelectionButtons();

            const showAll = Boolean(DomHelpers.getElement('showAllArtifacts')?.checked);
            const bestByBook = this.finalArtifacts(data.files);
            const bestEntries = [...bestByBook.values()];
            const bestNames = new Set(bestEntries.map(entry => entry.file.filename));
            const bestByFile = new Map(bestEntries.map(entry => [entry.file.filename, entry]));
            const visibleFiles = data.files.filter(file => {
                const info = this.artifactInfo(file.filename);
                if (!info) return true;
                if (!info.bookFile) return showAll;
                return showAll || bestNames.has(file.filename);
            });
            visibleFiles.sort((a, b) => {
                const infoA = this.artifactInfo(a.filename) || { rank: 0, book: a.filename };
                const infoB = this.artifactInfo(b.filename) || { rank: 0, book: b.filename };
                const finalA = bestNames.has(a.filename) ? 0 : 1;
                const finalB = bestNames.has(b.filename) ? 0 : 1;
                if (finalA !== finalB) return finalA - finalB;
                const qualityA = infoA.bookFile === false ? 1 : 0;
                const qualityB = infoB.bookFile === false ? 1 : 0;
                if (qualityA !== qualityB) return qualityA - qualityB;
                if (infoA.book !== infoB.book) return String(infoA.book).localeCompare(String(infoB.book));
                if (infoA.rank !== infoB.rank) return infoB.rank - infoA.rank;
                return new Date(b.modified_date) - new Date(a.modified_date);
            });

            if (data.files.length === 0 || visibleFiles.length === 0) {
                if (emptyDiv) emptyDiv.style.display = 'block';
                const fileTable = containerDiv.querySelector('.file-table');
                if (fileTable) {
                    fileTable.style.display = 'none';
                }
            } else {
                if (emptyDiv) emptyDiv.style.display = 'none';
                const fileTable = containerDiv.querySelector('.file-table');
                if (fileTable) {
                    fileTable.style.display = 'table';
                }

                // Populate table with the final edition of each book first;
                // intermediates stay behind the "show all versions" toggle.
                visibleFiles.forEach(file => {
                    const artifact = bestByFile.get(file.filename) || {
                        info: this.artifactInfo(file.filename),
                        final: false,
                    };
                    const row = this.createFileRow(file, artifact);
                    tableBody.appendChild(row);
                });
            }

            const filterStatus = DomHelpers.getElement('fileFilterStatus');
            if (filterStatus) {
                filterStatus.textContent = showAll
                    ? ''
                    : t('files:final_only_status', {
                        visible: visibleFiles.length,
                        total: data.files.length,
                    });
            }

            DomHelpers.setText('totalFileCount', data.total_files);
            DomHelpers.setText('totalFileSize', `${data.total_size_mb} MB`);

            StateManager.setState('files.managed', data.files);

        } catch (error) {
            if (loadingDiv) loadingDiv.style.display = 'none';
            MessageLogger.showMessage(t('files:load_failed', { error: error.message }), 'error');
        }
    },

    /**
     * Classify an EPUB pipeline artifact so the Files tab says which copy is
     * the reader edition instead of showing six near-identical filenames.
     *
     * Rank is the pipeline order used by the queue artifact picker:
     * refined > reader legacy > fixed-v2 > fixed > raw.
     * @param {string} filename
     * @returns {{kind: string, key: string, rank: number, book: string, bookFile: boolean}|null}
     */
    artifactInfo(filename) {
        const name = String(filename || '');
        if (/\.quality\.json$/i.test(name)) {
            return { kind: 'quality', key: 'badge_quality', rank: 0, book: '', bookFile: false };
        }
        const book = name
            .replace(/\.refined\.epub$/i, '')
            .replace(/ - reader\d+\.epub$/i, '')
            .replace(/ - fixed-v2\.epub$/i, '')
            .replace(/ - fixed\.epub$/i, '')
            .replace(/\.epub$/i, '')
            .replace(/\s*\(pt-BR\)$/i, '')
            .trim();
        if (/\.refined\.epub$/i.test(name)) {
            return { kind: 'reader', key: 'badge_reader', rank: 5, book, bookFile: true };
        }
        if (/ - reader\d+\.epub$/i.test(name)) {
            return { kind: 'reader-legacy', key: 'badge_reader_legacy', rank: 4, book, bookFile: true };
        }
        if (/ - fixed-v2\.epub$/i.test(name)) {
            return { kind: 'base', key: 'badge_fixed_v2', rank: 3, book, bookFile: true };
        }
        if (/ - fixed\.epub$/i.test(name)) {
            return { kind: 'fixed', key: 'badge_fixed', rank: 2, book, bookFile: true };
        }
        if (/\(pt-BR\)\.epub$/i.test(name)) {
            return { kind: 'raw', key: 'badge_raw', rank: 1, book, bookFile: true };
        }
        return null;
    },

    /**
     * Pick the best artifact for each book. A raw/fixed-only book is still
     * shown (otherwise the EPUB would disappear), but it is not marked Final.
     * @param {Array} files
     * @returns {Map<string, {file: Object, info: Object, final: boolean}>}
     */
    finalArtifacts(files) {
        const best = new Map();
        for (const file of files) {
            const info = this.artifactInfo(file.filename);
            if (!info || !info.bookFile) continue;
            const current = best.get(info.book);
            if (!current || info.rank > current.info.rank) {
                best.set(info.book, { file, info, final: info.rank >= 4 });
            }
        }
        return best;
    },

    /**
     * Create file row element
     * @param {Object} file - File data object
     * @param {{info: Object|null, final: boolean}} [artifact] - Pipeline role
     * @returns {HTMLElement} Table row element
     */
    createFileRow(file, artifact = null) {
        const row = document.createElement('tr');

        const modifiedDate = new Date(file.modified_date);
        const formattedDate = modifiedDate.toLocaleString();

        const isAudioFile = file.file_type === 'opus' || file.file_type === 'mp3';
        const fileIconClass = file.file_type === 'epub' ? 'book' :
                        file.file_type === 'srt' ? 'movie' :
                        file.file_type === 'txt' ? 'description' :
                        file.file_type === 'pdf' ? 'picture_as_pdf' :
                        isAudioFile ? 'headphones' : 'attach_file';

        const supportsTTS = ['epub', 'txt', 'srt'].includes(file.file_type);
        const safeFilename = DomHelpers.escapeHtml(file.filename);
        const info = artifact ? artifact.info : this.artifactInfo(file.filename);
        const isFinal = Boolean(artifact && artifact.final);
        const finalBadge = isFinal
            ? `<span class="file-artifact-badge is-final" title="${DomHelpers.escapeHtml(t('files:badge_final_title'))}">${DomHelpers.escapeHtml(t('files:badge_final'))}</span>`
            : '';
        const badgeHtml = info
            ? `<span class="file-artifact-badge is-${info.kind}">${DomHelpers.escapeHtml(t(`files:${info.key}`))}</span>`
            : '';
        const tooltipInfo = `${file.file_type.toUpperCase()} • ${file.size_mb} MB • ${formattedDate}`;

        row.innerHTML = `
            <td style="width: 36px; padding: 0.5rem;">
                <input type="checkbox" class="file-checkbox" data-filename="${safeFilename}"
                       aria-label="${safeFilename}">
            </td>
            <td style="max-width: 0;">
                <div class="file-name-cell">
                    <span class="clickable-filename" data-filename="${safeFilename}" data-action="open" title="${tooltipInfo}">
                        <span class="material-symbols-outlined file-icon-cell">${fileIconClass}</span>
                        <span class="filename-text">${safeFilename}</span>
                    </span>
                    ${finalBadge}${badgeHtml}
                </div>
            </td>
            <td class="file-row-actions">
                <div class="file-action-group file-action-group--compact"></div>
            </td>
        `;

        const checkbox = row.querySelector('.file-checkbox');
        if (checkbox) {
            checkbox.addEventListener('change', () => this.toggleFileSelection(file.filename));
        }

        const openLink = row.querySelector('.clickable-filename');
        if (openLink) {
            openLink.addEventListener('click', () => FileActions.open(file.filename));
        }

        const actionsHost = row.querySelector('.file-action-group');

        if (supportsTTS) {
            const audiobookBtn = document.createElement('button');
            audiobookBtn.type = 'button';
            audiobookBtn.className = 'file-action-btn audiobook';
            audiobookBtn.title = t('translation:audiobook_btn_title');
            audiobookBtn.setAttribute('aria-label', t('translation:audiobook_btn_title'));
            audiobookBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 0.875rem;">headphones</span>';
            audiobookBtn.addEventListener('click', () => window.createAudiobook(file.filename, file.file_path));
            actionsHost.appendChild(audiobookBtn);
        }

        const refreshAfterDelete = () => this.refreshFileList();
        ['open', 'reveal', 'download', 'delete'].forEach(action => {
            actionsHost.appendChild(FileActions.createActionButton({
                action,
                filename: file.filename,
                variant: 'compact',
                onAfter: action === 'delete' ? refreshAfterDelete : undefined
            }));
        });

        return row;
    },

    /**
     * Toggle file selection
     * @param {string} filename - Filename to toggle
     */
    toggleFileSelection(filename) {
        const selectedFiles = StateManager.getState('files.selected');

        if (selectedFiles.has(filename)) {
            selectedFiles.delete(filename);
        } else {
            selectedFiles.add(filename);
        }

        StateManager.setState('files.selected', selectedFiles);
        this.updateFileSelectionButtons();
    },

    /**
     * Select all files
     */
    selectAllFiles() {
        const checkboxes = DomHelpers.getElements('.file-checkbox');
        const selectedFiles = new Set();

        checkboxes.forEach(checkbox => {
            checkbox.checked = true;
            const filename = checkbox.getAttribute('data-filename');
            selectedFiles.add(filename);
        });

        StateManager.setState('files.selected', selectedFiles);
        this.updateFileSelectionButtons();
    },

    /**
     * Deselect all files
     */
    deselectAllFiles() {
        const checkboxes = DomHelpers.getElements('.file-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });

        StateManager.setState('files.selected', new Set());
        this.updateFileSelectionButtons();
    },

    /**
     * Toggle select all
     */
    toggleSelectAll() {
        const checkboxes = DomHelpers.getElements('.file-checkbox');
        const selectAllFiles = DomHelpers.getElement('selectAllFiles');

        // Use the Select All checkbox state
        const isChecked = selectAllFiles.checked;

        if (isChecked) {
            this.selectAllFiles();
        } else {
            this.deselectAllFiles();
        }
    },

    /**
     * Update file selection button states
     */
    updateFileSelectionButtons() {
        const selectedFiles = StateManager.getState('files.selected');
        const hasSelection = selectedFiles.size > 0;

        DomHelpers.setDisabled('batchDownloadBtn', !hasSelection);
        DomHelpers.setDisabled('batchDeleteBtn', !hasSelection);

        // Update "Select All" checkbox state based on actual selection
        const checkboxes = DomHelpers.getElements('.file-checkbox');
        const selectAllCheckbox = DomHelpers.getElement('selectAllFiles');
        if (selectAllCheckbox && checkboxes.length > 0) {
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            selectAllCheckbox.checked = allChecked;
        }

        // Update button text with count
        const downloadBtn = DomHelpers.getElement('batchDownloadBtn');
        const deleteBtn = DomHelpers.getElement('batchDeleteBtn');
        if (hasSelection) {
            if (downloadBtn) downloadBtn.innerHTML = `<span class="material-symbols-outlined">download</span> ${t('files:download_selected_with_count', { count: selectedFiles.size })}`;
            if (deleteBtn) deleteBtn.innerHTML = `<span class="material-symbols-outlined">delete</span> ${t('files:delete_selected_with_count', { count: selectedFiles.size })}`;
        } else {
            if (downloadBtn) downloadBtn.innerHTML = `<span class="material-symbols-outlined">download</span> ${t('files:download_selected')}`;
            if (deleteBtn) deleteBtn.innerHTML = `<span class="material-symbols-outlined">delete</span> ${t('files:delete_selected')}`;
        }
    },

    async deleteSingleFile(filename) {
        await FileActions.delete(filename, { onDeleted: () => this.refreshFileList() });
    },

    /**
     * Download selected files as ZIP
     */
    async downloadSelectedFiles() {
        const selectedFiles = StateManager.getState('files.selected');

        if (selectedFiles.size === 0) {
            MessageLogger.showMessage(t('files:no_selection_download'), 'error');
            return;
        }

        try {
            const response = await fetch(`${ApiClient.getBaseUrl()}/api/files/batch/download`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    filenames: Array.from(selectedFiles)
                })
            });

            if (response.ok) {
                // Download the zip file
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `translated_files_${new Date().getTime()}.zip`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);

                MessageLogger.showMessage(t('files:downloaded_as_zip', { count: selectedFiles.size }), 'success');
            } else {
                const data = await response.json();
                MessageLogger.showMessage(data.error || t('files:download_failed_default'), 'error');
            }
        } catch (error) {
            MessageLogger.showMessage(t('files:download_error', { error: error.message }), 'error');
        }
    },

    /**
     * Delete selected files
     */
    async deleteSelectedFiles() {
        const selectedFiles = StateManager.getState('files.selected');

        if (selectedFiles.size === 0) {
            MessageLogger.showMessage(t('files:no_selection_delete'), 'error');
            return;
        }

        if (!confirm(t('files:confirm_delete_selected', { count: selectedFiles.size }))) {
            return;
        }

        try {
            const response = await fetch(`${ApiClient.getBaseUrl()}/api/files/batch/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    filenames: Array.from(selectedFiles)
                })
            });

            const data = await response.json();

            if (response.ok) {
                const message = data.failed.length > 0
                    ? t('files:deleted_summary_with_failed', { count: data.total_deleted, failed: data.failed.length })
                    : t('files:deleted_summary', { count: data.total_deleted });
                MessageLogger.showMessage(message, data.failed.length > 0 ? 'info' : 'success');
                this.refreshFileList();
            } else {
                MessageLogger.showMessage(data.error || t('files:delete_failed_default'), 'error');
            }
        } catch (error) {
            MessageLogger.showMessage(t('files:delete_error', { error: error.message }), 'error');
        }
    },

};

// Selection toggle stays here (state lives in FileManager); the per-file
// actions (open/reveal/download) are exposed globally by FileActions itself.
window.toggleFileSelection = (filename) => FileManager.toggleFileSelection(filename);
window.deleteSingleFile = (filename) => FileManager.deleteSingleFile(filename);
