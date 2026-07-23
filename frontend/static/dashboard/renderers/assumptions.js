import { getElement } from "../dom.js";
import { escapeHtml, formatCell, timestampLabel } from "../formatters.js";

export function renderAssumptionStrip(state, basis) {
  const items = [
    [
      "Greenchoice afslag",
      `${formatCell(state.greenchoice_afslag_percentage)}%`,
    ],
    ["Afslag floor", `${formatCell(state.greenchoice_afslag_floor)} EUR/MWh`],
    ["GvO", `${formatCell(state.gvo_value)} EUR/MWh`],
    ["Strike price", `${formatCell(state.strike_price)} EUR/MWh`],
    ["Timezone", timestampLabel(state.timestamp_col)],
  ];

  const greenchoice = basis?.greenchoice;
  const basisChip = greenchoice
    ? `<div class="assumption-chip basis-${
        greenchoice.basis === "Official" ? "official" : "scenario"
      }" title="${escapeHtml(
        greenchoice.differences?.length
          ? greenchoice.differences.join("; ")
          : "Matches the official contract terms.",
      )}">
        <span>Greenchoice basis</span>
        <strong>${escapeHtml(greenchoice.basis)}</strong>
      </div>`
    : "";

  getElement("assumption-strip").innerHTML =
    basisChip +
    items
      .map(
        ([label, value]) => `
      <div class="assumption-chip">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `,
      )
      .join("");
}
