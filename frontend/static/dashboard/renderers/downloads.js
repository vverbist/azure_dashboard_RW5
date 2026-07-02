import { urlFor } from "../api.js";
import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

export function renderDownloads(targetId, links) {
  getElement(targetId).innerHTML = (links || [])
    .map(
      ({ label, path }) =>
        `<a class="download-link" href="${escapeHtml(urlFor(path).toString())}">${escapeHtml(label)}</a>`,
    )
    .join("");
}
