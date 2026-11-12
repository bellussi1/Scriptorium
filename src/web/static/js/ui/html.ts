/**
 * Escaped HTML templates.
 *
 * `html` returns trusted markup: every interpolated plain string is escaped, and
 * a nested `html` result (or `raw(...)`) is inserted as-is. A book title or log
 * line therefore cannot inject markup, while nested fragments compose without
 * extra wrapping. `null`, `undefined` and `false` render as nothing, so
 * `${condition && fragment}` works.
 */

const RAW = Symbol('raw-html');

export interface RawHtml {
    readonly [RAW]: true;
    readonly value: string;
    toString(): string;
}

/** Marks a string that is already safe markup. */
export function raw(value: string): RawHtml {
    return { [RAW]: true, value, toString: () => value };
}

function isRaw(part: unknown): part is RawHtml {
    return typeof part === 'object' && part !== null && RAW in part;
}

export function escapeHtml(value: unknown): string {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char] as string));
}

function renderPart(part: unknown): string {
    if (part === null || part === undefined || part === false) return '';
    if (Array.isArray(part)) return part.map(renderPart).join('');
    if (isRaw(part)) return part.value;
    return escapeHtml(part);
}

export function html(strings: TemplateStringsArray, ...values: unknown[]): RawHtml {
    let out = '';
    strings.forEach((text, index) => {
        out += text;
        if (index < values.length) out += renderPart(values[index]);
    });
    return raw(out);
}
