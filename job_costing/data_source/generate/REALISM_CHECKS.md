# Realism checks

Generated 2026-09-27 09:35. Rerun with `python -m data_source.generate.checks` after any generator change.

## Volume

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs over 36 months | 10,500-12,500 | 12,195 | pass |
| Revenue mix repeat / new / own (65/30/5, within 3 points) | 62-68 / 27-33 / 2-8 | 68% / 28% / 4% | pass |
| Quote lines in the window | 9,000-12,000 | 9,235 | pass |
| Win rate on new work | 35-50% | 47% | pass |
| Labor transactions | 220,000-300,000 | 258,215 | pass |
| Quantity breaks per quote line | 3-4 | 4.0 | pass |
| Jobs table rollups equal the sum of the job's transactions (material, labor, outside) | within $0.05 | max gap $0.01, $0.00, $0.00 | pass |
| Machine monitoring intervals | 1.5-2.5M | 1.57M | pass |
| Material transactions | 45,000-65,000 | 51,234 | pass |
| Outside processing lines | 8,000-12,000 | 11,369 | pass |
| Top customer share of 2025 revenue | 18-24% | 26% | CHECK |
| Top 10 customers share of 2025 revenue | 60-70% | 69% | pass |
| Lot size median | 40-80 pieces | 64 | pass |
| Share of jobs under 25 pieces | 20-30% | 22% | pass |
| Cost structure material / labor and burden / outside | 25-35 / 50-60 / 8-15 | 33% / 56% / 11% | pass |
| 2025 revenue | about $55M | $57.4M | pass |

## Outcome

| Check | Expected | Found | Result |
|---|---|---|---|
| Shop-level gross margin 2025 on the P&L (payroll, purchases, invoices) | 22-25% | 23.7% | pass |
| Shop-level gross margin 2025 from cleaned job cost at the pools | 22-25% | 23.9% | pass |
| Share of 2025 jobs above target margin | 40-50% | 53% | CHECK |
| Share of 2025 jobs below target | 35-45% | 37% | pass |
| Share of 2025 jobs with negative contribution | 6-10% | 9% | pass |
| Repeat parts priced below current cost plus target | 15-22% of parts | 27% | CHECK |
| Repeat revenue on parts below cost plus target | 10-16% | 24% | CHECK |
| Annual margin recoverable repricing the bottom quartile to target | 2.5-4% of revenue | 2.0% | CHECK |
| Estimate accuracy on labor hours 2025 before cleanup, median | 1.10-1.25 | 1.14 | pass |
| Estimate accuracy 2025 before cleanup, IQR | 0.85-1.60 | 0.94-1.50 | pass |
| Estimate accuracy on engagement-period jobs, median | 1.02-1.10 | 1.02 | pass |
| Estimate accuracy on engagement-period jobs, IQR | 0.90-1.30 | 0.95-1.13 | CHECK |
| Setup on lots under 25 pieces vs estimate (mill-turn, 5-axis) | 1.4-1.8x | 1.60x (lots of 25+: 1.01x) | pass |
| Clocked vs machine hours on monitored cells, 2025 (mean of job ratio) | clocked higher by 15-30% | +61% | CHECK |
| Standard deviation of the clocked/machine ratio | 0.25-0.40 | 0.53 | CHECK |
| Customer margin range, top 15 customers | 6% to 36% on price | 17% to 30% | CHECK |
| Top customer margin in the bottom third of the top 15 | bottom third | percentile 33% | pass |

## Defects

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs with an estimate attached before restructuring | 0% | 0% | pass |
| Outside processing lines tied to a job before restructuring | 15-30% | 21% | pass |
| Clock records spanning a break, shift or overnight (T1) | 6-10% | 6.5% | pass |
| Hours contained in those records | 25-40% of clocked hours | 22% | CHECK |
| Time charged to the wrong job (T3) | 1.5-3% | 2.4% | pass |
| Multi-machine tending recorded as one job (T4), CNC records | 10-15% | 10.2% | pass |
| Indirect time charged to jobs (T5) | 5-8% of hours | 5.3% | pass |
| Rework recorded as run time (T6) | 60-75% of rework events | 69% | pass |
| Scrap events recorded (T7) | 55-70% | 64% | pass |
| Recorded scrap events with a reason code | about 50% | 52% | pass |
| Material issued to the wrong job or not issued (T8) | 4-7% | 5.5% | pass |
| Repeat parts with standards more than 15% off the measured cycle (M2) | 55-70% | 64% | pass |
| Generic or reused program numbers (M7) | 8-12% | 10% | pass |
| Own products below current cost at list price (M8) | 3 of 14 | 7 of 14 | CHECK |
| Labor posting never turned on at three secondary cells (T10): records before the rollout | 0 | 0 records; 51% of jobs pass through them | pass |

## Post

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs released with an estimate attached after the config date | 100% | 100% | pass |
| Outside processing tied to a job, new POs | 97%+ | 98.6% | pass |
| Scan coverage at secondary operations, week 2 | 65-75% | 73% | pass |
| Scan coverage at secondary operations, week 12 | 85-92% | 91% | pass |
| Cost dollars measured (not estimated) on jobs run in weeks 8-12 | 85-92% | 88% | pass |
| Repeat parts with measured standards | 70-85% | 78% | pass |
| Estimator disputes of measured values | 5-10% | 9% | pass |
| Repricing decisions on the bottom quartile: repriced / held / exited | 55-70 / 15-25 / 5-10% | 61% / 20% / 10% | pass |

## Story

| Check | Expected | Found | Result |
|---|---|---|---|
| Cleaned job-cost margin within 1.5 points of the P&L figure | <= 1.5 pts | 0.1 pts | pass |
| Repeat parts below cost plus target on the true cycle (generator view) | 15-22% | 26% | CHECK |
| P2: setup ratio rises sharply below the lot-size threshold, not gradually | small-lot ratio > 1.3 x large-lot ratio | 1.59x | pass |
| P8: gap widest on the multi-machine cells (Swiss, EDM) | SWS/EDM ratio > mills ratio | SWS 2.88, EDM 2.19, VMC 1.33 | pass |
| P3: change-order customer margin on price | 8-11% | 17% | CHECK |
| P4: manual-heavy families rank below 5-axis-heavy under the blended rate and above under pools | reversal | Fixtures  19%->27%; Weldments 20%->29%; Aerospace 28%->15%; Turbine c 24%->16% | pass |
| P1: the erosion cohort sits below cost plus target far more often than other repeat parts | cohort >> others | cohort 54%, others 21% | pass |
| Coverage rises in step with the rollout | monotone-ish | w2:73% w3:75% w4:77% w5:81% w6:78% w7:79% w8:78% w9:82% w10:83% w11:83% w12:91% | pass |
