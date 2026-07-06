import { getElement } from "../dom.js";
import { escapeHtml, formatCell } from "../formatters.js";

export function renderEmptyState(targetOrId, message) {
  const target =
    typeof targetOrId === "string" ? getElement(targetOrId) : targetOrId;
  target.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

export function renderTable(targetId, rows, options = {}) {
  const target = getElement(targetId);
  const tableClass = options.tableClass || "";
  const rowClassName = options.rowClassName || (() => "");

  if (!rows || !rows.length) {
    renderEmptyState(target, "No data available.");
    return;
  }

  const columns = Object.keys(rows[0]);
  target.innerHTML = `
    <div class="table-wrap">
      <table${tableClass ? ` class="${escapeHtml(tableClass)}"` : ""}>
        <thead><tr>${columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map(
              (row) => `
            <tr${rowClassName(row) ? ` class="${escapeHtml(rowClassName(row))}"` : ""}>${columns.map((col) => `<td>${escapeHtml(formatCell(row[col]))}</td>`).join("")}</tr>
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
