import { getElement } from "../dom.js";
import { chartLayout, getPlotly, showChartEmpty } from "../charts/layout.js";
import { CHART_COLORS } from "../charts/chartTheme.js";
import { renderDownloads } from "./downloads.js";
import { renderTable, renderTableError } from "./tables.js";


const MONTHLY_COMPONENTS = [
  {
    key: "Actual output SCADA MWh",
    name: "Delivered energy",
    color: CHART_COLORS.blue,
  },
  {
    key: "Underperformance loss MWh",
    name: "Underperformance loss",
    color: CHART_COLORS.orange,
  },
  {
    key: "Curtailment loss MWh",
    name: "Curtailment / EMS loss",
    color: CHART_COLORS.purple,
  },
  {
    key: "Technical loss MWh",
    name: "Technical loss",
    color: CHART_COLORS.red,
  },
];

const SCADA_METRIC_COLUMN = "SCADA metric (% of wind potential)";

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function scadaMonthlyRowClass(row) {
  const metric = row?.[SCADA_METRIC_COLUMN];
  if (metric === "Wind-potential energy") return "scada-energy-start";
  if (metric === "Technical loss") return "scada-loss-start";
  return "";
}

function scadaMonthlyCellContent(row, column) {
  const value = row?.[column];
  if (
    value &&
    typeof value === "object" &&
    Object.hasOwn(value, "primary")
  ) {
    return {
      type: "stacked",
      primaryText: value.primary,
      secondaryText: value.secondary,
    };
  }
  return { type: "text", text: value };
}

function makeScadaPeriodRows(rows) {
  return (rows || []).map((row) => {
    const value = row?.["Selected period"];
    const isStructured =
      value &&
      typeof value === "object" &&
      Object.hasOwn(value, "primary");
    return {
      [SCADA_METRIC_COLUMN]: row?.[SCADA_METRIC_COLUMN],
      "Selected period": isStructured ? value.primary : value,
      "% of wind potential": isStructured ? value.secondary || "" : "",
    };
  });
}

function renderScadaMonthlyChart(payload) {
  const target = getElement("scada-monthly-chart");
  const rows = payload?.chart_rows || [];
  if (!rows.length) {
    showChartEmpty(target, "No monthly SCADA data available.");
    return;
  }

  const x = rows.map((row) => row.Month);
  const cumulative = rows.map(() => 0);
  const traces = MONTHLY_COMPONENTS.map((component) => {
    const y = rows.map((row) => numberOrZero(row[component.key]));
    const base = [...cumulative];
    y.forEach((value, index) => {
      cumulative[index] += value;
    });
    return {
      type: "bar",
      name: component.name,
      x,
      y,
      base,
      marker: { color: component.color },
      hovertemplate: `${component.name}: %{y:,.1f} MWh<extra></extra>`,
    };
  });

  const potential = rows.map((row) => numberOrZero(row["Wind potential MWh"]));
  const adjustment = rows.map((row) =>
    numberOrZero(row["Reconciliation adjustment MWh"]),
  );
  traces.push({
    type: "bar",
    name: "Reconciliation adjustment",
    x,
    y: adjustment,
    base: [...cumulative],
    customdata: adjustment,
    marker: {
      color: "rgba(100, 116, 139, 0.30)",
      line: { color: CHART_COLORS.slate, width: 1 },
      pattern: { shape: "/" },
    },
    hovertemplate:
      "Reconciliation adjustment: %{customdata:,.1f} MWh<extra></extra>",
  });
  traces.push({
    type: "scatter",
    mode: "markers",
    name: "Wind-potential energy",
    x,
    y: potential,
    marker: {
      color: "#002B5C",
      line: { color: "#FFFFFF", width: 1 },
      size: 9,
      symbol: "diamond",
    },
    hovertemplate: "Wind-potential energy: %{y:,.1f} MWh<extra></extra>",
  });
  traces.push({
    type: "scatter",
    mode: "text",
    name: "Valid coverage",
    showlegend: false,
    cliponaxis: false,
    x,
    y: rows.map((row, index) =>
      Math.max(cumulative[index], potential[index]) * 1.035,
    ),
    text: rows.map((row) => `${numberOrZero(row["Valid SCADA coverage %"]).toFixed(1)}% valid`),
    textfont: { color: CHART_COLORS.slate, size: 11 },
    hoverinfo: "skip",
  });

  const layout = chartLayout(
    "Monthly SCADA energy balance",
    "MWh on valid SCADA intervals",
  );
  layout.barmode = "overlay";
  layout.xaxis.type = "category";
  layout.legend.traceorder = "normal";
  layout.margin.t = 82;

  const plotly = getPlotly(target);
  if (!plotly) return;
  plotly.react(target, traces, layout);
}

export function renderScadaMonthly(payload) {
  if (!payload?.available) {
    renderScadaMonthlyError("No SCADA analysis is available in this dataset.");
    return;
  }
  renderTable("scada-monthly-table", payload?.table || [], {
    tableClass: "monthly-kpi-table scada-monthly-table",
    rowClassName: scadaMonthlyRowClass,
    renderCellContent: scadaMonthlyCellContent,
  });
  renderDownloads("scada-monthly-downloads", [
    { label: "SCADA overview", path: "/api/downloads/scada-monthly-overview" },
    { label: "Numeric export", path: "/api/downloads/scada-monthly-numeric" },
  ]);
  renderScadaMonthlyChart(payload);
}

export function renderScadaMonthlyError(message) {
  renderTableError("scada-monthly-table", message);
  renderDownloads("scada-monthly-downloads", []);
  showChartEmpty("scada-monthly-chart", message);
}

function envelopeSeries(payload, key) {
  return (payload?.series || []).find((series) => series.key === key);
}

function lossBandTrace(upper, lower, fillcolor) {
  const polygonX = [];
  const polygonY = [];
  let segmentX = [];
  let segmentUpper = [];
  let segmentLower = [];

  function finishSegment() {
    if (segmentX.length >= 2) {
      polygonX.push(...segmentX, ...[...segmentX].reverse(), null);
      polygonY.push(...segmentUpper, ...[...segmentLower].reverse(), null);
    }
    segmentX = [];
    segmentUpper = [];
    segmentLower = [];
  }

  upper.x.forEach((timestamp, index) => {
    const upperRaw = upper.y[index];
    const lowerRaw = lower.y[index];
    const upperValue = Number(upperRaw);
    const lowerValue = Number(lowerRaw);
    const isPhysicalBand =
      timestamp &&
      upperRaw !== null &&
      upperRaw !== undefined &&
      lowerRaw !== null &&
      lowerRaw !== undefined &&
      Number.isFinite(upperValue) &&
      Number.isFinite(lowerValue) &&
      upperValue >= lowerValue;
    if (!isPhysicalBand) {
      finishSegment();
      return;
    }
    segmentX.push(timestamp);
    segmentUpper.push(upperValue);
    segmentLower.push(lowerValue);
  });
  finishSegment();

  if (!polygonX.length) return null;
  return {
    type: "scatter",
    mode: "lines",
    x: polygonX,
    y: polygonY,
    fill: "toself",
    fillcolor,
    line: { width: 0 },
    hoverinfo: "skip",
    showlegend: false,
  };
}

export function renderScadaEnvelope(payload) {
  const target = getElement("scada-envelope-chart");
  const note = getElement("scada-coverage-note");
  if (!payload?.available || !(payload.series || []).length) {
    note.textContent = "No SCADA analysis is available for the selected period.";
    renderTableError(
      "scada-period-table",
      "No selected-period SCADA data available.",
    );
    showChartEmpty(target, "No selected-period SCADA data available.");
    return;
  }

  renderTable("scada-period-table", makeScadaPeriodRows(payload?.table), {
    tableClass: "monthly-kpi-table scada-period-table",
    rowClassName: scadaMonthlyRowClass,
    columns: [
      { key: SCADA_METRIC_COLUMN, label: "SCADA metric" },
      { key: "Selected period", label: "Selected period" },
      { key: "% of wind potential", label: "% of wind potential" },
    ],
  });

  const coverage = Number(payload.coverage_pct);
  note.textContent = Number.isFinite(coverage)
    ? `${coverage.toFixed(1)}% valid SCADA coverage (${payload.valid_intervals.toLocaleString()} of ${payload.total_intervals.toLocaleString()} intervals). Frozen or missing SCADA periods are shown in grey.`
    : "SCADA coverage is unavailable.";

  const styles = {
    actual_output: {
      color: CHART_COLORS.green,
      dash: "solid",
    },
    effective_cap: {
      color: CHART_COLORS.greenLight,
      dash: "dash",
    },
    technically_available: {
      color: CHART_COLORS.blueGreen,
      dash: "solid",
    },
    supplier_setpoint: {
      color: CHART_COLORS.orange,
      dash: "solid",
      width: 1.5,
      opacity: 0.67,
    },
    wind_potential: {
      color: CHART_COLORS.blue,
      dash: "solid",
    },
  };
  const orderedSeries = [
    envelopeSeries(payload, "wind_potential"),
    envelopeSeries(payload, "technically_available"),
    envelopeSeries(payload, "effective_cap"),
    envelopeSeries(payload, "actual_output"),
  ];
  const displaySeries = [
    orderedSeries[0],
    orderedSeries[1],
    envelopeSeries(payload, "supplier_setpoint"),
    orderedSeries[2],
    orderedSeries[3],
  ].filter(Boolean);
  const traces = [
    lossBandTrace(orderedSeries[0], orderedSeries[1], CHART_COLORS.blueFill),
    lossBandTrace(
      orderedSeries[1],
      orderedSeries[2],
      CHART_COLORS.blueGreenFill,
    ),
    lossBandTrace(
      orderedSeries[2],
      orderedSeries[3],
      CHART_COLORS.greenLightFill,
    ),
  ].filter(Boolean);
  traces.push(...displaySeries.map((series) => {
    const key = series.key;
    const style = styles[key];
    return {
      type: "scatter",
      mode: "lines",
      name: series.label,
      x: series.x,
      y: series.y,
      connectgaps: false,
      opacity: style.opacity ?? 1,
      line: {
        color: style.color,
        dash: style.dash,
        width: style.width ?? (key === "actual_output" ? 2.7 : 2),
      },
      hovertemplate: `${series.label}: %{y:,.3f} MW<extra></extra>`,
    };
  }));

  const layout = chartLayout("SCADA production envelope", "Average power (MW)");
  layout.legend.traceorder = "normal";
  layout.shapes = (payload.invalid_ranges || []).map((range) => ({
    type: "rect",
    xref: "x",
    yref: "paper",
    x0: range.start,
    x1: range.end,
    y0: 0,
    y1: 1,
    fillcolor: "rgba(100, 116, 139, 0.16)",
    line: { width: 0 },
    layer: "below",
  }));

  const plotly = getPlotly(target);
  if (!plotly) return;
  plotly.react(target, traces, layout);
}

export function renderScadaEnvelopeError(message) {
  getElement("scada-coverage-note").textContent = message;
  renderTableError("scada-period-table", message);
  showChartEmpty("scada-envelope-chart", message);
}
