# Checks on the source extracts

12 of 12 checks pass. A check marked OUT is outside its range; it is reported here and nothing is adjusted.

| Check | What is measured | Range | Measured | Result |
|---|---|---|---|---|
| R1 | Unplanned failures in the scoring quarter (1 Jan to 31 Mar 2026) | 7 to 14 | 11 | pass |
| R2 | Unplanned failures a year, fleet | 35 to 55 | 45.0 | pass |
| R3 | Interval services in the scoring quarter | 40 to 55 | 45 | pass |
| R4 | Share of failures pre-empted by an interval service | 0.78 to 0.9 | 0.80 | pass |
| R5 | Unplanned downtime in the scoring quarter, CMMS hours | 110 to 230 | 177 | pass |
| R6 | Planned downtime a year (calendar PM plus interval services) against the calendar PM alone | 2.5 to 3.8 | 3.38x (415 + 988 hours) | pass |
| R7 | Unplanned failures a year per machine, MCH-007 and MCH-011 against the other ten | 2.0 to 3.5 | 3.5x (9.2 against 2.7) | pass |
| R8 | Unplanned-down hours in the state log against CMMS unplanned repair hours, whole window | 0.85 to 1.15 | 1.06 (2,470 against 2,338 hours) | pass |
| R9 | Fleet OEE over the window | 0.64 to 0.72 | 66.5% (availability 85.2%, performance 82.1%) | pass |
| R10 | OEE of the machines over 9 years (MCH-007, MCH-011, MCH-012) below the rest, points | at least 8.0 | 9.8 (59.0% against 68.9%) | pass |
| R11 | Alarm rate while a calendar PM is more than 14 days overdue, against current | 1.9 to 2.6 | 2.60x | pass |
| R12 | Physical sense (the four lines below) | all hold | 4 of 4 hold | pass |

## R12, line by line

| Condition | Holds | Detail |
|---|---|---|
| No repair opens in the same hour as a service on the machine, or while the service is under way | yes | 0 in the same hour, 0 during a service |
| Every interval service has a scheduled and a completed date | yes | 0 missing |
| repair_interval_days on every machine | yes | 0 missing |
| The clock restarts at the event that resolves each cycle, and a pre-empted failure has no repair | yes | 0 breaks in the sequence, 0 repairs on a pre-empted failure |

## Reported without a range

| Figure | Value |
|---|---|
| Unplanned-down and alarm share of state intervals, MCH-007 and MCH-011 against the rest | 4.2% against 2.2% (1.9x) |
| Unplanned-down share in the first 45 minutes of Shift A against the rest of the shift | 0.29% against 0.23% (1.3x) |
| Unplanned-down share in the first 45 minutes of Shift B against the rest of the shift | 0.27% against 0.25% (1.1x) |
| Calendar PM completed on time, fleet; the two aging assets | 72.4%; 67.3% |
| Median setup hours, the three flagged operators against the cohort | 0.58 against 0.43 (1.3x) |
| Calendar PMs logged with no scheduled date; jobs with no actual end | 6%; 7% |
| Maintenance records by type | INSPECTION 476, PLANNED_INTERVAL 596, PLANNED_PM 336, UNPLANNED_REPAIR 146 |
| Unplanned repair hours a year; interval service hours a year; calendar PM hours a year | 721; 988; 415 |
| Failures the wear-out process produced, by outcome | pre-empted by the service: 571; failed before the interval was reached: 103; failed after a service that did not address it: 25; failed before the service was carried out: 18 |
| Repair interval by machine, days | MCH-001 32, MCH-002 34, MCH-003 30, MCH-004 32, MCH-005 25, MCH-006 27, MCH-007 9, MCH-008 26, MCH-009 27, MCH-010 29, MCH-011 7, MCH-012 20 |

## By quarter: unplanned-down hours in the state log against CMMS unplanned repair hours

| Quarter | State log hours | CMMS repair hours | Ratio | Unplanned failures | Interval services |
|---|---|---|---|---|---|
| 2023Q1 | 199 | 276 | 0.72 | 15 | 42 |
| 2023Q2 | 202 | 165 | 1.23 | 12 | 43 |
| 2023Q3 | 173 | 162 | 1.07 | 11 | 48 |
| 2023Q4 | 178 | 165 | 1.08 | 10 | 48 |
| 2024Q1 | 188 | 119 | 1.59 | 7 | 50 |
| 2024Q2 | 180 | 253 | 0.71 | 16 | 38 |
| 2024Q3 | 209 | 182 | 1.15 | 9 | 47 |
| 2024Q4 | 204 | 185 | 1.10 | 12 | 48 |
| 2025Q1 | 176 | 74 | 2.38 | 8 | 45 |
| 2025Q2 | 164 | 250 | 0.66 | 13 | 47 |
| 2025Q3 | 192 | 194 | 0.99 | 11 | 50 |
| 2025Q4 | 202 | 136 | 1.48 | 11 | 45 |
| 2026Q1 | 203 | 177 | 1.15 | 11 | 45 |
