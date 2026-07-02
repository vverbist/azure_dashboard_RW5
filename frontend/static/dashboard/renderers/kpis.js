import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

export function renderKpis(kpis) {
  getElement("kpis").innerHTML = (kpis || [])
    .slice(0, 4)
    .map(
      (kpi) => `
      <article class="kpi-card">
        <div class="kpi-label">${escapeHtml(kpi.label)}</div>
        <div class="kpi-value">${escapeHtml(kpi.formatted)}</div>
        ${kpi.status ? `<div class="kpi-status">${escapeHtml(kpi.status)}</div>` : ""}
      </article>
    `,
    )
    .join("");
}

export function renderNarrative(items) {
  const node = getElement("narrative");

  if (!items || !items.length) {
    node.innerHTML =
      "<li>Not enough recognized columns to generate an executive summary.</li>";
    return;
  }

  node.innerHTML = items
    .map((item) => `<li>${escapeHtml(item.text)}</li>`)
    .join("");
}
