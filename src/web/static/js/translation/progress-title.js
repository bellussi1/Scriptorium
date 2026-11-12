import { DomHelpers } from "../ui/dom-helpers.js";
import { t } from "../i18n/i18n.js";
function createGenericEPUBIcon() {
  return `
            <svg style="width: 48px; height: 72px;" viewBox="0 0 48 72" xmlns="http://www.w3.org/2000/svg">
                <!-- Book cover -->
                <rect x="6" y="3" width="36" height="66" rx="2.5"
                      fill="#5a8ee8" stroke="#3676d8" stroke-width="2"/>
                <!-- Book spine line -->
                <path d="M6 13 L42 13" stroke="#3676d8" stroke-width="1.8"/>
                <!-- Text lines -->
                <path d="M10 22 L38 22 M10 32 L38 32 M10 42 L32 42"
                      stroke="white" stroke-width="2.2" stroke-linecap="round" opacity="0.8"/>
                <!-- EPUB badge -->
                <circle cx="24" cy="56" r="5" fill="white" opacity="0.9"/>
                <text x="24" y="60" text-anchor="middle" font-size="6"
                      fill="#3676d8" font-weight="bold">E</text>
            </svg>
        `;
}
function getFileIcon(fileType) {
  if (fileType === "epub") {
    return createGenericEPUBIcon();
  } else if (fileType === "srt") {
    return "\u{1F3AC}";
  }
  return "\u{1F4C4}";
}
function renderTranslationTitle(file) {
  const titleElement = DomHelpers.getElement("currentFileProgressTitle");
  if (!titleElement) return;
  titleElement.innerHTML = "";
  const mainContainer = document.createElement("div");
  mainContainer.style.display = "flex";
  mainContainer.style.flexDirection = "column";
  mainContainer.style.gap = "8px";
  const translatingText = document.createElement("div");
  translatingText.id = "progressOperationLabel";
  let titleText;
  if (file.operation === "refine") {
    titleText = t("translation:refining");
  } else if (file.operation === "term_fix") {
    titleText = t("translation:fixing_terms");
  } else if (file.refineAfter) {
    titleText = t("translation:translating_step", { step: 1, total: 2, defaultValue: "Translating (1/2)" });
  } else {
    titleText = t("translation:translating");
  }
  translatingText.textContent = titleText;
  translatingText.style.fontWeight = "bold";
  mainContainer.appendChild(translatingText);
  const fileInfoContainer = document.createElement("div");
  fileInfoContainer.style.display = "flex";
  fileInfoContainer.style.alignItems = "center";
  fileInfoContainer.style.gap = "8px";
  const iconContainer = document.createElement("span");
  iconContainer.style.display = "inline-flex";
  iconContainer.style.alignItems = "center";
  iconContainer.style.fontSize = "24px";
  if (file.fileType === "epub" && file.thumbnail) {
    const img = document.createElement("img");
    img.src = `/api/thumbnails/${encodeURIComponent(file.thumbnail)}`;
    img.alt = "Cover";
    img.style.width = "48px";
    img.style.height = "72px";
    img.style.objectFit = "cover";
    img.style.borderRadius = "3px";
    img.style.boxShadow = "0 2px 4px rgba(0,0,0,0.2)";
    img.onerror = () => {
      iconContainer.innerHTML = createGenericEPUBIcon();
    };
    iconContainer.appendChild(img);
  } else {
    iconContainer.innerHTML = getFileIcon(file.fileType);
  }
  fileInfoContainer.appendChild(iconContainer);
  const fileNameContainer = document.createElement("div");
  fileNameContainer.style.display = "flex";
  fileNameContainer.style.flexDirection = "column";
  fileNameContainer.style.gap = "4px";
  const lastDotIndex = file.name.lastIndexOf(".");
  const fileNameWithoutExt = lastDotIndex > 0 ? file.name.substring(0, lastDotIndex) : file.name;
  const fileExt = lastDotIndex > 0 ? file.name.substring(lastDotIndex) : "";
  const nameRow = document.createElement("div");
  nameRow.style.display = "flex";
  nameRow.style.alignItems = "baseline";
  nameRow.style.gap = "2px";
  const fileNameSpan = document.createElement("span");
  fileNameSpan.textContent = fileNameWithoutExt;
  fileNameSpan.style.fontSize = "18px";
  fileNameSpan.style.fontWeight = "bold";
  nameRow.appendChild(fileNameSpan);
  if (fileExt) {
    const extSpan = document.createElement("span");
    extSpan.textContent = fileExt;
    extSpan.style.fontSize = "14px";
    extSpan.style.color = "var(--text-muted-light)";
    nameRow.appendChild(extSpan);
  }
  fileNameContainer.appendChild(nameRow);
  if (file.sourceLanguage && file.targetLanguage) {
    const langSpan = document.createElement("div");
    langSpan.textContent = `${file.sourceLanguage} \u2192 ${file.targetLanguage}`;
    langSpan.style.fontSize = "12px";
    langSpan.style.color = "var(--text-muted-light)";
    langSpan.style.fontWeight = "normal";
    fileNameContainer.appendChild(langSpan);
  }
  fileInfoContainer.appendChild(fileNameContainer);
  mainContainer.appendChild(fileInfoContainer);
  titleElement.appendChild(mainContainer);
}
export {
  createGenericEPUBIcon,
  getFileIcon,
  renderTranslationTitle
};
