#!/usr/bin/env python3
"""
Sensibilidad del coeficiente institucional: decreto vs. titular.

Compara regresión logística binaria (riesgo alto vs. bajo) con la misma
especificación salvo la dummy de comisión de búsqueda.

Notas metodológicas:
- Muestra principal 2015-2024 (SESNSP con variación; evita 2010-14 en cero).
- `anio` se excluye en la spec principal: correlación ~0.85 con ambas dummies
  institucionales y colapsa el coeficiente.
- 2020-2024: `comision_busqueda` es constante (=1); solo titular varía.

Uso:
  python3 analysis/ml_comision_sensibilidad.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "panel_ml_estatal_2010_2024.csv"
OUT_DIR = ROOT / "output" / "tables"

CORE_PREDICTORS = [
    "pobreza_pct",
    "tasa_hom_doloso",
    "tasa_secuestro",
    "pct_sin_municipio",
    "log_poblacion",
]

INST_SPECS = {
    "decreto": "comision_busqueda",
    "titular": "comision_busqueda_titular",
}


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(PANEL)
    df["riesgo_alto"] = (df["riesgo_cat"] == "alto").astype(int)
    cols = CORE_PREDICTORS + list(INST_SPECS.values()) + ["anio"]
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fit_logit(
    df: pd.DataFrame,
    inst_col: str,
    label: str,
    sample: str,
    include_anio: bool,
) -> dict | None:
    if df[inst_col].nunique() < 2:
        return None
    if df["riesgo_alto"].nunique() < 2:
        return None

    x_cols = CORE_PREDICTORS + ([ "anio"] if include_anio else []) + [inst_col]
    y = df["riesgo_alto"]
    x = sm.add_constant(df[x_cols], has_constant="add")
    try:
        model = sm.Logit(y, x).fit(disp=0, maxiter=500, method="bfgs")
    except Exception:
        return None

    ci = model.conf_int().loc[inst_col]
    spec_name = f"{label}{'_con_anio' if include_anio else ''}"
    return {
        "muestra": sample,
        "especificacion": spec_name,
        "variable_institucional": inst_col,
        "incluye_anio": include_anio,
        "n": int(model.nobs),
        "eventos_alto": int(y.sum()),
        "coef": float(model.params[inst_col]),
        "se": float(model.bse[inst_col]),
        "z": float(model.tvalues[inst_col]),
        "pvalor": float(model.pvalues[inst_col]),
        "or": float(np.exp(model.params[inst_col])),
        "or_ic95_inf": float(np.exp(ci[0])),
        "or_ic95_sup": float(np.exp(ci[1])),
        "pseudo_r2": float(model.prsquared),
    }


def fit_sklearn_temporal(
    train: pd.DataFrame, test: pd.DataFrame, inst_col: str, label: str
) -> dict | None:
    if train[inst_col].nunique() < 2:
        return None
    x_cols = CORE_PREDICTORS + [inst_col]
    x_train = train[x_cols].to_numpy()
    y_train = train["riesgo_alto"].to_numpy()
    x_test = test[x_cols].to_numpy()
    y_test = test["riesgo_alto"].to_numpy()

    if y_train.sum() == 0 or y_test.sum() == 0:
        return None

    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_test_s = scaler.transform(x_test)

    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    clf.fit(x_train_s, y_train)
    proba = clf.predict_proba(x_test_s)[:, 1]
    pred = (proba >= 0.5).astype(int)

    inst_idx = len(x_cols) - 1
    coef = float(clf.coef_[0][inst_idx])
    auc = roc_auc_score(y_test, proba)
    return {
        "muestra": "train2015-2019_test2020-2024",
        "especificacion": label,
        "variable_institucional": inst_col,
        "n_train": len(train),
        "n_test": len(test),
        "eventos_train": int(y_train.sum()),
        "eventos_test": int(y_test.sum()),
        "coef_estandarizado": coef,
        "or_estandarizado": float(np.exp(coef)),
        "test_accuracy": float(accuracy_score(y_test, pred)),
        "test_f1_alto": float(f1_score(y_test, pred, zero_division=0)),
        "test_recall_alto": float(recall_score(y_test, pred, zero_division=0)),
        "test_auc": float(auc),
    }


def sig_label(p: float) -> str:
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


def main() -> None:
    df = load_panel()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    logit_rows: list[dict] = []
    ml_rows: list[dict] = []

    samples = {
        "2015-2024": df[(df["anio"] >= 2015) & (df["anio"] <= 2024)],
        "2010-2024": df,
        "2020-2024": df[(df["anio"] >= 2020) & (df["anio"] <= 2024)],
    }

    for sample_name, sub in samples.items():
        for label, inst_col in INST_SPECS.items():
            for include_anio in (False, True):
                row = fit_logit(sub.copy(), inst_col, label, sample_name, include_anio)
                if row:
                    logit_rows.append(row)

    train = df[(df["anio"] >= 2015) & (df["anio"] <= 2019)].copy()
    test = df[(df["anio"] >= 2020) & (df["anio"] <= 2024)].copy()
    for label, inst_col in INST_SPECS.items():
        row = fit_sklearn_temporal(train, test, inst_col, label)
        if row:
            ml_rows.append(row)

    logit_path = OUT_DIR / "comision_sensibilidad_logit.csv"
    ml_path = OUT_DIR / "comision_sensibilidad_validacion_temporal.csv"
    summary_path = OUT_DIR / "comision_sensibilidad_resumen.txt"

    pd.DataFrame(logit_rows).to_csv(logit_path, index=False)
    pd.DataFrame(ml_rows).to_csv(ml_path, index=False)

    primary = [
        r
        for r in logit_rows
        if r["muestra"] == "2015-2024" and not r["incluye_anio"]
    ]
    dec = next(r for r in primary if r["especificacion"] == "decreto")
    tit = next(r for r in primary if r["especificacion"] == "titular")

    lines = [
        "Sensibilidad institucional: comisión por decreto vs. por titular",
        "=" * 62,
        "",
        "VD: riesgo_alto (Dalenius-Hodges 'alto' vs. resto)",
        f"VI estructurales: {', '.join(CORE_PREDICTORS)}",
        "",
        "ESPECIFICACIÓN PRINCIPAL — logit 2015-2024, sin anio:",
        f"  decreto   coef={dec['coef']:+.4f}  OR={dec['or']:.3f}  "
        f"p={dec['pvalor']:.4f}{sig_label(dec['pvalor'])}  "
        f"(n={dec['n']}, eventos={dec['eventos_alto']})",
        f"  titular   coef={tit['coef']:+.4f}  OR={tit['or']:.3f}  "
        f"p={tit['pvalor']:.4f}{sig_label(tit['pvalor'])}  "
        f"(n={tit['n']}, eventos={tit['eventos_alto']})",
        "",
        f"  Cambio de signo: {'SÍ' if (dec['coef'] > 0) != (tit['coef'] > 0) else 'NO'}",
        f"  Significativo (p<0.05) decreto: {'SÍ' if dec['pvalor'] < 0.05 else 'NO'}",
        f"  Significativo (p<0.05) titular: {'SÍ' if tit['pvalor'] < 0.05 else 'NO'}",
        "",
        "Todas las especificaciones logit:",
    ]
    for row in logit_rows:
        anio_tag = "+anio" if row["incluye_anio"] else "sin anio"
        lines.append(
            f"  [{row['muestra']}, {anio_tag}] {row['especificacion']:14}  "
            f"coef={row['coef']:+.4f}  OR={row['or']:.3f}  "
            f"p={row['pvalor']:.4f}{sig_label(row['pvalor'])}"
        )

    lines.extend(["", "Validación temporal sklearn (train 2015-2019, test 2020-2024):"])
    if ml_rows:
        for row in ml_rows:
            lines.append(
                f"  {row['especificacion']:7}  coef_std={row['coef_estandarizado']:+.4f}  "
                f"AUC={row['test_auc']:.3f}  F1_alto={row['test_f1_alto']:.3f}  "
                f"recall_alto={row['test_recall_alto']:.3f}"
            )
    else:
        lines.append("  (no estimable)")

    lines.extend(
        [
            "",
            "Interpretación breve:",
            "- Ambas dummies apuntan en la misma dirección (OR>1): más riesgo",
            "  asociado a tener comisión, contraintuitivo si se lee causalmente.",
            "- Ninguna alcanza significancia estadística convencional.",
            "- Incluir `anio` anula la identificación del efecto institucional.",
            "- En 2020-2024 la dummy por decreto no varía (todas las entidades=1).",
            "",
            f"Archivos: {logit_path.name}, {ml_path.name}",
        ]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
