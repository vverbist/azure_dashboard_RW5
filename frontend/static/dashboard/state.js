const dashboardState = {
  dataset: "",
  timestamp_col: "timestamp_Ams",
  quick_period: "Last full month",
  start_date: "",
  end_date: "",
  resampling_rule: "Original",
  greenchoice_afslag_percentage: 17,
  greenchoice_afslag_floor: 10,
  gvo_value: 0,
  strike_price: 0,
  row_count: 10,
  dataBounds: null,
  fullBounds: null,
  monthPeriods: [],
};

export function getState() {
  return {
    ...dashboardState,
    monthPeriods: [...dashboardState.monthPeriods],
  };
}

export function getStateValue(key) {
  return dashboardState[key];
}

export function updateState(patch) {
  Object.assign(dashboardState, patch);
  return getState();
}

export function setStateValue(key, value) {
  dashboardState[key] = value;
  return value;
}
