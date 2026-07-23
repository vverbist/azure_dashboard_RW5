import { getElement } from "../dom.js";
import { escapeHtml, formatCell } from "../formatters.js";

function renderStructuredCell(content) {
  if (content?.type === "stacked") {
    const secondary =
      content.secondaryText === null || content.secondaryText === undefined
        ? ""
        : `<span class="table-cell-secondary">${escapeHtml(content.secondaryText)}</span>`;
    return `<span class="table-cell-stack"><span class="table-cell-primary">${escapeHtml(formatCell(content.primaryText))}</span>${secondary}</span>`;
  }
  return escapeHtml(formatCell(content?.text));
}

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
  const renderCellContent = options.renderCellContent;
  const renderCell =
    options.renderCell ||
    ((row, col) => escapeHtml(formatCell(row[col])));

  if (!rows || !rows.length) {
    renderEmptyState(target, "No data available.");
    return;
  }

  // An explicit `columns` list takes full control of which columns show and
  // in what order, bypassing the automatic key discovery below.
  const allColumns = options.columns
    ? options.columns.map((col) => ({
        key: col.key,
        label: col.label || col.key,
        render: col.render,
        extra: Boolean(col.render),
        sticky: Boolean(col.sticky),
      }))
    : [
        ...Object.keys(rows[0])
          .filter((col) => !hiddenColumns.has(col))
          .map((key) => ({ key, label: key, extra: false })),
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
        <thead><tr>${allColumns.map((col) => `<th${col.sticky ? ` class="sticky-col"` : ""}>${escapeHtml(col.label)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map(
              (row) => `
            <tr${rowClassName(row) ? ` class="${escapeHtml(rowClassName(row))}"` : ""}>${allColumns.map((col) => `<td${col.sticky ? ` class="sticky-col"` : ""}>${col.extra ? col.render(row) : renderCellContent ? renderStructuredCell(renderCellContent(row, col.key)) : renderCell(row, col.key)}</td>`).join("")}</tr>
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
