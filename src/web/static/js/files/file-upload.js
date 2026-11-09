/**
 * File Upload - File upload and drag-drop handling
 *
 * Handles file selection, drag & drop, and upload to server.
 * Manages output filename generation and file queue management.
 */

import { StateManager } from '../core/state-manager.js';
import { ApiClient } from '../core/api-client.js';
import { SOURCE_LANGUAGE, TARGET_LANGUAGE } from '../core/language-scope.js';
import { MessageLogger } from '../ui/message-logger.js';
import { DomHelpers } from '../ui/dom-helpers.js';
import { StatusManager } from '../utils/status-manager.js';
import { QuickTestManager } from '../translation/quick-test.js';
import { t } from '../i18n/i18n.js';

const FILE_QUEUE_STORAGE_KEY = 'tbl_file_queue';

// Track the last uploaded file for language synchronization
let lastUploadedFileName = null;

/**
 * Sanitize a value to be safe in a filename across Windows/macOS/Linux.
 * Strips path separators and reserved chars, collapses whitespace.
 */
function sanitizeFilenamePart(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/[\/\\:*?"<>|]+/g, '_')
        .replace(/\s+/g, ' ')
        .trim();
}

/**
 * Generate output filename based on pattern.
 * Supported placeholders: {originalName}, {targetLang}, {sourceLang}, {model}, {date}, {datetime}, {ext}
 *
 * @param {File|{name: string}} file - Original file (only .name is used)
 * @param {string} pattern - Output pattern
 * @param {Object} [overrides] - Optional explicit values that win over DOM lookups
 * @param {string} [overrides.sourceLang]
 * @param {string} [overrides.targetLang]
 * @param {string} [overrides.model]
 * @returns {string} Generated filename
 */
export function generateOutputFilename(file, pattern, overrides = {}) {
    const fileExtension = file.name.split('.').pop().toLowerCase();
    const originalNameWithoutExt = file.name.replace(/\.[^/.]+$/, "");

    const targetLang = overrides.targetLang || TARGET_LANGUAGE;
    const sourceLang = overrides.sourceLang || SOURCE_LANGUAGE;
    const model = overrides.model ?? DomHelpers.getValue('model') ?? '';

    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const datetime = `${date}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;

    const replacements = {
        '{originalName}': sanitizeFilenamePart(originalNameWithoutExt),
        '{targetLang}': sanitizeFilenamePart(targetLang),
        '{sourceLang}': sanitizeFilenamePart(sourceLang),
        '{model}': sanitizeFilenamePart(model),
        '{date}': date,
        '{datetime}': datetime,
        '{ext}': fileExtension
    };

    let result = pattern || '{originalName} ({targetLang}).{ext}';
    for (const [token, value] of Object.entries(replacements)) {
        result = result.split(token).join(value);
    }
    return result;
}

/**
 * Detect file type from extension
 * @param {string} filename - Filename
 * @returns {string} File type ('txt', 'epub', 'srt')
 */
function detectFileType(filename) {
    const extension = filename.split('.').pop().toLowerCase();

    if (extension === 'epub') return 'epub';
    if (extension === 'srt') return 'srt';
    return 'txt';
}


export const FileUpload = {
    /**
     * Initialize file upload handlers
     */
    initialize() {
        this.setupDragDrop();
        this.setupFileInput();
        // Restore file queue from localStorage synchronously first
        // This ensures files are available immediately on page load
        this.restoreFileQueueSync();
        // Reflect any restored operation in the drop-zone locking state.
        this.refreshZoneLocking();
        // The queue rows are built with t(): rebuild them on a UI language switch.
        window.addEventListener('localeChanged', () => this.updateFileDisplay());
        // Then verify files exist on server after a delay
        setTimeout(() => this.verifyAndCleanupFileQueue(), 1000);
    },






    /**
     * Clear the last uploaded file tracking
     */
    clearLastUploadedFile() {
        lastUploadedFileName = null;
    },

    /**
     * Set a file as the active file for editing
     * Syncs the file's language parameters TO the UI (file → interface)
     * @param {string} filename - Name of the file to set as active
     */
    setActiveFile(filename) {
        const filesToProcess = StateManager.getState('files.toProcess') || [];
        const file = filesToProcess.find(f => f.name === filename);

        if (!file) {
            return false;
        }

        // Only allow setting as active if file is still Queued
        if (file.status !== 'Queued') {
            MessageLogger.showMessage(t('translation:cannot_edit_file_processing', { name: filename }), 'info');
            return false;
        }

        // Update the active file tracking
        lastUploadedFileName = filename;

        // Sync file parameters TO the interface (file → UI)
        // Update display to reflect new active file
        this.updateFileDisplay();

        return true;
    },



    /**
     * Save file queue to localStorage
     * @private
     */
    _saveFileQueue() {
        try {
            const filesToProcess = StateManager.getState('files.toProcess') || [];
            // Save only serializable data (exclude File objects)
            const serializableFiles = filesToProcess.map(f => ({
                name: f.name,
                filePath: f.filePath,
                fileType: f.fileType,
                originalExtension: f.originalExtension,
                status: f.status,
                outputFilename: f.outputFilename,
                size: f.size,
                sourceLanguage: f.sourceLanguage,
                targetLanguage: f.targetLanguage,
                translationId: f.translationId,
                thumbnail: f.thumbnail,
                operation: f.operation || 'translate',
                refineAfter: !!f.refineAfter
            }));
            localStorage.setItem(FILE_QUEUE_STORAGE_KEY, JSON.stringify(serializableFiles));
        } catch {
            // Failed to save file queue
        }
    },

    /**
     * Restore file queue from localStorage synchronously (no server verification)
     * This ensures files appear immediately on page load
     */
    restoreFileQueueSync() {
        try {
            const stored = localStorage.getItem(FILE_QUEUE_STORAGE_KEY);
            if (!stored) return;

            const savedFiles = JSON.parse(stored);
            if (!Array.isArray(savedFiles) || savedFiles.length === 0) return;

            // Restore files to state immediately (reset status to Queued for non-completed files)
            const filesToRestore = savedFiles.map(f => ({
                ...f,
                status: f.status === 'Completed' ? 'Completed' : 'Queued',
                ...(f.status !== 'Completed' ? {
                    sourceLanguage: (f.operation === 'refine' || f.operation === 'term_fix')
                        ? TARGET_LANGUAGE
                        : SOURCE_LANGUAGE,
                    targetLanguage: TARGET_LANGUAGE,
                } : {}),
            }));

            StateManager.setState('files.toProcess', filesToRestore);
            this.updateFileDisplay();

            // Mark the last queued file as active for the row highlight.
            const lastQueuedFile = [...filesToRestore].reverse().find(f => f.status === 'Queued');
            if (lastQueuedFile) {
                lastUploadedFileName = lastQueuedFile.name;
            }
        } catch {
            // Failed to restore file queue
        }
    },


    /**
     * Verify and cleanup file queue after restoration
     * This runs after a delay to verify files still exist on server
     */
    async verifyAndCleanupFileQueue() {
        try {
            const filesToProcess = StateManager.getState('files.toProcess') || [];
            if (filesToProcess.length === 0) return;

            // Get file paths to verify
            const filePaths = filesToProcess.map(f => f.filePath);

            // Verify which files still exist on the server
            const verification = await ApiClient.verifyUploadedFiles(filePaths);

            // Filter to only existing files
            const existingFilePaths = new Set(verification.existing || []);
            const validFiles = filesToProcess.filter(f => existingFilePaths.has(f.filePath));

            // Update state if any files were removed
            if (validFiles.length !== filesToProcess.length) {
                StateManager.setState('files.toProcess', validFiles);
                this.notifyFileListChanged();
            }
        } catch {
            // Failed to verify file queue
        }
    },

    /**
     * Restore file queue from localStorage and verify files exist
     * @deprecated Use restoreFileQueueSync() followed by verifyAndCleanupFileQueue() instead
     */
    async restoreFileQueue() {
        try {
            const stored = localStorage.getItem(FILE_QUEUE_STORAGE_KEY);
            if (!stored) return;

            const savedFiles = JSON.parse(stored);
            if (!Array.isArray(savedFiles) || savedFiles.length === 0) return;

            // Get file paths to verify
            const filePaths = savedFiles.map(f => f.filePath);

            // Verify which files still exist on the server
            const verification = await ApiClient.verifyUploadedFiles(filePaths);

            // Filter to only existing files
            const existingFilePaths = new Set(verification.existing || []);
            const restoredFiles = savedFiles.filter(f => existingFilePaths.has(f.filePath));

            if (restoredFiles.length > 0) {
                // Restore files to state (reset status to Queued for non-completed files)
                const filesToRestore = restoredFiles.map(f => ({
                    ...f,
                    status: f.status === 'Completed' ? 'Completed' : 'Queued'
                }));

                StateManager.setState('files.toProcess', filesToRestore);
                this.notifyFileListChanged();
            }

            // Update localStorage with only existing files
            this._saveFileQueue();

        } catch {
            // Failed to restore file queue
        }
    },



    /**
     * Set up drag and drop event handlers
     */
    setupDragDrop() {
        const zones = [
            { id: 'fileUpload', operation: 'translate' },
            { id: 'fileUploadRefine', operation: 'refine' },
            { id: 'fileUploadTermFix', operation: 'term_fix' }
        ];
        zones.forEach(({ id, operation }) => {
            const uploadArea = DomHelpers.getElement(id);
            if (!uploadArea) return;

            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (uploadArea.classList.contains('zone-disabled')) return;
                DomHelpers.addClass(uploadArea, 'dragging');
            });
            uploadArea.addEventListener('dragleave', () => {
                DomHelpers.removeClass(uploadArea, 'dragging');
            });
            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                DomHelpers.removeClass(uploadArea, 'dragging');
                if (uploadArea.classList.contains('zone-disabled')) {
                    MessageLogger.showMessage(
                        t('translation:zone_locked', { operation }),
                        'info'
                    );
                    return;
                }
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    this.handleFiles(Array.from(files), operation);
                }
            });
        });
    },

    /**
     * Set up file input change handler
     */
    setupFileInput() {
        const fileInput = DomHelpers.getElement('fileInput');
        if (fileInput) {
            fileInput.addEventListener('change', (e) => {
                this.handleFileSelect(e);
            });
        }
        const fileInputRefine = DomHelpers.getElement('fileInputRefine');
        if (fileInputRefine) {
            fileInputRefine.addEventListener('change', (e) => {
                this.handleFileSelectRefine(e);
            });
        }
        const fileInputTermFix = DomHelpers.getElement('fileInputTermFix');
        if (fileInputTermFix) {
            fileInputTermFix.addEventListener('change', (e) => {
                this.handleFileSelectTermFix(e);
            });
        }
    },

    /**
     * Handle file selection from input (Translate zone)
     * @param {Event} event - Change event from file input
     */
    handleFileSelect(event) {
        const files = event.target.files;
        if (files.length > 0) {
            this.handleFiles(Array.from(files), 'translate');
            DomHelpers.setValue('fileInput', '');
        }
    },

    /**
     * Handle file selection from input (Refine zone)
     * @param {Event} event - Change event from file input
     */
    handleFileSelectRefine(event) {
        const files = event.target.files;
        if (files.length > 0) {
            this.handleFiles(Array.from(files), 'refine');
            DomHelpers.setValue('fileInputRefine', '');
        }
    },

    /**
     * Handle file selection from input (Term fix zone)
     * @param {Event} event - Change event from file input
     */
    handleFileSelectTermFix(event) {
        const files = event.target.files;
        if (files.length > 0) {
            this.handleFiles(Array.from(files), 'term_fix');
            DomHelpers.setValue('fileInputTermFix', '');
        }
    },

    /**
     * Resolve the current queue's operation, or null if the queue is empty.
     * @returns {string|null}
     */
    getQueueOperation() {
        const filesToProcess = StateManager.getState('files.toProcess') || [];
        const inFlight = filesToProcess.find(f => f.status === 'Queued' || f.status === 'Preparing...' || f.status === 'Submitted');
        return inFlight ? (inFlight.operation || 'translate') : null;
    },

    /**
     * Apply the zone locking rule: once the queue has a chosen operation,
     * the other drop zones are disabled until the queue empties.
     */
    refreshZoneLocking() {
        const op = this.getQueueOperation();
        const zones = {
            translate: DomHelpers.getElement('fileUpload'),
            refine: DomHelpers.getElement('fileUploadRefine'),
            term_fix: DomHelpers.getElement('fileUploadTermFix'),
        };
        for (const [zoneOp, zone] of Object.entries(zones)) {
            if (zone) zone.classList.toggle('zone-disabled', !!op && op !== zoneOp);
        }
    },

    /**
     * Handle multiple files (from drag-drop or file input)
     * @param {File[]} files - Array of files
     * @param {string} operation - 'translate' or 'refine'
     */
    async handleFiles(files, operation = 'translate') {
        const currentOp = this.getQueueOperation();
        if (currentOp && currentOp !== operation) {
            MessageLogger.showMessage(
                t('translation:zone_locked_current', { current: currentOp }),
                'warning'
            );
            return;
        }

        for (const file of files) {
            await this.addFileToQueue(file, operation);
        }

        // Trigger UI update
        this.notifyFileListChanged();
    },

    /**
     * Add a file to the processing queue
     * @param {File} file - File to add
     * @param {string} operation - 'translate' or 'refine'
     */
    async addFileToQueue(file, operation = 'translate') {
        // Get current files from state
        const filesToProcess = StateManager.getState('files.toProcess') || [];

        // Check for duplicates
        if (filesToProcess.find(f => f.name === file.name)) {
            MessageLogger.showMessage(t('translation:file_duplicate', { name: file.name }), 'info');
            return;
        }

        // Get output filename pattern
        const outputPattern = DomHelpers.getValue('outputFilenamePattern') ||
                             "{originalName} ({targetLang}).{ext}";
        const outputFilename = generateOutputFilename(file, outputPattern);
        const fileExtension = file.name.split('.').pop().toLowerCase();

        MessageLogger.showMessage(t('translation:file_uploading', { name: file.name }), 'info', 4000);

        try {
            // Upload file using ApiClient
            const uploadResult = await ApiClient.uploadFile(file);

            // The literary UI only runs English -> Brazilian Portuguese.
            // Refine/term-fix are monolingual, so both sides are pt-BR.
            const initialSourceLanguage = operation === 'translate'
                ? SOURCE_LANGUAGE
                : TARGET_LANGUAGE;
            const initialTargetLanguage = TARGET_LANGUAGE;

            // Create file object
            const fileObject = {
                name: file.name,
                filePath: uploadResult.file_path,
                fileType: uploadResult.file_type,
                originalExtension: fileExtension,
                status: 'Queued',
                outputFilename: outputFilename,
                size: file.size,
                sourceLanguage: initialSourceLanguage,
                targetLanguage: initialTargetLanguage,
                translationId: null,
                result: null,
                content: null,
                thumbnail: uploadResult.thumbnail || null,  // EPUB cover thumbnail
                operation: operation,
                refineAfter: false
            };

            // Add to state
            const updatedFiles = [...filesToProcess, fileObject];
            StateManager.setState('files.toProcess', updatedFiles);

            // Track this as the last uploaded file for the active-row highlight.
            lastUploadedFileName = file.name;

        } catch (error) {
            MessageLogger.showMessage(
                t('translation:file_upload_failed', { name: file.name, error: error.message }),
                'error'
            );
        }
    },

    /**
     * Update file display in the UI
     */
    updateFileDisplay() {
        const filesToProcess = StateManager.getState('files.toProcess') || [];
        const fileListContainer = DomHelpers.getElement('fileListContainer');
        const fileInfo = DomHelpers.getElement('fileInfo');
        const translateBtn = DomHelpers.getElement('translateBtn');

        if (!fileListContainer) return;

        // Clear existing list
        fileListContainer.innerHTML = '';

        if (filesToProcess.length > 0) {
            // Display files in reverse order (newest first) but keep execution order unchanged
            const displayFiles = [...filesToProcess].reverse();
            displayFiles.forEach(file => {
                const li = document.createElement('li');
                li.setAttribute('data-filename', file.name);

                // Mark the last uploaded file as active (editable via language selectors)
                const isActiveFile = file.name === lastUploadedFileName && file.status === 'Queued';
                li.className = isActiveFile ? 'file-item file-active' : 'file-item';

                // Add click handler to set file as active (only for Queued files)
                if (file.status === 'Queued') {
                    li.style.cursor = 'pointer';
                    li.onclick = () => {
                        this.setActiveFile(file.name);
                    };
                }

                // Header row groups icon, info, and remove button so the cost
                // badge (added below) can sit on its own line inside the li.
                const header = document.createElement('div');
                header.className = 'file-item-header';

                // Icon/thumbnail container
                const iconContainer = document.createElement('span');
                iconContainer.className = 'file-icon';

                if (file.fileType === 'epub' && file.thumbnail) {
                    // Show thumbnail
                    const img = document.createElement('img');
                    img.src = `/api/thumbnails/${encodeURIComponent(file.thumbnail)}`;
                    img.alt = 'Cover';
                    img.className = 'epub-thumbnail';

                    // Fallback to generic SVG on error
                    img.onerror = () => {
                        iconContainer.innerHTML = this._createGenericEPUBIcon();
                    };

                    iconContainer.appendChild(img);
                } else {
                    // Generic icons
                    iconContainer.innerHTML = this._getFileIcon(file.fileType);
                }

                header.appendChild(iconContainer);

                // File info
                const infoSpan = document.createElement('span');
                infoSpan.className = 'file-info';

                // Create file name and size
                const fileNameText = document.createTextNode(`${file.name} (${(file.size / 1024).toFixed(2)} KB) `);
                infoSpan.appendChild(fileNameText);

                // Add language pair display (read-only summary)
                const op = file.operation || 'translate';
                if ((op === 'refine' || op === 'term_fix') && file.targetLanguage) {
                    const langSpan = document.createElement('span');
                    langSpan.className = 'file-languages';
                    langSpan.style.fontSize = '0.85em';
                    langSpan.style.color = 'var(--text-muted-light)';
                    langSpan.textContent = `[${file.targetLanguage}] `;
                    infoSpan.appendChild(langSpan);
                } else if (file.sourceLanguage && file.targetLanguage) {
                    const langSpan = document.createElement('span');
                    langSpan.className = 'file-languages';
                    langSpan.style.fontSize = '0.85em';
                    langSpan.style.color = 'var(--text-muted-light)';
                    langSpan.textContent = `[${file.sourceLanguage} → ${file.targetLanguage}] `;
                    infoSpan.appendChild(langSpan);
                }

                const statusSpan = document.createElement('span');
                statusSpan.className = 'file-status';
                statusSpan.textContent = `(${file.status})`;

                infoSpan.appendChild(statusSpan);

                // Add "Active" badge for the current editable file
                if (isActiveFile) {
                    const activeBadge = document.createElement('span');
                    activeBadge.className = 'file-active-badge';
                    activeBadge.innerHTML = `<span class="material-symbols-outlined" style="font-size: 12px;">edit</span> ${t('translation:active_badge')}`;
                    infoSpan.appendChild(activeBadge);
                }

                header.appendChild(infoSpan);

                // Quick LLM test button — grabs 5 segments from this file and
                // translates them once with the currently-selected LLM/options,
                // so the user can eyeball quality before a big run. Queued only.
                // A term fix has its own preview ("Check matches" in its panel).
                if (file.status === 'Queued' && op !== 'term_fix') {
                    const testBtn = document.createElement('button');
                    testBtn.className = 'file-test-btn';
                    testBtn.title = t('translation:quicktest_button_title');
                    testBtn.setAttribute('aria-label', t('translation:quicktest_button_title'));
                    testBtn.innerHTML = `<span class="material-symbols-outlined">science</span><span class="file-test-btn-label">${DomHelpers.escapeHtml(t('translation:quicktest_button_label'))}</span>`;
                    testBtn.onclick = (e) => {
                        e.stopPropagation();
                        QuickTestManager.open(file);
                    };
                    header.appendChild(testBtn);
                }

                // Remove button
                const removeBtn = document.createElement('button');
                removeBtn.className = 'file-remove-btn';
                removeBtn.title = t('translation:remove_file_title');
                removeBtn.innerHTML = '<span class="material-symbols-outlined">close</span>';
                removeBtn.onclick = (e) => {
                    e.stopPropagation();
                    this.removeFile(file.name);
                };
                header.appendChild(removeBtn);

                li.appendChild(header);

                // Per-file controls: operation badge, language dropdown(s),
                // and a "Refine after" toggle for translate items.
                if (file.status === 'Queued') {
                    li.appendChild(this._buildFileControls(file));
                }

                // Cost badge slot — filled by CostEstimator. Identified by file
                // path (or name as fallback) so the estimator can target it.
                if (file.status === 'Queued') {
                    const costBadge = document.createElement('div');
                    costBadge.className = 'cost-badge file-cost-badge';
                    costBadge.setAttribute(
                        'data-cost-badge-for',
                        file.filePath || file.name
                    );
                    costBadge.style.display = 'none';
                    li.appendChild(costBadge);
                }

                fileListContainer.appendChild(li);
            });

            // Make sure the inactive drop zone is locked when the queue is busy.
            this.refreshZoneLocking();

            // Show file info section
            DomHelpers.show(fileInfo);

            // Enable translate button if not batch active and LLM is connected
            const isBatchActive = StateManager.getState('translation.isBatchActive') || false;
            if (translateBtn) {
                translateBtn.disabled = isBatchActive || !StatusManager.isConnected();
            }
        } else {
            // Hide file info section
            DomHelpers.hide(fileInfo);

            // Disable translate button
            if (translateBtn) {
                translateBtn.disabled = true;
            }

            // Empty queue: unlock both drop zones.
            this.refreshZoneLocking();
        }
    },

    /**
     * Build the per-file controls row.
     * @param {Object} file - File object
     * @returns {HTMLElement}
     * @private
     */
    _buildFileControls(file) {
        const wrap = document.createElement('div');
        wrap.className = 'file-item-controls';

        const op = file.operation || 'translate';

        const badge = document.createElement('span');
        badge.className = `file-op-badge op-${op}`;
        const badgeKeys = {
            refine: 'translation:op_badge_refine',
            term_fix: 'translation:op_badge_term_fix',
        };
        badge.textContent = t(badgeKeys[op] || 'translation:op_badge_translate');
        wrap.appendChild(badge);

        if (op === 'translate') {
            const refineLabel = document.createElement('label');
            refineLabel.title = t('translation:per_file_refine_after_title');
            const refineCheckbox = document.createElement('input');
            refineCheckbox.type = 'checkbox';
            refineCheckbox.checked = !!file.refineAfter;
            refineCheckbox.onclick = (e) => e.stopPropagation();
            refineCheckbox.onchange = (e) => {
                e.stopPropagation();
                this._updateFileField(file.name, 'refineAfter', refineCheckbox.checked);
            };
            refineLabel.appendChild(refineCheckbox);
            refineLabel.appendChild(
                document.createTextNode(' ' + t('translation:per_file_refine_after'))
            );
            wrap.appendChild(refineLabel);
        }

        return wrap;
    },

    /**
     * Update a single field on a queued file and persist.
     * @private
     */
    _updateFileField(filename, field, value) {
        const filesToProcess = StateManager.getState('files.toProcess') || [];
        const fileIndex = filesToProcess.findIndex(f => f.name === filename);
        if (fileIndex === -1) return;
        if (filesToProcess[fileIndex].status !== 'Queued') return;
        filesToProcess[fileIndex][field] = value;
        StateManager.setState('files.toProcess', filesToProcess);
        this._saveFileQueue();

        // Fields that affect cost estimation or the settings summary need to
        // notify listeners; without this the per-file "Refine after" toggle
        // would silently double the inference cost without refreshing the
        // displayed estimate. We dispatch the existing global event rather
        // than poking the cost estimator directly to keep this module
        // dependency-free.
        const costRelevant = new Set([
            'refineAfter', 'operation', 'sourceLanguage', 'targetLanguage',
        ]);
        if (costRelevant.has(field)) {
            window.dispatchEvent(new CustomEvent('translationOptionsChanged'));
        }
    },

    /**
     * Notify that file list has changed (triggers UI update)
     */
    notifyFileListChanged() {
        // Update display immediately
        this.updateFileDisplay();

        // Persist to localStorage
        this._saveFileQueue();

        // Emit event so other modules can react
        const event = new CustomEvent('fileListChanged');
        window.dispatchEvent(event);
    },

    /**
     * Remove a file from the queue by name
     * @param {string} filename - Name of file to remove
     */
    removeFile(filename) {
        const filesToProcess = StateManager.getState('files.toProcess') || [];
        const updatedFiles = filesToProcess.filter(f => f.name !== filename);
        StateManager.setState('files.toProcess', updatedFiles);

        // If removing the last uploaded file, clear tracking
        if (filename === lastUploadedFileName) {
            lastUploadedFileName = null;
        }

        this.notifyFileListChanged();
    },

    /**
     * Clear all files from queue
     */
    clearAll() {
        StateManager.setState('files.toProcess', []);
        lastUploadedFileName = null;
        this.notifyFileListChanged();
    },

    /**
     * Get file icon based on file type
     * @param {string} fileType - File type ('txt', 'epub', 'srt')
     * @returns {string} HTML string for icon
     */
    _getFileIcon(fileType) {
        if (fileType === 'epub') {
            return this._createGenericEPUBIcon();
        } else if (fileType === 'srt') {
            return '🎬';
        }
        return '📄';
    },

    /**
     * Create generic EPUB icon as SVG
     * @returns {string} SVG HTML string
     */
    _createGenericEPUBIcon() {
        return `
            <svg class="generic-epub-icon" viewBox="0 0 48 64" xmlns="http://www.w3.org/2000/svg">
                <!-- Book cover -->
                <rect x="8" y="4" width="32" height="56" rx="2"
                      fill="#5a8ee8" stroke="#3676d8" stroke-width="2"/>
                <!-- Book spine line -->
                <path d="M8 12 L40 12" stroke="#3676d8" stroke-width="1.5"/>
                <!-- Text lines -->
                <path d="M12 20 L36 20 M12 28 L36 28 M12 36 L30 36"
                      stroke="white" stroke-width="2" stroke-linecap="round" opacity="0.8"/>
                <!-- EPUB badge -->
                <circle cx="24" cy="48" r="4" fill="white" opacity="0.9"/>
                <text x="24" y="51" text-anchor="middle" font-size="5"
                      fill="#3676d8" font-weight="bold">E</text>
            </svg>
        `;
    }
};
