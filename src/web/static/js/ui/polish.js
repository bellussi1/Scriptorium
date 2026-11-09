/**
 * Small, UI-only accessibility helpers.
 *
 * The templates use clickable cards and toggle headers that are not native
 * buttons, so keyboard support and ARIA state have to be added explicitly.
 * Keeping the wiring here avoids scattering inline handlers across the HTML.
 */

function syncToggleState(toggle) {
    const section = toggle.nextElementSibling;
    if (!section) return;
    toggle.setAttribute('aria-expanded', String(!section.classList.contains('hidden')));
}

function wireToggle(toggle) {
    if (toggle.dataset.keyboardReady === '1') return;
    toggle.dataset.keyboardReady = '1';
    toggle.addEventListener('click', () => syncToggleState(toggle));
    toggle.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        toggle.click();
    });
    syncToggleState(toggle);
}

function wireUploadZone(zone) {
    if (zone.dataset.keyboardReady === '1') return;
    zone.dataset.keyboardReady = '1';
    zone.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        zone.click();
    });
}

export const UiPolish = {
    initialize() {
        document.querySelectorAll('.prompt-options-toggle').forEach(wireToggle);
        document.querySelectorAll('.file-upload[role="button"]').forEach(wireUploadZone);
    },
};
