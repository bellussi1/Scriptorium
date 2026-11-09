/**
 * Apply the fixed English -> Portuguese (Brazil) profile to the browser UI.
 *
 * The template keeps the original language controls so the generic translator
 * can be restored by setting FIXED_LANGUAGE_PAIR to false in
 * core/language-scope.js. When the flag is on:
 *   - the body gets a class that reveals the fixed-pair summary and hides the
 *     original language rows and per-file language controls;
 *   - every language <select> is reduced to the one supported option, so no
 *     stale preference or cloned per-file control can select another pair.
 *
 * The backend is deliberately untouched.
 */
import {
    FIXED_LANGUAGE_PAIR,
    FIXED_SOURCE_LANGUAGE,
    FIXED_TARGET_LANGUAGE,
} from '../core/language-scope.js';
import { DomHelpers } from './dom-helpers.js';

const MAIN_SELECTS = [
    ['sourceLang', FIXED_SOURCE_LANGUAGE],
    ['targetLang', FIXED_TARGET_LANGUAGE],
];

const SAMPLE_SELECTS = [
    ['sampleSourceLang', FIXED_SOURCE_LANGUAGE],
    ['sampleTargetLang', FIXED_TARGET_LANGUAGE],
];

const GLOSSARY_SELECTS = [
    ['glossaryEditorSourceLang', FIXED_SOURCE_LANGUAGE],
    ['glossaryEditorTargetLang', FIXED_TARGET_LANGUAGE],
];

const STYLE_SELECTS = [
    ['styleExtractSourceLang', FIXED_SOURCE_LANGUAGE],
    ['styleExtractTargetLang', FIXED_TARGET_LANGUAGE],
];

function pinSelect(selectId, value) {
    const select = DomHelpers.getElement(selectId);
    if (!select) return;
    if (select.options.length === 1 && select.value === value) return;

    select.innerHTML = '';
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    option.selected = true;
    select.appendChild(option);
    select.value = value;
}

function pinAll() {
    MAIN_SELECTS.forEach(([id, value]) => pinSelect(id, value));
    SAMPLE_SELECTS.forEach(([id, value]) => pinSelect(id, value));
    GLOSSARY_SELECTS.forEach(([id, value]) => pinSelect(id, value));
    STYLE_SELECTS.forEach(([id, value]) => pinSelect(id, value));

    // The custom-language fields only matter in the generic profile.
    ['customSourceLangContainer', 'customTargetLangContainer',
        'glossaryEditorCustomSourceLangContainer',
        'glossaryEditorCustomTargetLangContainer'].forEach((id) => {
        const container = DomHelpers.getElement(id);
        if (container) container.style.display = 'none';
    });
}

export const LanguageScope = {
    initialize() {
        if (!FIXED_LANGUAGE_PAIR) {
            // The template starts in the focused profile to avoid a flash of
            // the full language controls; opt out when the flag is false.
            document.body.classList.remove('literary-language-scope');
            return;
        }

        document.body.classList.add('literary-language-scope');
        pinAll();

        // SettingsManager restores local preferences and FormManager loads the
        // server defaults asynchronously; re-pin after both have had a chance
        // to write to the selects.
        window.addEventListener('defaultConfigLoaded', pinAll);
        window.addEventListener('localeChanged', pinAll);
        setTimeout(pinAll, 0);
        setTimeout(pinAll, 1000);
    },
};
