#!/usr/bin/env python3
"""Descriptivos por grupo de edad (RNPDNO estatus 7) a partir del panel municipal."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL_GEO = ROOT / "data" / "panel" / "panel_estatus7_2010_2025_geo.csv"
OUT_TABLES = ROOT / "output" / "tables"
OUT_FIGURES = ROOT / "output" / "figures"

# Bandas amplias para lectura en el TFM
BAND_MAP = {
    "0-4": "0-17",
    "5-9": "0-17",
    "10-14": "0-17",
    "15-17": "0-17",  # por si existe
    "15-19": "18-29",  # 15-19 se reparte; usamos 15-19 en jovenes adultos (convención RNPDNO)
    "20-24": "18-29",
    "25-29": "18-29",
    "30-34": "30-44",
    "35-39": "30-44",
    "40-44": "30-44",
    "45-49": "45-59",
    "50-54": "45-59",
    "55-59": "45-59",
    "60-64": "60+",
    "65-69": "60+",
    "70-74": "60+",
    "75-79": "60+",
    "80+": "60+",
    "sin_edad": "Sin edad",
}

BAND_ORDER = ["0-17", "18-29", "30-44", "45-59", "60+", "Sin edad"]
# Recolocar 15-19: en México suele agruparse con jóvenes; mantenemos 15-19 en 18-29
# y añadimos 0-14 solo como 0-17 desde 0-4..10-14. Ajuste: 15-19 → jóvenes.


def load_rows() -> list[dict[str, str]]:
    with PANEL_GEO.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aggregate_national(rows: list[dict[str, str]]) -> dict[tuple[int, str], int]:
    """anio × banda_amplia → personas (2010–2024, sin id_estado 33)."""
    out: dict[tuple[int, str], int] = defaultdict(int)
    for r in rows:
        anio = int(r["anio"])
        if anio > 2024:
            continue
        if str(r.get("id_estado", "")) == "33":
            continue
        edad = (r.get("rango_edad") or "").strip()
        if edad in ("", "total"):
            continue
        banda = BAND_MAP.get(edad, "Sin edad" if edad == "sin_edad" else None)
        if banda is None:
            # bandas no mapeadas (p. ej. 15-19 ya mapeada): intentar prefijo
            if edad.startswith("1") and "-" in edad:
                banda = "18-29"
            elif edad == "sin_edad":
                banda = "Sin edad"
            else:
                continue
        # Corrección: 0-4, 5-9, 10-14 → 0-17; 15-19 ya en 18-29
        if edad in ("0-4", "5-9", "10-14"):
            banda = "0-17"
        elif edad == "15-19":
            banda = "18-29"
        out[(anio, banda)] += int(float(r["personas"] or 0))
    return out


def write_table(agg: dict[tuple[int, str], int]) -> Path:
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    path = OUT_TABLES / "serie_nacional_edad_2010_2024.csv"
    years = sorted({a for a, _ in agg})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["anio", "banda_edad", "personas", "pct", "fuente"])
        for anio in years:
            total = sum(agg.get((anio, b), 0) for b in BAND_ORDER)
            for b in BAND_ORDER:
                n = agg.get((anio, b), 0)
                pct = round(100.0 * n / total, 2) if total else 0.0
                w.writerow([anio, b, n, pct, "RNPDNO estatus 7, panel municipal"])
    print(f"Escrito: {path}")
    return path


def figura_edad(agg: dict[tuple[int, str], int]) -> None:
    try:
        import matplotlib.pyplot as plt
        import sys

        sys.path.insert(0, str(ROOT / "analysis"))
        from plot_style import (
            AZUL_CENTENARIO,
            AZUL_CLARO,
            GRIS_ALUMINIO,
            ROJO_UGR,
            ROJO_VITOR,
            apply_tfm_style,
            save_figure,
            style_axes,
        )
    except ImportError:
        print("matplotlib no disponible; omitiendo figura edad")
        return

    apply_tfm_style()
    years = sorted({a for a, _ in agg})
    colors = {
        "0-17": AZUL_CLARO,
        "18-29": AZUL_CENTENARIO,
        "30-44": ROJO_UGR,
        "45-59": ROJO_VITOR,
        "60+": GRIS_ALUMINIO,
        "Sin edad": "#B0B0B0",
    }
    # Excluir "Sin edad" del apilado principal si es residual; incluirlo
    bands_plot = [b for b in BAND_ORDER if b != "Sin edad"]
    bottoms = [0.0] * len(years)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for b in bands_plot:
        vals = [agg.get((y, b), 0) for y in years]
        ax.bar(years, vals, bottom=bottoms, label=b, color=colors[b], width=0.85)
        bottoms = [bottoms[i] + vals[i] for i in range(len(years))]
    ax.set_title("Personas desaparecidas y no localizadas por grupo de edad (RNPDNO, estatus 7)")
    ax.set_xlabel("Año")
    ax.set_ylabel("Personas")
    ax.legend(loc="upper left", ncol=3)
    style_axes(ax, grid_y=True)
    path = OUT_FIGURES / "serie_nacional_edad_2010_2024.png"
    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


def figura_edad_2024(agg: dict[tuple[int, str], int]) -> None:
    try:
        import matplotlib.pyplot as plt
        import sys

        sys.path.insert(0, str(ROOT / "analysis"))
        from plot_style import AZUL_CENTENARIO, ROJO_VITOR, apply_tfm_style, save_figure, style_axes
    except ImportError:
        return

    apply_tfm_style()
    bands = [b for b in BAND_ORDER if b != "Sin edad"]
    vals = [agg.get((2024, b), 0) for b in bands]
    total = sum(vals) or 1
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.barh(bands[::-1], vals[::-1], color=AZUL_CENTENARIO, height=0.65)
    for bar, v in zip(bars, vals[::-1]):
        ax.text(
            bar.get_width() + max(vals) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{v:,} ({100 * v / total:.1f}%)".replace(",", " "),
            va="center",
            fontsize=9,
            color=ROJO_VITOR if v == max(vals) else "#4D4D4D",
        )
    ax.set_title("Distribución por edad — 2024 (estatus 7)")
    ax.set_xlabel("Personas")
    style_axes(ax, grid_y=False, grid_x=True)
    path = OUT_FIGURES / "edad_nacional_2024.png"
    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


def main() -> None:
    if not PANEL_GEO.exists():
        raise SystemExit(f"Falta {PANEL_GEO}")
    rows = load_rows()
    agg = aggregate_national(rows)
    write_table(agg)
    figura_edad(agg)
    figura_edad_2024(agg)
    # Resumen 2024
    total_2024 = sum(agg.get((2024, b), 0) for b in BAND_ORDER)
    print(f"Total nacional 2024 (edad): {total_2024}")
    for b in BAND_ORDER:
        n = agg.get((2024, b), 0)
        print(f"  {b}: {n} ({100 * n / total_2024:.1f}%)" if total_2024 else f"  {b}: {n}")


if __name__ == "__main__":
    main()
