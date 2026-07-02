import { getState } from "./state.js";

export function params(extra = {}) {
  const state = getState();
  const query = {
    dataset: state.dataset,
    timestamp_col: state.timestamp_col,
    resampling_rule: state.resampling_rule,
    greenchoice_afslag_percentage: state.greenchoice_afslag_percentage,
    greenchoice_afslag_floor: state.greenchoice_afslag_floor,
    gvo_value: state.gvo_value,
    strike_price: state.strike_price,
    row_count: state.row_count,
    ...extra,
  };

  if (state.start_date) query.start_date = state.start_date;
  if (state.end_date) query.end_date = state.end_date;

  return query;
}

export function urlFor(path, extra = {}) {
  const url = new URL(path, window.location.origin);

  Object.entries(params(extra)).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });

  return url;
}

export async function apiGet(path, extra = {}, options = {}) {
  const response = await fetch(urlFor(path, extra), {
    signal: options.signal,
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;

    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {
      // Ignore non-JSON error bodies.
    }

    throw new Error(detail);
  }

  return response.json();
}

export async function loadDatasets(options = {}) {
  const response = await fetch("/api/datasets", {
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error("Could not load dataset list.");
  }

  return response.json();
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}
