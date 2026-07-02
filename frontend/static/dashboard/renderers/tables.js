import { getElement } from "../dom.js";
import { escapeHtml, formatCell } from "../formatters.js";

export function renderEmptyState(targetOrId, message) {
  const target =
    typeof targetOrId === "string" ? getElement(targetOrId) : targetOrId;
  target.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

export function renderTable(targetId, rows) {
  const target = getElement(targetId);

  if (!rows || !rows.length) {
    renderEmptyState(target, "No data available.");
    return;
  }

  const columns = Object.keys(rows[0]);
  target.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map(
              (row) => `
            <tr>${columns.map((col) => `<td>${escapeHtml(formatCell(row[col]))}</td>`).join("")}</tr>
          `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

export function renderTableError(targetId, message) {
  renderEmptyState(targetId, message);
}
