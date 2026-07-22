# SCADA data dictionary

## Purpose and data layers

The SCADA workflow separates directly retrieved turbine measurements from
derived analysis and dashboard exports.

1. **Raw**: the 15-minute mean values returned by InfluxDB, retaining the
   original ENERCON signal names.
2. **Processed**: descriptive power and energy names, the effective power cap,
   and loss analysis.
3. **Combined**: processed SCADA fields joined to the existing market daily,
   monthly, and YTD datasets.

Local files under `data/` are an ignored working cache. Durable SCADA
partitions are uploaded to Azure Blob Storage:

```text
scada/raw/<year>/<YYYY-MM-DD>.parquet
scada/processed/<year>/<YYYY-MM-DD>.parquet
```

Raw data is saved and uploaded successfully before processed analysis is
published or merged into market data.

## Time convention

InfluxDB calculates 15-minute means using `aggregateWindow`. Each result is
labelled with the **start** of its interval. The query uses Europe/Amsterdam
local-day boundaries converted to UTC, so daylight-saving days contain 92,
96, or 100 intervals as appropriate.

`timestamp_utc` is timezone-aware UTC in Parquet. Combined market files join
on their timezone-naive UTC `timestamp` representation.

## Raw ENERCON signals

| Signal | Unit | Definition |
| --- | --- | --- |
| `P` | kW | Actual active power output. |
| `PavaVWind` | kW | Theoretical wind power available without faults or curtailment. |
| `AbstMaxP` | kW | Maximum technically available power after faults, maintenance, derating, and other technical limitations. |
| `PSet1` | kW | External power setpoint from the EMS or farm controller. |
| `Vwind` | m/s | Measured wind speed. It is contextual and is not converted to energy. |

The intended physical hierarchy is:

```text
PavaVWind
    | technical limitations
    v
AbstMaxP
    | EMS / dispatch limitation
    v
Pcap = min(AbstMaxP, PSet1)
    |
    v
P
```

If `PSet1` is absent for an interval, the turbine is designed to produce at
the technically available maximum. The raw `PSet1` remains missing, while the
processed calculation uses `AbstMaxP` as the effective setpoint. The boolean
`scada_setpoint_fallback_applied` records where this rule was used.

## Processed columns

| Processed column | Unit | Source or definition |
| --- | --- | --- |
| `scada_actual_power_kw` | kW | `P` |
| `scada_wind_potential_power_kw` | kW | `PavaVWind` |
| `scada_technically_available_power_kw` | kW | `AbstMaxP` |
| `scada_ems_setpoint_kw` | kW | `PSet1` |
| `scada_effective_power_cap_kw` | kW | `min(AbstMaxP, effective PSet1)` |
| `scada_wind_speed_mps` | m/s | `Vwind` |
| `scada_actual_energy_mwh` | MWh | Actual power converted to interval energy |
| `scada_wind_potential_energy_mwh` | MWh | Wind-potential power converted to interval energy |
| `scada_technically_available_energy_mwh` | MWh | Technically available power converted to interval energy |
| `scada_effective_cap_energy_mwh` | MWh | Effective power cap converted to interval energy |

For a 15-minute mean power value:

```text
energy_mwh = power_kw * 0.25 / 1000
```

## Loss calculations

All reported losses are non-negative. Raw measurements are never altered to
force the expected hierarchy.

```text
technical_loss_kw = max(PavaVWind - AbstMaxP, 0)
dispatch_loss_kw = max(AbstMaxP - Pcap, 0)
underperformance_loss_kw = max(Pcap - P, 0)
total_loss_kw = max(PavaVWind - P, 0)
```

The corresponding processed columns are:

- `scada_technical_loss_mwh`
- `scada_dispatch_loss_mwh`
- `scada_underperformance_loss_mwh`
- `scada_total_loss_mwh`

`scada_loss_balance_error_mwh` is total loss minus the three loss components.
It is a data-quality diagnostic: measurement averaging, control lag, or an
unexpected signal relationship can make the clipped components differ from
the directly calculated total.

The processed layer retains the magnitudes of signal-order deviations:

- `scada_available_above_potential_kw = max(AbstMaxP - PavaVWind, 0)`
- `scada_actual_above_cap_kw = max(P - Pcap, 0)`

`scada_available_potential_warning` is set when the first deviation exceeds
1 kW. This suppresses sub-kW averaging and floating-point noise.

`scada_actual_cap_warning` is set when actual power exceeds the effective cap
by more than 50 kW, or when an exceedance above 1 kW persists for at least two
consecutive 15-minute intervals. Deviations remain stored even when no warning
is raised.

At daily-summary level, loss reconciliation is considered a warning when the
absolute daily balance error exceeds the larger of 0.05 MWh or 5% of total
loss. These thresholds are diagnostic only and never change raw values or loss
calculations.

## Frozen-signal detection

The EMS setpoint is excluded from frozen-signal detection because a constant
setpoint is normal. A processed interval is marked `scada_frozen_signal` when
`P`, `PavaVWind`, `AbstMaxP`, and `Vwind` remain unchanged within 0.001 kW or
0.001 m/s for at least four consecutive 15-minute intervals (one hour).

Original raw values and the descriptive processed power/wind columns are
preserved for inspection. Energy, loss, and signal-order deviation fields are
set to `NaN` for frozen intervals so that stale numerical values cannot enter
KPIs. Warning booleans are false for frozen intervals; frozen coverage is
reported separately.

## Missing data

Missing raw measurements remain missing. They are not converted to zero.
The `PSet1` fallback described above is the only domain-specific substitution,
and it is explicitly flagged. A raw daily partition with no signal values at
all is considered unusable and is not processed into dashboard data.
