# Realism checks

Rerun with `python -m data_source.generate.checks` after the dbt build and the mart export.

## Volume

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs over 36 months | 10,500-12,500 | 12,181 | pass |
| Revenue mix repeat / new / own (65/30/5, within 3 points) | 62-68 / 27-33 / 2-8 | 67% / 28% / 5% | pass |
| Quote lines in the window | 9,000-12,000 | 9,315 | pass |
| Win rate on new work | 35-50% | 48% | pass |
| Labor transactions | 220,000-300,000 | 256,208 | pass |
| Quantity breaks per quote line | 3-4 | 4.0 | pass |
| Jobs table rollups equal the sum of the job's transactions (material, labor, outside) | within $0.05 | max gap $0.01, $0.00, $0.00 | pass |
| Machine monitoring intervals | 1.5-2.5M | 1.60M | pass |
| Material transactions | 45,000-65,000 | 51,224 | pass |
| Outside processing lines | 8,000-12,000 | 11,468 | pass |
| Top customer share of 2025 revenue | 18-24% | 21% | pass |
| Top 10 customers share of 2025 revenue | 60-70% | 64% | pass |
| Lot size median | 40-80 pieces | 64 | pass |
| Share of jobs under 25 pieces | 20-30% | 21% | pass |
| Cost structure material / labor and burden / outside | 25-35 / 50-60 / 8-15 | 31% / 58% / 10% | pass |
| 2025 revenue | about $55M | $56.1M | pass |

## Outcome

| Check | Expected | Found | Result |
|---|---|---|---|
| Shop-level gross margin 2025 on the P&L (payroll, purchases, invoices) | 22-25% | 23.9% | pass |
| Shop-level gross margin 2025 from cleaned job cost at the pools | 22-25% | 24.4% | pass |
| Share of 2025 jobs above target margin | 45-58% | 45% | pass |
| Share of 2025 jobs below target | 35-45% | 40% | pass |
| Share of 2025 jobs with negative contribution | 5-12% | 6.5% | pass |
| Repeat parts below current cost plus target | 12-18% of parts | 16.4% | pass |
| Repeat revenue on parts below current cost plus target | 8-16% | 11.3% | pass |
| Repeat parts below target: gap to target price, median | 4-8% | 5.1% | pass |
| Repeat parts below target: gap to target price, 90th percentile | 10-18% | 17.1% | pass |
| Repeat parts below cost outright | under 2% | 0.2% | pass |
| Pricing exposure, repeat parts and own products, share of 2025 revenue | 1.0-1.5% | 1.05% | pass |
| Repricing decisions, captured / held / exited share of exposure | 45-65 / 25-40 / 5-18% | 49% / 36% / 16% | pass |
| Own products, list vs current cost plus target, median | -5 to -15% | -11.2% | pass |
| Own products below cost at list | 1-2 of 14 | 1 of 14 | pass |
| Estimate accuracy on labor hours 2025 before cleanup, median | 1.10-1.25 | 1.10 | pass |
| Estimate accuracy 2025 before cleanup, IQR | lower 0.88-0.96, upper 1.35-1.50 | 0.91-1.40 | pass |
| Estimate accuracy on engagement-period jobs, median | 1.02-1.10 | 1.04 | pass |
| Estimate accuracy on engagement-period jobs, IQR | lower 0.93-0.99, upper 1.08-1.18 | 0.96-1.13 | pass |
| Setup on new parts and parts not run in a year vs estimate (mill-turn, 5-axis) | 1.4-1.8x | 1.60x (parts run within the year: 1.01x) | pass |
| Setup vs estimate by lot size, mill-turn and 5-axis (no rule on lot size) | reported | under 25 pieces 1.04x, 25+ 1.04x; infrequent share 15% vs 15% | pass |
| Clocked vs machine hours on monitored cells, 2025 (mean of job ratio; median beside it) | clocked higher by 45-70% | +60% (median +44%) | pass |
| Standard deviation of the clocked/machine ratio | 0.40-0.60 | 0.53 | pass |
| Top customer margin in the bottom third of the top 15 | bottom third | percentile 20% | pass |

## Record errors before the engagement

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs with an estimate attached before restructuring | 0% | 0% | pass |
| Outside processing lines tied to a job before restructuring | 15-30% | 22% | pass |
| Clock records spanning a break, shift or overnight | 6-10% | 6.5% | pass |
| Hours contained in those records | 20-40% of clocked hours | 22% | pass |
| Time charged to the wrong job | 1.5-3% | 2.4% | pass |
| Multi-machine tending recorded as one job, CNC records | 10-15% | 10.3% | pass |
| Indirect time charged to jobs | 5-8% of hours | 5.4% | pass |
| Rework recorded as run time | 60-75% of rework events | 68% | pass |
| Scrap events recorded | 55-70% | 65% | pass |
| Recorded scrap events with a reason code | about 50% | 50% | pass |
| Material issued to the wrong job or not issued | 4-7% | 5.7% | pass |
| Repeat parts with standards more than 15% off the measured cycle | 55-70% | 62% | pass |
| Generic or reused program numbers | 8-12% | 10% | pass |
| Own products below current cost at list price (from the working tables) | 1-3 of 14 | 3 of 14 | pass |
| Labor posting never turned on at three secondary cells: records before the rollout | 0 | 0 records; 53% of jobs pass through them | pass |

## After the engagement

| Check | Expected | Found | Result |
|---|---|---|---|
| Jobs released with an estimate attached after the config date | 100% | 100% | pass |
| Outside processing tied to a job, new POs | 97%+ | 100.0% | pass |
| Scan coverage at secondary operations, week 2 | 65-75% | 72% | pass |
| Scan coverage at secondary operations, week 12 | 82-92% | 86% | pass |
| Cost dollars measured (not estimated) on jobs run in weeks 8-12 | 85-92% | 89% | pass |
| Repeat parts with measured standards (every part that ran on a monitored cell) | 70-100% | 100% | pass |
| Estimator disputes of measured values | 5-10% | 9% | pass |
| Repricing decisions on every part reviewed: repriced / held / exited, none pending | 60-75 / 12-25 / 8-20% / 0 | 65% / 17% / 18% / 0% | pass |

## Cross-checks

| Check | Expected | Found | Result |
|---|---|---|---|
| Cleaned job-cost margin within 1.5 points of the P&L figure | <= 1.5 pts | 0.3 pts | pass |
| Repeat parts below cost plus target on the current cycle (from the working tables) | 12-22% | 19% | pass |
| The setup overrun follows how recently the part ran, not the lot size | infrequent-part ratio > 1.3 x familiar-part ratio | 1.59x | pass |
| Clocked against machine hours: gap widest on the multi-machine cells (Swiss, EDM) | SWS/EDM ratio > mills ratio | SWS 2.87, EDM 2.27, VMC 1.31 | pass |
| The erosion cohort sits below cost plus target far more often than other repeat parts | cohort at least 1.4x others | cohort 41%, others 18% | pass |
| Coverage rises in step with the rollout | monotone-ish | w2:72% w3:71% w4:75% w5:73% w6:79% w7:80% w8:80% w9:80% w10:81% w11:83% w12:86% | pass |

## Actual against estimate

| Check | Expected | Found | Result |
|---|---|---|---|
| R1 run-hours ratio, median and interquartile | median 1.06-1.12; IQR lower 0.94-1.00, upper 1.22-1.32 | median 1.081; IQR 0.963 to 1.252 | pass |
| R2 run-hours ratio on the hard alloys over the other materials in the same two families (medians); the excess as a share of the run-hours overrun before offsets | 1.03-1.10x; 5-10% | 1.065x (1.113 against 1.046); 8.1% ($139K of $1,702K) | pass |
| R3 outside-processing ratio, median | 1.15-1.25 | 1.230 | pass |
| R4 outside-processing ratio on lots under 25 pieces over lots above 100 | 1.25-2.0x | 1.31x (1.544 against 1.182) | pass |
| R5 plated jobs, invoice over estimate: median against all services, and the rise from the first quarter to the last | within 0.05 of the all-services median; rise within one year of drift (under 6.5%) | 1.252 against 1.230; quarters 1.312, 1.295, 1.182, 1.228 (-6.4%) | pass |
| R6 revision-heavy account, labor hours over estimate (summed setup and run hours), against the rest of the book; the excess in dollars | 1.08-1.15x against 0.98-1.04x; $150K-260K | 1.086x against 0.999x; $207K | pass |
| R7 revision work at other customers: share of jobs; with a change-order line before the week 9 decision; after it | 2.5-3.5%; 45-55%; 100% | 3.19% (331 jobs); 54% of 314; 100% of 17 | pass |
| R8 interrupted operations over the occasions; two setup intervals in the feed. An occasion: a rush job's operation arrives at a monitored cell and would wait, and an operation of another job is in its run there, not stopped before, where the rush operation fits before the machine's next commitment and the remainder can resume within the limit in working hours; the rush operation is no longer than the limit on its own length | 6-10%; all | 7.9% (210 of 2,669); 209 of the 209 resumed inside the window | pass |
| R9 elements by gross over estimate, largest first | run hours, outside processing, setup hours, scrap and rework, material | run hours $1,702K, outside processing $1,013K, setup hours $544K, scrap and rework $124K, material $107K | pass |
| R10 not attributable share of the overrun before offsets | 30-50% | 34.0% | pass |
| R11 margin on revenue; estimated margin | 22-26%; 26-30% | 25.4%; 28.8% | pass |
| R12 jobs losing money | 6-10% | 7.4% | pass |
| R13 margin by family at the pools less at the blended rate: manual-heavy families; 5-axis-heavy families; the family with the highest margin at the blended rate | +5 to +9 points; at least one at -5 or lower and none above 0; not in the top two at the pools | +6.6, +6.5; -7.4, -2.9; Aerospace brackets is number 8 at the pools | pass |
| Customer margin range, top 15 customers by revenue | lowest 21-27%; highest 33-42% | 22.8% to 39.6% | pass |
| Revision-heavy account, margin on price: against the shop's margin on revenue; against its own estimated margin | within 2 points; 6 to 9 points below | +0.5 points below the shop (24.9% against 25.4%); 7.5 points below its estimate (32.4%) | pass |
| R14 lots under 25 pieces: margin a job; share losing money | 10-16%; 15-22% | 13.6%; 19.3% (902 jobs) | pass |
| R15 physical sense: operations with negative hours; interrupted operations in order (start, stop, resume, end); invoices below the vendor's minimum; change-order lines without a revision after release | 0; all; 0; 0 | 0; all of 210; 0 of 11,346; 0 | pass |
