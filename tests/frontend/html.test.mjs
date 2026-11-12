import { test } from 'node:test';
import assert from 'node:assert/strict';
import { escapeHtml, html, raw } from '../../src/web/static/js/ui/html.js';

test('interpolated text is escaped', () => {
    const title = `<img src=x onerror=alert(1)> & "quotes" 'single'`;
    assert.equal(
        String(html`<h2>${title}</h2>`),
        '<h2>&lt;img src=x onerror=alert(1)&gt; &amp; &quot;quotes&quot; &#39;single&#39;</h2>',
    );
});

test('nested html results are inserted as markup', () => {
    const inner = html`<b>${'<i>'}</b>`;
    assert.equal(String(html`<p>${inner}</p>`), '<p><b>&lt;i&gt;</b></p>');
});

test('raw strings are inserted as markup', () => {
    assert.equal(String(html`<p>${raw('<em>ok</em>')}</p>`), '<p><em>ok</em></p>');
});

test('null, undefined and false render as nothing; zero renders as 0', () => {
    assert.equal(String(html`[${null}|${undefined}|${false}|${0}]`), '[|||0]');
});

test('arrays of html results join without separators', () => {
    const items = ['a', '<b>'].map((s) => html`<li>${s}</li>`);
    assert.equal(String(html`<ul>${items}</ul>`), '<ul><li>a</li><li>&lt;b&gt;</li></ul>');
});

test('conditional fragments with &&', () => {
    const show = false;
    assert.equal(String(html`<div>${show && html`<span>x</span>`}</div>`), '<div></div>');
});

test('escapeHtml for plain values', () => {
    assert.equal(escapeHtml(undefined), '');
    assert.equal(escapeHtml(42), '42');
    assert.equal(escapeHtml('a&b'), 'a&amp;b');
});
