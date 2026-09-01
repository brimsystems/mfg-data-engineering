# Realism checks

Generated 2026-09-28 14:59. Rerun with `python -m data_source.generate.checks` after any generator change.

## Volume

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs over 36 months | 10,500-12,500 | 12,218 | pass |
| Revenue mix repeat / new / own (65/30/5, within 3 points) | 62-68 / 27-33 / 2-8 | 67% / 28% / 5% | pass |
| Quote lines in the window | 9,000-12,000 | 9,315 | pass |
| Win rate on new work | 35-50% | 48% | pass |
| Labor transactions | 220,000-300,000 | 261,274 | pass |
| Quantity breaks per quote line | 3-4 | 4.0 | pass |
| Jobs table rollups equal the sum of the job's transactions (material, labor, outside) | within $0.05 | max gap $0.01, $0.00, $0.00 | pass |
| Machine monitoring intervals | 1.5-2.5M | 1.59M | pass |
| Material transactions | 45,000-65,000 | 51,369 | pass |
| Outside processing lines | 8,000-12,000 | 11,474 | pass |
| Top customer share of 2025 revenue | 18-24% | 20% | pass |
| Top 10 customers share of 2025 revenue | 60-70% | 65% | pass |
| Lot size median | 40-80 pieces | 65 | pass |
| Share of jobs under 25 pieces | 20-30% | 21% | pass |
| Cost structure material / labor and burden / outside | 25-35 / 50-60 / 8-15 | 31% / 59% / 10% | pass |
| 2025 revenue | about $55M | $55.0M | pass |

## Outcome

| Check | Expected | Found | Result |
|---|---|---|---|
| Shop-level gross margin 2025 on the P&L (payroll, purchases, invoices) | 22-25% | 22.3% | pass |
| Shop-level gross margin 2025 from cleaned job cost at the pools | 22-25% | 22.9% | pass |
| Share of 2025 jobs above target margin | 45-58% | 45% | pass |
| Share of 2025 jobs below target | 35-45% | 40% | pass |
| Share of 2025 jobs with negative contribution | 6-12% | 7% | pass |
| P1: repeat parts below current cost plus target | 12-18% of parts | 16.8% | pass |
| P1: repeat revenue on parts below current cost plus target | 8-12% (13% tolerated) | 11.6% | pass |
| P1: gap to target price, median | 4-8% | 3.5% | CHECK |
| P1: gap to target price, 90th percentile | about 12% (10-16%) | 13.7% | pass |
| P1: repeat parts below cost outright | under 2% (brief 1-2%, which conflicts with a 12% p90) | 0.2% | pass |
| P1+P7: exposure, repeat parts and own products, share of 2025 revenue | 1.0-1.5% | 1.08% | pass |
| P1: repricing decisions, captured / held / exited share of exposure | 40-60 / 25-40 / 5-10% | 52% / 41% / 7% | CHECK |
| P7: own products, list vs current cost plus target, median | -5 to -15% | -11.4% | pass |
| P7: own products below cost at list | 1-2 of 14 | 1 of 14 | pass |
| Estimate accuracy on labor hours 2025 before cleanup, median | 1.10-1.25 | 1.14 | pass |
| Estimate accuracy 2025 before cleanup, IQR | 0.85-1.60 | 0.94-1.46 | pass |
| Estimate accuracy on engagement-period jobs, median | 1.02-1.10 | 1.03 | pass |
| Estimate accuracy on engagement-period jobs, IQR | 0.90-1.30 | 0.96-1.16 | CHECK |
| Setup on new parts and parts not run in a year vs estimate (mill-turn, 5-axis) | 1.4-1.8x | 1.60x (parts run within the year: 1.01x) | pass |
| Setup vs estimate by lot size, mill-turn and 5-axis (no rule on lot size) | reported | under 25 pieces 1.03x, 25+ 1.05x; infrequent share 16% vs 17% | pass |
| Clocked vs machine hours on monitored cells, 2025 (mean of job ratio) | clocked higher by 15-30% | +60% | CHECK |
| Standard deviation of the clocked/machine ratio | 0.25-0.40 | 0.51 | CHECK |
| Customer margin range, top 15 customers | 6% to 36% on price | 17% to 32% | CHECK |
| Top customer margin in the bottom third of the top 15 | bottom third | percentile 47% | CHECK |

## Defects

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs with an estimate attached before restructuring | 0% | 0% | pass |
| Outside processing lines tied to a job before restructuring | 15-30% | 21% | pass |
| Clock records spanning a break, shift or overnight (T1) | 6-10% | 6.6% | pass |
| Hours contained in those records | 25-40% of clocked hours | 23% | CHECK |
| Time charged to the wrong job (T3) | 1.5-3% | 2.4% | pass |
| Multi-machine tending recorded as one job (T4), CNC records | 10-15% | 10.4% | pass |
| Indirect time charged to jobs (T5) | 5-8% of hours | 5.4% | pass |
| Rework recorded as run time (T6) | 60-75% of rework events | 67% | pass |
| Scrap events recorded (T7) | 55-70% | 65% | pass |
| Recorded scrap events with a reason code | about 50% | 52% | pass |
| Material issued to the wrong job or not issued (T8) | 4-7% | 5.5% | pass |
| Repeat parts with standards more than 15% off the measured cycle (M2) | 55-70% | 62% | pass |
| Generic or reused program numbers (M7) | 8-12% | 10% | pass |
| Own products below current cost at list price (M8, generator view) | 1-3 of 14 | 3 of 14 | pass |
| Labor posting never turned on at three secondary cells (T10): records before the rollout | 0 | 0 records; 52% of jobs pass through them | pass |

## Post

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs released with an estimate attached after the config date | 100% | 100% | pass |
| Outside processing tied to a job, new POs | 97%+ | 100.0% | pass |
| Scan coverage at secondary operations, week 2 | 65-75% | 68% | pass |
| Scan coverage at secondary operations, week 12 | 85-92% | 87% | pass |
| Cost dollars measured (not estimated) on jobs run in weeks 8-12 | 85-92% | 89% | pass |
| Repeat parts with measured standards (every part that ran on a monitored cell) | 70-100% | 100% | pass |
| Estimator disputes of measured values | 5-10% | 8% | pass |
| Repricing decisions on every part reviewed: repriced / held / exited, none pending | 45-70 / 20-45 / 3-12% / 0 | 72% / 19% / 9% / 0% | CHECK |

## Story

| Check | Expected | Found | Result |
|---|---|---|---|
| Cleaned job-cost margin within 1.5 points of the P&L figure | <= 1.5 pts | 0.1 pts | pass |
| Repeat parts below cost plus target on the true cycle (generator view) | 12-22% | 16% | pass |
| P2: the setup overrun follows how recently the part ran, not the lot size | infrequent-part ratio > 1.3 x familiar-part ratio | 1.59x | pass |
| P8: gap widest on the multi-machine cells (Swiss, EDM) | SWS/EDM ratio > mills ratio | SWS 2.73, EDM 2.15, VMC 1.30 | pass |
| P3: change-order customer margin on price | 8-11% | 17% | CHECK |
| P4: manual-heavy families rank below 5-axis-heavy under the blended rate and above under pools | reversal | Fixtures  18%->24%; Weldments 17%->23%; Aerospace 27%->19%; Turbine c 25%->21% | pass |
| P1: the erosion cohort sits below cost plus target far more often than other repeat parts | cohort at least 1.4x others | cohort 38%, others 17% | pass |
| Coverage rises in step with the rollout | monotone-ish | w2:68% w3:75% w4:72% w5:76% w6:74% w7:79% w8:82% w9:82% w10:81% w11:85% w12:87% | pass |
