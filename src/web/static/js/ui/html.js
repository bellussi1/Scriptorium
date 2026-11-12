const RAW = /* @__PURE__ */ Symbol("raw-html");
function raw(value) {
  return { [RAW]: true, value, toString: () => value };
}
function isRaw(part) {
  return typeof part === "object" && part !== null && RAW in part;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}
function renderPart(part) {
  if (part === null || part === void 0 || part === false) return "";
  if (Array.isArray(part)) return part.map(renderPart).join("");
  if (isRaw(part)) return part.value;
  return escapeHtml(part);
}
function html(strings, ...values) {
  let out = "";
  strings.forEach((text, index) => {
    out += text;
    if (index < values.length) out += renderPart(values[index]);
  });
  return raw(out);
}
export {
  escapeHtml,
  html,
  raw
};
