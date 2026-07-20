#!/usr/bin/env python3
"""
Modelos ML principales del TFM — clasificación binaria riesgo_alto.

Especificación principal:
  - Muestra: 2015-2024 (predictores SESNSP con variación)
  - Validación temporal: train 2015-2019, test 2020-2024
  - Predictores: pobreza, homicidio, secuestro, pct_sin_municipio,
    comision_busqueda, log_poblacion (sin anio)

Modelos: logística (statsmodels + sklearn), Random Forest, XGBoost/GBM.

Salidas:
  output/tables/ml_metricas.csv
  output/tables/ml_logit_coeficientes.csv
  output/tables/ml_importancias.csv
  output/tables/ml_confusion_test.csv
  output/tables/ml_predicciones_test_2020_2024.csv
  output/tables/ml_shap_mean_abs.csv
  output/figures/ml_confusion_matrix.png
  output/figures/ml_importancias.png
  output/figures/ml_shap_mean_abs.png
  output/figures/heatmap_riesgo_estatal.png
  output/figures/atlas_riesgo_2024.png

Uso:
  python3 analysis/ml_panel.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "panel_ml_estatal_2010_2024.csv"
OUT_TABLES = ROOT / "output" / "tables"
OUT_FIGURES = ROOT / "output" / "figures"

FEATURES = [
    "pobreza_pct",
    "tasa_hom_doloso",
    "tasa_secuestro",
    "pct_sin_municipio",
    "comision_busqueda",
    "log_poblacion",
]

TRAIN_YEARS = (2015, 2019)
TEST_YEARS = (2020, 2024)


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(PANEL)
    df["riesgo_alto"] = (df["riesgo_cat"] == "alto").astype(int)
    for col in FEATURES + ["anio", "tasa_desap_100k"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def split_temporal(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df[(df["anio"] >= TRAIN_YEARS[0]) & (df["anio"] <= TRAIN_YEARS[1])].copy()
    test = df[(df["anio"] >= TEST_YEARS[0]) & (df["anio"] <= TEST_YEARS[1])].copy()
    return train, test


def eval_preds(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray) -> dict:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_alto": float(f1_score(y_true, y_pred, zero_division=0)),
        "precision_alto": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall_alto": float(recall_score(y_true, y_pred, zero_division=0)),
        "auc": float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) > 1 else float("nan"),
    }


def fit_logit_sm(train: pd.DataFrame) -> pd.DataFrame:
    y = train["riesgo_alto"]
    x = sm.add_constant(train[FEATURES], has_constant="add")
    model = sm.Logit(y, x).fit(disp=0, maxiter=500, method="bfgs")
    rows = []
    ci = model.conf_int()
    for var in x.columns:
        rows.append(
            {
                "variable": var,
                "coef": float(model.params[var]),
                "se": float(model.bse[var]),
                "z": float(model.tvalues[var]),
                "pvalor": float(model.pvalues[var]),
                "or": float(np.exp(model.params[var])) if var != "const" else np.nan,
                "or_ic95_inf": float(np.exp(ci.loc[var, 0])) if var != "const" else np.nan,
                "or_ic95_sup": float(np.exp(ci.loc[var, 1])) if var != "const" else np.nan,
            }
        )
    rows.append({"variable": "_pseudo_r2", "coef": float(model.prsquared)})
    return pd.DataFrame(rows)


def fit_sklearn_models(
    train: pd.DataFrame, test: pd.DataFrame
) -> tuple[dict, np.ndarray, np.ndarray, dict]:
    x_train = train[FEATURES].to_numpy()
    y_train = train["riesgo_alto"].to_numpy()
    x_test = test[FEATURES].to_numpy()
    y_test = test["riesgo_alto"].to_numpy()

    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_test_s = scaler.transform(x_test)

    models: dict = {
        "logit_sklearn": LogisticRegression(max_iter=2000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=4,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=42,
        ),
    }

    xgb_ok = False
    try:
        from xgboost import XGBClassifier

        models["xgboost"] = XGBClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=max(1.0, (y_train == 0).sum() / max(1, (y_train == 1).sum())),
            random_state=42,
            eval_metric="logloss",
        )
        xgb_ok = True
    except Exception as exc:
        print(f"XGBoost no disponible ({exc.__class__.__name__}); usando GradientBoosting")
        models["gradient_boosting"] = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.08,
            random_state=42,
        )

    use_scaled = {"logit_sklearn"}

    metrics_rows: list[dict] = []
    importances: dict[str, np.ndarray] = {}
    fitted: dict = {}
    best_name = ""
    best_auc = -1.0
    best_proba = None
    best_pred = None

    for name, clf in models.items():
        xt = x_train_s if name in use_scaled else x_train
        xs = x_test_s if name in use_scaled else x_test
        clf.fit(xt, y_train)
        fitted[name] = clf
        proba = clf.predict_proba(xs)[:, 1]
        pred = (proba >= 0.5).astype(int)
        m = eval_preds(y_test, pred, proba)
        m.update(
            {
                "modelo": name,
                "n_train": len(train),
                "n_test": len(test),
                "eventos_train": int(y_train.sum()),
                "eventos_test": int(y_test.sum()),
            }
        )
        metrics_rows.append(m)

        if hasattr(clf, "feature_importances_"):
            importances[name] = clf.feature_importances_
        elif hasattr(clf, "coef_"):
            importances[name] = np.abs(clf.coef_[0])

        if m["auc"] > best_auc:
            best_auc = m["auc"]
            best_name = name
            best_proba = proba
            best_pred = pred

    # statsmodels logit on same split — predict on test
    logit_df = fit_logit_sm(train)
    x_train_sm = sm.add_constant(train[FEATURES], has_constant="add")
    x_test_sm = sm.add_constant(test[FEATURES], has_constant="add")
    sm_model = sm.Logit(train["riesgo_alto"], x_train_sm).fit(disp=0, maxiter=500, method="bfgs")
    proba_sm = sm_model.predict(x_test_sm)
    pred_sm = (proba_sm >= 0.5).astype(int)
    m_sm = eval_preds(y_test, pred_sm, proba_sm)
    m_sm.update(
        {
            "modelo": "logit_statsmodels",
            "n_train": len(train),
            "n_test": len(test),
            "eventos_train": int(y_train.sum()),
            "eventos_test": int(y_test.sum()),
        }
    )
    metrics_rows.insert(0, m_sm)

    if m_sm["auc"] > best_auc:
        best_name = "logit_statsmodels"
        best_proba = proba_sm
        best_pred = pred_sm

    return (
        {
            "metrics": metrics_rows,
            "logit": logit_df,
            "importances": importances,
            "best": best_name,
            "fitted": fitted,
            "xgb_ok": xgb_ok,
            "x_train": x_train,
            "x_test": x_test,
        },
        best_pred,
        best_proba,
        {"y_test": y_test},
    )


def compute_shap(
    fitted: dict,
    x_train: np.ndarray,
    x_test: np.ndarray,
) -> tuple[pd.DataFrame | None, str | None]:
    """SHAP mean |value| por variable; prioriza XGBoost."""
    try:
        import shap
    except ImportError:
        print("shap no instalado; omitiendo explicación SHAP")
        return None, None

    model_name = None
    for cand in ("xgboost", "random_forest", "gradient_boosting"):
        if cand in fitted:
            model_name = cand
            break
    if model_name is None:
        return None, None

    model = fitted[model_name]
    # TreeExplainer es estable con RF/XGB; sample train como fondo
    n_bg = min(80, len(x_train))
    rng = np.random.default_rng(42)
    bg_idx = rng.choice(len(x_train), size=n_bg, replace=False)
    background = x_train[bg_idx]

    explainer = shap.TreeExplainer(model, data=background)
    shap_values = explainer.shap_values(x_test)

    # Binary classifiers may return list [class0, class1] or 2D array
    if isinstance(shap_values, list):
        vals = np.asarray(shap_values[1])
    else:
        vals = np.asarray(shap_values)
        if vals.ndim == 3:
            vals = vals[:, :, 1]

    mean_abs = np.abs(vals).mean(axis=0)
    rows = [
        {
            "modelo": model_name,
            "variable": feat,
            "mean_abs_shap": float(v),
            "rank": i + 1,
        }
        for i, (feat, v) in enumerate(
            sorted(zip(FEATURES, mean_abs), key=lambda x: -x[1])
        )
    ]
    # re-rank after sort
    for i, row in enumerate(rows):
        row["rank"] = i + 1
    return pd.DataFrame(rows), model_name


def figure_shap(df_shap: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    from plot_style import BARRAS_SHAP, GRIS_ALUMINIO, apply_tfm_style, save_figure, style_axes

    apply_tfm_style()
    sub = df_shap.sort_values("mean_abs_shap", ascending=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(sub["variable"], sub["mean_abs_shap"], color=BARRAS_SHAP, height=0.65)
    ax.set_title(f"SHAP — media |valor| ({sub['modelo'].iloc[0]}, test 2020-2024)")
    ax.set_xlabel("Mean |SHAP|")
    style_axes(ax, grid_y=False, grid_x=True)
    save_figure(fig, path)
    plt.close(fig)


def save_importances(importances: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    for model, vals in importances.items():
        for feat, val in zip(FEATURES, vals):
            rows.append({"modelo": model, "variable": feat, "importancia": float(val)})
    return pd.DataFrame(rows)


def figure_confusion(y_true: np.ndarray, y_pred: np.ndarray, path: Path) -> None:
    import matplotlib.pyplot as plt

    from plot_style import GRIS_ALUMINIO, apply_tfm_style, confusion_cmap, save_figure

    apply_tfm_style()
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, cmap=confusion_cmap())
    ax.set_xticks([0, 1], labels=["Pred. bajo", "Pred. alto"])
    ax.set_yticks([0, 1], labels=["Obs. bajo", "Obs. alto"])
    thresh = cm.max() / 2.0 if cm.max() else 0
    for i in range(2):
        for j in range(2):
            color = "white" if cm[i, j] > thresh else GRIS_ALUMINIO
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color=color, fontweight="bold")
    ax.set_title("Matriz de confusión — test 2020-2024")
    fig.colorbar(im, ax=ax, fraction=0.046)
    save_figure(fig, path)
    plt.close(fig)


def figure_importances(df_imp: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    from plot_style import BARRAS_IMPORTANCIA, apply_tfm_style, save_figure, style_axes

    apply_tfm_style()
    for pref in ("xgboost", "gradient_boosting", "random_forest", "logit_sklearn"):
        sub = df_imp[df_imp["modelo"] == pref]
        if not sub.empty:
            break
    else:
        return
    sub = sub.sort_values("importancia", ascending=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(sub["variable"], sub["importancia"], color=BARRAS_IMPORTANCIA, height=0.65)
    ax.set_title(f"Importancia de variables — {pref}")
    ax.set_xlabel("Importancia")
    style_axes(ax, grid_y=False, grid_x=True)
    save_figure(fig, path)
    plt.close(fig)


def figure_heatmap(df: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt

    from plot_style import apply_tfm_style, risk_cmap, save_figure

    apply_tfm_style()
    pivot = df.pivot_table(index="estado", columns="anio", values="tasa_desap_100k", aggfunc="first")
    order = pivot.mean(axis=1).sort_values(ascending=False).index
    pivot = pivot.loc[order]
    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap=risk_cmap())
    ax.set_xticks(range(len(pivot.columns)), labels=pivot.columns.astype(int), rotation=45, ha="right")
    ax.set_yticks(range(len(pivot.index)), labels=pivot.index, fontsize=7)
    ax.set_title("Tasa de desaparición/no localización (por 100k) — entidad × año")
    ax.set_xlabel("Año")
    ax.set_ylabel("Entidad federativa")
    cbar = fig.colorbar(im, ax=ax, label="Tasa / 100k")
    cbar.ax.yaxis.label.set_color("#4D4D4D")
    save_figure(fig, path)
    plt.close(fig)


def figure_atlas_2024(df: pd.DataFrame, path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    from plot_style import (
        GRIS_ALUMINIO,
        RIESGO_ALTO,
        RIESGO_BAJO,
        RIESGO_NA,
        apply_tfm_style,
        save_figure,
        style_axes,
    )

    apply_tfm_style()
    sub = df[df["anio"] == 2024].copy().sort_values("tasa_desap_100k", ascending=True)
    colors = sub["riesgo_cat"].map({"bajo": RIESGO_BAJO, "alto": RIESGO_ALTO}).fillna(RIESGO_NA)
    fig, ax = plt.subplots(figsize=(10, 12))
    ax.barh(sub["estado"], sub["tasa_desap_100k"], color=colors, height=0.72)
    ax.axvline(13.1, color=GRIS_ALUMINIO, linestyle="--", linewidth=1.2, label="Umbral DH (~13,1/100k)")
    ax.set_xlabel("Tasa RNPDNO estatus 7 (por 100.000 hab.)")
    ax.set_title("Atlas de riesgo observado — 2024")
    ax.legend(
        handles=[
            Patch(facecolor=RIESGO_BAJO, label="Riesgo bajo"),
            Patch(facecolor=RIESGO_ALTO, label="Riesgo alto"),
            plt.Line2D([0], [0], color=GRIS_ALUMINIO, linestyle="--", label="Umbral DH (~13,1/100k)"),
        ],
        loc="lower right",
    )
    style_axes(ax, grid_y=False, grid_x=True)
    save_figure(fig, path)
    plt.close(fig)


def main() -> None:
    if not PANEL.exists():
        raise SystemExit("Ejecuta primero: python3 build_state_panel.py")

    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)

    df = load_panel()
    train, test = split_temporal(df)

    results, y_pred, y_proba, aux = fit_sklearn_models(train, test)
    y_test = aux["y_test"]

    metrics_df = pd.DataFrame(results["metrics"])
    metrics_path = OUT_TABLES / "ml_metricas.csv"
    metrics_df.to_csv(metrics_path, index=False)

    logit_path = OUT_TABLES / "ml_logit_coeficientes.csv"
    results["logit"].to_csv(logit_path, index=False)

    imp_df = save_importances(results["importances"])
    imp_path = OUT_TABLES / "ml_importancias.csv"
    imp_df.to_csv(imp_path, index=False)

    shap_df, shap_model = compute_shap(
        results["fitted"], results["x_train"], results["x_test"]
    )
    shap_path = OUT_TABLES / "ml_shap_mean_abs.csv"
    if shap_df is not None:
        shap_df.to_csv(shap_path, index=False)

    cm = confusion_matrix(y_test, y_pred, labels=[0, 1])
    cm_df = pd.DataFrame(cm, index=["obs_bajo", "obs_alto"], columns=["pred_bajo", "pred_alto"])
    cm_path = OUT_TABLES / "ml_confusion_test.csv"
    cm_df.to_csv(cm_path)

    pred_out = test[["estado", "anio", "tasa_desap_100k", "riesgo_cat", "riesgo_alto"]].copy()
    pred_out["riesgo_pred"] = np.where(y_pred == 1, "alto", "bajo")
    pred_out["prob_alto"] = y_proba
    pred_path = OUT_TABLES / "ml_predicciones_test_2020_2024.csv"
    pred_out.to_csv(pred_path, index=False)

    summary = {
        "best_model": results["best"],
        "xgb_available": results["xgb_ok"],
        "shap_model": shap_model,
        "train_years": list(TRAIN_YEARS),
        "test_years": list(TEST_YEARS),
        "features": FEATURES,
        "metrics": metrics_df.to_dict(orient="records"),
    }
    (OUT_TABLES / "ml_resumen.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    try:
        import matplotlib  # noqa: F401

        figure_confusion(y_test, y_pred, OUT_FIGURES / "ml_confusion_matrix.png")
        figure_importances(imp_df, OUT_FIGURES / "ml_importancias.png")
        if shap_df is not None:
            figure_shap(shap_df, OUT_FIGURES / "ml_shap_mean_abs.png")
        figure_heatmap(df, OUT_FIGURES / "heatmap_riesgo_estatal.png")
        figure_atlas_2024(df, OUT_FIGURES / "atlas_riesgo_2024.png")
        print("Figuras guardadas en output/figures/")
    except ImportError:
        print("matplotlib no disponible; omitiendo figuras")

    print(f"Mejor modelo (AUC test): {results['best']}")
    print(f"XGBoost disponible: {results['xgb_ok']} | SHAP: {shap_model}")
    print(metrics_df.to_string(index=False))
    if shap_df is not None:
        print("\nSHAP mean |valor|:")
        print(shap_df.to_string(index=False))
    print(f"\nArchivos: {metrics_path.name}, {logit_path.name}, {imp_path.name}")


if __name__ == "__main__":
    main()
