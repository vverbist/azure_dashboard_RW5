import { getElement } from "../dom.js";
import { escapeHtml } from "../formatters.js";

function describeSource(source) {
  const bits = [];
  if (source.coverage_pct != null) {
    bits.push(`${source.coverage_pct}% coverage`);
  }
  if (source.missing_dates?.length) {
    const shown = source.missing_dates.slice(0, 3).join(", ");
    const extra =
      source.missing_dates.length > 3
        ? ` +${source.missing_dates.length - 3} more`
        : "";
    bits.push(`missing ${shown}${extra}`);
  }
  if (source.stale_days) {
    bits.push(`${source.stale_days}d behind`);
  }
  return bits.join(" · ");
}

export function renderCompleteness(completeness) {
  const target = getElement("completeness-strip");
  const sources = completeness?.sources || [];
  const flagged = sources.filter((source) => source.status !== "complete");

  if (!flagged.length) {
    target.hidden = true;
    target.innerHTML = "";
    return;
  }

  const items = flagged
    .map(
      (source) =>
        `<li><strong>${escapeHtml(source.label)}</strong>: ${escapeHtml(
          describeSource(source),
        )}</li>`,
    )
    .join("");

  target.hidden = false;
  target.innerHTML = `
    <span class="completeness-badge">Data completeness</span>
    <ul class="completeness-list">${items}</ul>
  `;
}
