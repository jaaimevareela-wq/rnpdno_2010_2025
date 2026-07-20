#!/usr/bin/env python3
"""Mapas coropléticos estatales (INEGI) — atlas observado y predicho 2024."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GEOJSON = ROOT / "data" / "external" / "geo" / "entidades_federativas_simplificado.geojson"
GEOJSON_FULL = ROOT / "data" / "external" / "geo" / "entidades_federativas.geojson"
PANEL = ROOT / "data" / "processed" / "panel_ml_estatal_2010_2024.csv"
PREDS = ROOT / "output" / "tables" / "ml_predicciones_test_2020_2024.csv"
OUT_FIGURES = ROOT / "output" / "figures"

sys.path.insert(0, str(ROOT / "analysis"))


def load_geo() -> "geopandas.GeoDataFrame":
    import geopandas as gpd

    path = GEOJSON if GEOJSON.exists() else GEOJSON_FULL
    if not path.exists():
        raise SystemExit(
            f"Falta geometría estatal. Ejecuta: python3 fetch_inegi_geo.py\n"
            f"(busca {GEOJSON} o {GEOJSON_FULL})"
        )
    gdf = gpd.read_file(path)
    # Normalizar cve
    for col in ("cve_ent", "CVE_ENT", "cvegeo", "CVEGEO"):
        if col in gdf.columns:
            gdf["cve_ent"] = gdf[col].astype(str).str.zfill(2)
            break
    if "cve_ent" not in gdf.columns:
        raise SystemExit(f"GeoJSON sin cve_ent. Columnas: {list(gdf.columns)}")
    gdf["cve_ent"] = gdf["cve_ent"].astype(str).str.zfill(2)
    return gdf


def _plot_choropleth(
    gdf,
    column: str,
    title: str,
    path: Path,
    *,
    categorical: bool,
    legend_label: str = "Tasa / 100k",
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable

    from plot_style import (
        GRIS_ALUMINIO,
        RIESGO_ALTO,
        RIESGO_BAJO,
        RIESGO_NA,
        apply_tfm_style,
        risk_cmap,
        save_figure,
    )

    apply_tfm_style()
    fig, ax = plt.subplots(figsize=(10, 8))
    if categorical:
        color_map = {"bajo": RIESGO_BAJO, "alto": RIESGO_ALTO}
        gdf = gdf.copy()
        gdf["_color"] = gdf[column].map(color_map).fillna(RIESGO_NA)
        gdf.plot(ax=ax, color=gdf["_color"], edgecolor="white", linewidth=0.4)
        legend = [
            Patch(facecolor=RIESGO_BAJO, edgecolor="white", label="Riesgo bajo"),
            Patch(facecolor=RIESGO_ALTO, edgecolor="white", label="Riesgo alto"),
        ]
        ax.legend(handles=legend, loc="lower left", frameon=False)
    else:
        gdf.plot(
            ax=ax,
            column=column,
            cmap=risk_cmap(),
            edgecolor="white",
            linewidth=0.4,
            legend=True,
            legend_kwds={"label": legend_label, "shrink": 0.65},
            missing_kwds={"color": "#EAEAEA"},
        )
    ax.set_axis_off()
    ax.set_title(title, color=GRIS_ALUMINIO, fontweight="bold", pad=12)
    if categorical and "estado" in gdf.columns:
        altos = gdf[gdf[column] == "alto"]
        for _, row in altos.iterrows():
            try:
                pt = row.geometry.representative_point()
                ax.annotate(
                    str(row.get("estado", ""))[:12],
                    xy=(pt.x, pt.y),
                    fontsize=5.5,
                    ha="center",
                    color="white",
                    fontweight="bold",
                )
            except Exception:
                pass
    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


def atlas_observado_2024() -> None:
    import geopandas as gpd

    gdf = load_geo()
    panel = pd.read_csv(PANEL)
    sub = panel[panel["anio"] == 2024][
        ["cve_estado", "estado", "tasa_desap_100k", "riesgo_cat"]
    ].copy()
    sub["cve_estado"] = sub["cve_estado"].astype(str).str.zfill(2)
    merged = gdf.merge(sub, left_on="cve_ent", right_on="cve_estado", how="left")

    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    _plot_choropleth(
        merged,
        "riesgo_cat",
        "Atlas de riesgo observado — 2024 (RNPDNO estatus 7)",
        OUT_FIGURES / "atlas_mapa_observado_2024.png",
        categorical=True,
    )
    _plot_choropleth(
        merged,
        "tasa_desap_100k",
        "Tasa de desaparición/no localización por 100k — 2024",
        OUT_FIGURES / "atlas_mapa_tasa_2024.png",
        categorical=False,
    )


def atlas_predicho_2024() -> None:
    gdf = load_geo()
    if not PREDS.exists():
        raise SystemExit(f"Falta {PREDS}. Ejecuta: python3 analysis/ml_panel.py")
    preds = pd.read_csv(PREDS)
    sub = preds[preds["anio"] == 2024].copy()
    # Unir CVE desde panel
    panel = pd.read_csv(PANEL)
    keys = panel[["estado", "cve_estado"]].drop_duplicates()
    keys["cve_estado"] = keys["cve_estado"].astype(str).str.zfill(2)
    sub = sub.merge(keys, on="estado", how="left")
    merged = gdf.merge(sub, left_on="cve_ent", right_on="cve_estado", how="left")

    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    _plot_choropleth(
        merged,
        "riesgo_pred",
        "Atlas de riesgo predicho — Random Forest, 2024 (test OOS)",
        OUT_FIGURES / "atlas_mapa_predicho_2024.png",
        categorical=True,
    )
    # Mapa continuo de probabilidad
    _plot_choropleth(
        merged,
        "prob_alto",
        "Probabilidad predicha de riesgo alto — RF, 2024",
        OUT_FIGURES / "atlas_mapa_prob_alto_2024.png",
        categorical=False,
        legend_label="P(riesgo alto)",
    )


def main() -> None:
    try:
        import geopandas  # noqa: F401
    except ImportError:
        raise SystemExit("Instala geopandas: python3 -m pip install geopandas")
    atlas_observado_2024()
    atlas_predicho_2024()


if __name__ == "__main__":
    main()
