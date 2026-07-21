import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

function formatDataDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function renderDataAvailability(value, fallback = "Unavailable") {
  const displayValue = formatDataDate(value) || fallback;
  getElement("data-available-through").innerHTML = `
    <span>Data available through</span>
    <strong>${escapeHtml(displayValue)}</strong>
  `;
}

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
