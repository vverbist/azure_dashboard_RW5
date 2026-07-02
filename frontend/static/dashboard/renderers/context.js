import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

export function renderContext(context) {
  const items = [
    ["Period", context?.period || "-"],
    ["Rows", Number(context?.rows || 0).toLocaleString()],
    ["Granularity", context?.granularity || "-"],
    ["Source rows", Number(context?.source_rows || 0).toLocaleString()],
  ];

  getElement("context").innerHTML = items
    .map(
      ([label, value]) => `
      <div class="context-item">
        <div class="context-label">${escapeHtml(label)}</div>
        <div class="context-value">${escapeHtml(value)}</div>
      </div>
    `,
    )
    .join("");
}

export function renderSelectedPeriodScope(context) {
  const rows = context?.rows?.toLocaleString?.() || context?.rows || 0;
  getElement("selected-period-scope").textContent =
    `Uses ${context?.period || "the selected range"} with ${rows} rows.`;
}
