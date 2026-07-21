import { getElement } from "../dom.js";
import { timestampToSelectedLocalString } from "../formatters.js";
import { applyInspectionRange, chartLayout, getPlotly, showChartEmpty } from "./layout.js";
import { CHART_COLORS } from "./chartTheme.js";
import { SERIES_LABELS } from "./seriesLabels.js";

export function renderVolumesChart(payload, targetId, options = {}) {
  const target = getElement(targetId);
  const series = payload?.series || [];
  const lineA = series.find(
    (item) => item.label === SERIES_LABELS.volumes.delivered,
  );
  const lineB = series.find(
    (item) => item.label === SERIES_LABELS.volumes.nominated,
  );

  if (!lineA || !lineB) {
    showChartEmpty(
      target,
      "Required volume series are not available for this selection.",
    );
    console.warn("Missing volume lines", {
      wanted: [
        SERIES_LABELS.volumes.delivered,
        SERIES_LABELS.volumes.nominated,
      ],
      available: series.map((item) => item.label),
    });
    return;
  }

  const pointsA = toNumericPoints(lineA);
  const pointsB = toNumericPoints(lineB);

  if (pointsA.length < 2 || pointsB.length < 2) {
    showChartEmpty(
      target,
      "Not enough volume points to draw the comparison chart.",
    );
    return;
  }

  const aligned = buildAlignedComparisonPoints(pointsA, pointsB);
  const traces = [];
  const lineAAbove = "Delivered above nominated";
  const lineBAbove = "Nominated above delivered";

  for (let index = 0; index < aligned.length - 1; index += 1) {
    const left = aligned[index];
    const right = aligned[index + 1];

    if (!left || !right) continue;

    const leftDiff = left.a - left.b;
    const rightDiff = right.a - right.b;

    if (leftDiff === 0 && rightDiff === 0) continue;

    if (leftDiff >= 0 && rightDiff >= 0) {
      traces.push(
        makeDifferencePolygonTrace({
          left,
          right,
          topKey: "a",
          bottomKey: "b",
          fillcolor: CHART_COLORS.greenFill,
          name: lineAAbove,
          showlegend: !traces.some((trace) => trace.name === lineAAbove),
        }),
      );
    } else if (leftDiff <= 0 && rightDiff <= 0) {
      traces.push(
        makeDifferencePolygonTrace({
          left,
          right,
          topKey: "b",
          bottomKey: "a",
          fillcolor: CHART_COLORS.redFill,
          name: lineBAbove,
          showlegend: !traces.some((trace) => trace.name === lineBAbove),
        }),
      );
    } else {
      const crossing = interpolateCrossing(
        left,
        right,
        options.timestampColumn,
      );

      if (!crossing) continue;

      if (leftDiff > 0) {
        traces.push(
          makeDifferencePolygonTrace({
            left,
            right: crossing,
            topKey: "a",
            bottomKey: "b",
            fillcolor: CHART_COLORS.greenFill,
            name: lineAAbove,
            showlegend: !traces.some((trace) => trace.name === lineAAbove),
          }),
        );
        traces.push(
          makeDifferencePolygonTrace({
            left: crossing,
            right,
            topKey: "b",
            bottomKey: "a",
            fillcolor: CHART_COLORS.redFill,
            name: lineBAbove,
            showlegend: !traces.some((trace) => trace.name === lineBAbove),
          }),
        );
      } else {
        traces.push(
          makeDifferencePolygonTrace({
            left,
            right: crossing,
            topKey: "b",
            bottomKey: "a",
            fillcolor: CHART_COLORS.redFill,
            name: lineBAbove,
            showlegend: !traces.some((trace) => trace.name === lineBAbove),
          }),
        );
        traces.push(
          makeDifferencePolygonTrace({
            left: crossing,
            right,
            topKey: "a",
            bottomKey: "b",
            fillcolor: CHART_COLORS.greenFill,
            name: lineAAbove,
            showlegend: !traces.some((trace) => trace.name === lineAAbove),
          }),
        );
      }
    }
  }

  const deliveredAboveTraces = traces.filter(
    (trace) => trace.name === lineAAbove,
  );
  const nominatedAboveTraces = traces.filter(
    (trace) => trace.name === lineBAbove,
  );
  traces.length = 0;
  traces.push(...nominatedAboveTraces, ...deliveredAboveTraces);

  traces.push(
    {
      type: "scatter",
      mode: "lines",
      name: lineB.label,
      x: lineB.x,
      y: lineB.y,
      line: { width: 2, color: CHART_COLORS.blueLight },
    },
    {
      type: "scatter",
      mode: "lines",
      name: lineA.label,
      x: lineA.x,
      y: lineA.y,
      line: { width: 2.5, color: CHART_COLORS.blue },
    },
  );

  const layout = applyInspectionRange(
    chartLayout("Volumes", lineA.unit || lineB.unit || "MWh"),
    options.inspectionWindow,
  );
  layout.yaxis.rangemode = "tozero";
  layout.legend.traceorder = "reversed";

  const plotly = getPlotly(target);
  if (!plotly) return;

  plotly.react(target, traces, layout);
}

function toNumericPoints(series) {
  return (series.x || [])
    .map((xValue, index) => {
      const timestamp = new Date(xValue).getTime();
      const yValue = Number(series.y?.[index]);

      if (!Number.isFinite(timestamp) || !Number.isFinite(yValue)) {
        return null;
      }

      return {
        x: xValue,
        t: timestamp,
        y: yValue,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.t - b.t);
}

function interpolateY(points, timestamp) {
  if (timestamp < points[0].t || timestamp > points[points.length - 1].t) {
    return null;
  }

  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index];
    const right = points[index + 1];

    if (timestamp === left.t) return left.y;
    if (timestamp === right.t) return right.y;

    if (timestamp > left.t && timestamp < right.t) {
      const ratio = (timestamp - left.t) / (right.t - left.t);
      return left.y + ratio * (right.y - left.y);
    }
  }

  return null;
}

function buildAlignedComparisonPoints(pointsA, pointsB) {
  const timestampToOriginalX = new Map();

  [...pointsA, ...pointsB].forEach((point) => {
    if (!timestampToOriginalX.has(point.t)) {
      timestampToOriginalX.set(point.t, point.x);
    }
  });

  const timestamps = [...timestampToOriginalX.keys()].sort((a, b) => a - b);

  return timestamps
    .map((timestamp) => {
      const a = interpolateY(pointsA, timestamp);
      const b = interpolateY(pointsB, timestamp);

      if (!Number.isFinite(a) || !Number.isFinite(b)) {
        return null;
      }

      return {
        t: timestamp,
        x: timestampToOriginalX.get(timestamp),
        a,
        b,
      };
    })
    .filter(Boolean);
}

function interpolateCrossing(left, right, timestampColumn) {
  const leftDiff = left.a - left.b;
  const rightDiff = right.a - right.b;
  const denominator = leftDiff - rightDiff;

  if (denominator === 0) return null;

  const ratio = leftDiff / denominator;
  const timestamp = left.t + ratio * (right.t - left.t);
  const a = left.a + ratio * (right.a - left.a);

  return {
    t: timestamp,
    x: timestampToSelectedLocalString(timestamp, timestampColumn),
    a,
    b: a,
  };
}

function makeDifferencePolygonTrace({
  left,
  right,
  topKey,
  bottomKey,
  fillcolor,
  name,
  showlegend,
}) {
  return {
    type: "scatter",
    mode: "lines",
    name,
    x: [left.x, right.x, right.x, left.x],
    y: [left[topKey], right[topKey], right[bottomKey], left[bottomKey]],
    fill: "toself",
    fillcolor,
    line: { width: 0 },
    hoverinfo: "skip",
    showlegend,
  };
}
