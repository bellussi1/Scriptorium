/**
 * Pre-flight Rules - turns the current form/file state into ordered advice.
 *
 * Two exports with deliberately opposite natures:
 *  - buildContext() reads the DOM, StateManager and ModelDetector once.
 *  - evaluateRules() is pure and importless, so it can be unit-tested with a
 *    hand-written object literal and reasoned about without a browser.
 *
 * The module emits i18n *keys* only. Resolving them with t() is the renderer's
 * job, which is what keeps the advice reactive to a locale switch.
 */

import { DomHelpers } from './dom-helpers.js';
import { StateManager } from '../core/state-manager.js';
import { ModelDetector } from '../providers/model-detector.js';

/**
 * @typedef {Object} PreflightContext
 * @property {string}   provider          lowercased #llmProvider value, '' if unset
 * @property {string}   model             #model value, '' if unset
 * @property {boolean}  isSmallModel      ModelDetector.isSmallModel(model)
 * @property {boolean}  hasQueuedFiles    at least one file with status === 'Queued'
 * @property {string[]} queuedExts        UPPERCASED originalExtension of queued files, deduped, e.g. ['EPUB']
 * @property {boolean}  plainTextMode     #plainTextMode.checked
 * @property {string}   glossaryId        #glossarySelect value, '' if none
 * @property {string}   instructionId     #customInstructionSelect value, '' if none
 * @property {number}   parallelWorkers   parseInt(#parallelWorkers), 1 when NaN
 * @property {boolean}  parallelVisible   #parallelWorkersGroup is not display:none
 */

/**
 * @typedef {Object} PreflightRule
 * @property {string}  id           one of the frozen rule ids
 * @property {'advice'|'warning'|'danger'} severity
 * @property {string}  labelKey     i18n key, 'ns:key' form
 * @property {string}  reasonKey    i18n key, 'ns:key' form
 * @property {Object}  params       interpolation params for labelKey and reasonKey
 * @property {'expandPanel'|'navigate'} action
 * @property {string}  focusId      DOM id of the control to focus after the action
 * @property {string|null} navigateKey  TARGETS key; non-null iff action === 'navigate'
 */

// Formats that carry inline markup the LLM can drop. Plain Text Mode is the
// mitigation, so these are the only extensions that trigger tag-loss advice.
const TAGGED_EXTENSIONS = ['EPUB', 'DOCX'];

/**
 * Collect the queued files' extensions, uppercased and deduped.
 * @param {Array<Object>} files - StateManager 'files.toProcess' entries
 * @returns {string[]} Extensions such as ['EPUB', 'TXT']
 */
function collectQueuedExtensions(files) {
    const seen = [];
    files.forEach(file => {
        if (!file || file.status !== 'Queued') return;
        const ext = (file.originalExtension || '').toUpperCase();
        if (ext && !seen.includes(ext)) seen.push(ext);
    });
    return seen;
}

/**
 * Impure. Reads the DOM, StateManager and ModelDetector.
 * Every lookup falls back to a documented default, so a missing element can
 * never throw here: the zone has to survive a partially rendered page.
 * @returns {PreflightContext} Current pre-flight context
 */
export function buildContext() {
    const model = DomHelpers.getValue('model') || '';
    const files = StateManager.getState('files.toProcess') || [];
    // Term-fix files are left out: every rule here advises on a translation or
    // refinement prompt, and a term fix sends neither.
    const queuedFiles = files.filter(f => f && f.status === 'Queued' && f.operation !== 'term_fix');
    const plainTextModeEl = DomHelpers.getElement('plainTextMode');
    const parallelWorkers = parseInt(DomHelpers.getValue('parallelWorkers'), 10);
    const parallelGroup = DomHelpers.getElement('parallelWorkersGroup');

    return {
        provider: (DomHelpers.getValue('llmProvider') || '').trim().toLowerCase(),
        model,
        isSmallModel: !!ModelDetector.isSmallModel(model),
        hasQueuedFiles: queuedFiles.length > 0,
        queuedExts: collectQueuedExtensions(queuedFiles),
        plainTextMode: !!(plainTextModeEl && plainTextModeEl.checked),
        glossaryId: (DomHelpers.getValue('glossarySelect') || '').trim(),
        instructionId: (DomHelpers.getValue('customInstructionSelect') || '').trim(),
        parallelWorkers: Number.isNaN(parallelWorkers) ? 1 : parallelWorkers,
        // Mirrors how provider-manager.js shows/hides the group, rather than
        // duplicating its provider-capability list.
        parallelVisible: parallelGroup ? parallelGroup.style.display !== 'none' : false,
    };
}

/**
 * Pure. No DOM, no localStorage, no t(), no Date, no Math.random.
 * @param {PreflightContext} ctx - Context, typically from buildContext()
 * @returns {PreflightRule[]} Applicable rules, in fixed order
 */
export function evaluateRules(ctx) {
    if (!ctx || !ctx.hasQueuedFiles) return [];

    const rules = [];

    const queuedExts = ctx.queuedExts || [];
    const tagged = queuedExts.filter(ext => TAGGED_EXTENSIONS.indexOf(ext) !== -1);
    const firstTagged = tagged[0];
    const taggedAtRisk = tagged.length > 0 && !ctx.plainTextMode;

    // The warning supersedes the plain advice: same control, stronger wording.
    const smallModelTagged = taggedAtRisk && !!ctx.isSmallModel;

    if (smallModelTagged) {
        rules.push({
            id: 'small-model-tagged',
            severity: 'warning',
            labelKey: 'translation:preflight_warning_action',
            reasonKey: 'translation:preflight_warning_small_model_tagged',
            params: { model: ctx.model, ext: firstTagged },
            action: 'expandPanel',
            focusId: 'plainTextMode',
            navigateKey: null,
        });
    }

    if (taggedAtRisk && !smallModelTagged) {
        rules.push({
            id: 'plain-text-mode',
            severity: 'advice',
            labelKey: 'translation:summary_plain_text_mode',
            reasonKey: 'translation:preflight_reason_plain_text',
            params: { ext: firstTagged },
            action: 'expandPanel',
            focusId: 'plainTextMode',
            navigateKey: null,
        });
    }

    if (ctx.parallelVisible && ctx.provider !== 'ollama' && ctx.parallelWorkers <= 1) {
        rules.push({
            id: 'parallel-requests',
            severity: 'advice',
            labelKey: 'translation:preflight_chip_parallel',
            reasonKey: 'translation:preflight_reason_parallel',
            params: {},
            action: 'navigate',
            focusId: 'parallelWorkers',
            navigateKey: 'parallelWorkers',
        });
    }

    if (!ctx.glossaryId) {
        rules.push({
            id: 'glossary',
            severity: 'advice',
            labelKey: 'translation:preflight_chip_glossary',
            reasonKey: 'translation:preflight_reason_glossary',
            params: {},
            action: 'expandPanel',
            focusId: 'glossarySelect',
            navigateKey: null,
        });
    }

    if (!ctx.instructionId) {
        rules.push({
            id: 'custom-instructions',
            severity: 'advice',
            // Label borrowed from the settings namespace rather than duplicated:
            // the panel's own field label is the same words, and a second copy
            // would drift the day one of them is reworded.
            labelKey: 'settings:custom_instructions_label',
            reasonKey: 'translation:preflight_reason_instructions',
            params: {},
            action: 'expandPanel',
            focusId: 'customInstructionSelect',
            navigateKey: null,
        });
    }

    return rules;
}
