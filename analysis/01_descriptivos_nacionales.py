#!/usr/bin/env python3
"""Descriptivos nacionales y estatales para el capítulo de resultados del TFM."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "panel_ml_estatal_2010_2024.csv"
OUT_TABLES = ROOT / "output" / "tables"
OUT_FIGURES = ROOT / "output" / "figures"


def load_panel() -> list[dict[str, str]]:
    with PANEL.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def tabla_serie_nacional(rows: list[dict[str, str]]) -> None:
    by_year: dict[int, int] = defaultdict(int)
    for r in rows:
        by_year[int(r["anio"])] += int(r["desap_count"])
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    path = OUT_TABLES / "serie_nacional_desap_2010_2024.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["anio", "desap_count", "fuente"])
        for anio in sorted(by_year):
            w.writerow([anio, by_year[anio], "RNPDNO estatus 7, panel ML"])
    print(f"Escrito: {path}")


def tabla_ranking_estados(rows: list[dict[str, str]]) -> None:
    acum: dict[str, int] = defaultdict(int)
    for r in rows:
        acum[r["estado"]] += int(r["desap_count"])
    ranked = sorted(acum.items(), key=lambda x: -x[1])
    path = OUT_TABLES / "ranking_estados_acumulado_2010_2024.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["estado", "desap_count_acum", "fuente"])
        for estado, total in ranked:
            w.writerow([estado, total, "RNPDNO estatus 7"])
    print(f"Escrito: {path}")


def tabla_sexo_nacional(rows: list[dict[str, str]]) -> None:
    by_year: dict[int, dict[str, int]] = defaultdict(lambda: {"h": 0, "m": 0, "total": 0})
    for r in rows:
        anio = int(r["anio"])
        h = int(r.get("desap_hombres") or 0)
        m = int(r.get("desap_mujeres") or 0)
        by_year[anio]["h"] += h
        by_year[anio]["m"] += m
        by_year[anio]["total"] += int(r["desap_count"])
    path = OUT_TABLES / "serie_nacional_sexo_2010_2024.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["anio", "hombres", "mujeres", "total", "pct_hombres", "fuente"])
        for anio in sorted(by_year):
            d = by_year[anio]
            pct = round(100.0 * d["h"] / d["total"], 2) if d["total"] else 0
            w.writerow([anio, d["h"], d["m"], d["total"], pct, "RNPDNO estatus 7, panel ML"])
    print(f"Escrito: {path}")


def figura_serie_nacional(rows: list[dict[str, str]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib no instalado; omitiendo figura")
        return
    import sys

    sys.path.insert(0, str(ROOT / "analysis"))
    from plot_style import SERIE_PRINCIPAL, apply_tfm_style, save_figure, style_axes

    apply_tfm_style()
    by_year: dict[int, int] = defaultdict(int)
    for r in rows:
        by_year[int(r["anio"])] += int(r["desap_count"])
    years = sorted(by_year)
    vals = [by_year[y] for y in years]
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(years, vals, marker="o", linewidth=2.2, color=SERIE_PRINCIPAL, markersize=6)
    ax.fill_between(years, vals, alpha=0.12, color=SERIE_PRINCIPAL)
    ax.set_title("Personas desaparecidas y no localizadas (RNPDNO, estatus 7)")
    ax.set_xlabel("Año")
    ax.set_ylabel("Personas")
    style_axes(ax, grid_y=True)
    path = OUT_FIGURES / "serie_nacional_2010_2024.png"
    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


def figura_sexo_nacional(rows: list[dict[str, str]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib no instalado; omitiendo figura sexo")
        return
    import sys

    sys.path.insert(0, str(ROOT / "analysis"))
    from plot_style import SERIE_HOMBRES, SERIE_MUJERES, apply_tfm_style, save_figure, style_axes

    apply_tfm_style()
    by_year: dict[int, dict[str, int]] = defaultdict(lambda: {"h": 0, "m": 0})
    for r in rows:
        anio = int(r["anio"])
        by_year[anio]["h"] += int(r.get("desap_hombres") or 0)
        by_year[anio]["m"] += int(r.get("desap_mujeres") or 0)
    years = sorted(by_year)
    h_vals = [by_year[y]["h"] for y in years]
    m_vals = [by_year[y]["m"] for y in years]
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(years, h_vals, marker="o", label="Hombres", linewidth=2.2, color=SERIE_HOMBRES, markersize=6)
    ax.plot(years, m_vals, marker="s", label="Mujeres", linewidth=2.2, color=SERIE_MUJERES, markersize=5)
    ax.set_title("Personas desaparecidas y no localizadas por sexo (RNPDNO, estatus 7)")
    ax.set_xlabel("Año")
    ax.set_ylabel("Personas")
    ax.legend(loc="upper left")
    style_axes(ax, grid_y=True)
    path = OUT_FIGURES / "serie_nacional_sexo_2010_2024.png"
    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


def main() -> None:
    if not PANEL.exists():
        raise SystemExit("Ejecuta primero: python3 build_state_panel.py")
    rows = load_panel()
    tabla_serie_nacional(rows)
    tabla_ranking_estados(rows)
    tabla_sexo_nacional(rows)
    figura_serie_nacional(rows)
    figura_sexo_nacional(rows)


if __name__ == "__main__":
    main()
