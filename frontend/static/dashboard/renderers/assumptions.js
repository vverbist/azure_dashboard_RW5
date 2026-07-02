import { getElement } from "../dom.js";
import { escapeHtml, formatCell, timestampLabel } from "../formatters.js";

export function renderAssumptionStrip(state) {
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

  getElement("assumption-strip").innerHTML = items
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
