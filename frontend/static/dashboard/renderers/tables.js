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
  const hiddenColumns = new Set(options.hiddenColumns || []);
  const extraColumns = options.extraColumns || [];
  const renderCell =
    options.renderCell ||
    ((row, col) => escapeHtml(formatCell(row[col])));

  if (!rows || !rows.length) {
    renderEmptyState(target, "No data available.");
    return;
  }

  const columns = Object.keys(rows[0]).filter((col) => !hiddenColumns.has(col));
  const allColumns = [
    ...columns.map((key) => ({ key, label: key, extra: false })),
    ...extraColumns.map((col) => ({
      key: col.key,
      label: col.label || col.key,
      render: col.render || (() => ""),
      extra: true,
    })),
  ];
  target.innerHTML = `
    <div class="table-wrap">
      <table${tableClass ? ` class="${escapeHtml(tableClass)}"` : ""}>
        <thead><tr>${allColumns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map(
              (row) => `
            <tr${rowClassName(row) ? ` class="${escapeHtml(rowClassName(row))}"` : ""}>${allColumns.map((col) => `<td>${col.extra ? col.render(row) : renderCell(row, col.key)}</td>`).join("")}</tr>
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
