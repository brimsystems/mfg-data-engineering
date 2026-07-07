"""
ablation.py
The 7-day model with and without the sensor layer, for one evaluation table.

Retrains the selected candidate on the 7-day target with the same tuning as
training.py, once on all features and once without the ten sensor features (the
nine sensor features and the anomaly flag built on them), and scores both on the
held-out test set and the scoring window. Nothing is registered: the result is
an evaluation artifact, ml/models/ablation_no_sensors.csv. Both rows are the
uncalibrated model, so ROC-AUC and average precision are comparable between
them; the first row can differ slightly from the calibrated production figures.

Run after training.py:  python ml/src/ablation.py
"""
import json
import logging
import warnings
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

import sys
sys.path.insert(0, str(Path(__file__).parent))
import training as T
from features import ALL_FEATURES, TARGETS
from health import TRAIN_END, load_mart

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)

OUT = T.MODELS_DIR / "ablation_no_sensors.csv"


def main():
    best_type = json.loads((T.MODELS_DIR / "metrics.json").read_text())["best_model_type"]
    without = [f for f in ALL_FEATURES if f not in T.SENSOR_LAYER]
    target = TARGETS[7]

    mart = load_mart()
    train = mart[mart["observation_date"] <= TRAIN_END]
    val   = mart[(mart["observation_date"] > TRAIN_END) & (mart["observation_date"] <= T.VAL_END)]
    parts = {
        "test":    mart[(mart["observation_date"] > T.VAL_END) & (mart["observation_date"] <= T.TEST_END)],
        "scoring": mart[(mart["observation_date"] > T.TEST_END) & mart[target].notna()],
    }

    rows = []
    for label, cols in (("all features", ALL_FEATURES), ("without sensor features", without)):
        tree_prep, linear_prep = T.build_preprocessors(train[cols])
        prep = linear_prep if best_type == "logistic_regression" else tree_prep
        pipe, _ = T.TUNERS[best_type](train[cols], train[target].astype(int),
                                      val[cols], val[target].astype(int), prep)
        for split, d in parts.items():
            p = pipe.predict_proba(d[cols])[:, 1]
            y = d[target].astype(int)
            rows.append({"model": label, "model_type": best_type, "features": len(cols),
                         "split": split, "rows": len(d),
                         "roc_auc": round(float(roc_auc_score(y, p)), 6),
                         "average_precision": round(float(average_precision_score(y, p)), 6)})
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    log.info("\n" + out.to_string(index=False))
    log.info(f"Saved {OUT}")


if __name__ == "__main__":
    main()
