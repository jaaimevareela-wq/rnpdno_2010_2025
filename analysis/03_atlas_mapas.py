#!/usr/bin/env python3
"""Mapas estatales (INEGI) — atlas observado, predicho y símbolos proporcionales."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GEOJSON = ROOT / "data" / "external" / "geo" / "entidades_federativas_simplificado.geojson"
GEOJSON_FULL = ROOT / "data" / "external" / "geo" / "entidades_federativas.geojson"
PANEL = ROOT / "data" / "processed" / "panel_ml_estatal_2010_2024.csv"
PREDS = ROOT / "output" / "tables" / "ml_predicciones_test_2020_2024.csv"
OUT_FIGURES = ROOT / "output" / "figures"
OUT_TABLES = ROOT / "output" / "tables"

# Corrección perceptual de Flannery (1971): radio ∝ valor^0,5716 → área ∝ valor^1,1432
FLANNERY_RADIUS_EXP = 0.5716
FLANNERY_AREA_EXP = 2 * FLANNERY_RADIUS_EXP  # 1.1432

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
    for col in ("cve_ent", "CVE_ENT", "cvegeo", "CVEGEO"):
        if col in gdf.columns:
            gdf["cve_ent"] = gdf[col].astype(str).str.zfill(2)
            break
    if "cve_ent" not in gdf.columns:
        raise SystemExit(f"GeoJSON sin cve_ent. Columnas: {list(gdf.columns)}")
    gdf["cve_ent"] = gdf["cve_ent"].astype(str).str.zfill(2)
    return gdf


def _scaled_area(value: float, *, use_flannery: bool = True) -> float:
    """Área del símbolo en unidades proporcionales al valor (para `s` de scatter)."""
    if use_flannery:
        return value ** FLANNERY_AREA_EXP
    return value


def _format_estado(name: str) -> str:
    """Nombre completo en formato título (sin truncar)."""
    raw = str(name).strip()
    parts = raw.lower().split()
    small = {"de", "del", "la", "las", "los", "y", "e"}
    titled = [
        p if (i > 0 and p in small) else p.capitalize()
        for i, p in enumerate(parts)
    ]
    s = " ".join(titled)
    accents = {
        "Mexico": "México",
        "Michoacan": "Michoacán",
        "Queretaro": "Querétaro",
        "Yucatan": "Yucatán",
        "Nuevo Leon": "Nuevo León",
        "San Luis Potosi": "San Luis Potosí",
        "Leon": "León",
    }
    for plain, accented in accents.items():
        s = s.replace(plain, accented)
    return s


def _label_textprops(color: str, *, ha: str = "left", va: str = "center") -> dict:
    from matplotlib import patheffects as pe

    return {
        "fontsize": 7,
        "ha": ha,
        "va": va,
        "color": color,
        "fontweight": "bold",
        "path_effects": [pe.withStroke(linewidth=2.2, foreground="white")],
        "annotation_clip": False,
        "zorder": 5,
    }


def _scatter_radius_pts(size: float) -> float:
    return math.sqrt(size / math.pi)


def _annotate_states(
    ax,
    fig,
    labels_df,
    all_df,
    sizes: pd.Series,
    label_col: str,
    *,
    default_color: str,
    allow_skip: bool = False,
) -> list[tuple[str, bool]]:
    """Coloca etiquetas junto al círculo o con línea guía si hay colisión."""
    from matplotlib.transforms import Bbox

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    dpi_scale = fig.dpi / 72.0

    def _circle_bbox(x: float, y: float, size: float, pad: float = 2.0) -> Bbox:
        px, py = ax.transData.transform((x, y))
        r = _scatter_radius_pts(size) * dpi_scale + pad
        return Bbox.from_bounds(px - r, py - r, 2 * r, 2 * r)

    all_circles = [
        (row["_x"], row["_y"], float(sizes.loc[idx]), idx)
        for idx, row in all_df.iterrows()
    ]

    placed_text_bboxes: list[Bbox] = []
    results: list[tuple[str, bool]] = []

    def _candidates(r_pt: float) -> list[tuple[float, float, str, str, bool]]:
        gap = 3.0
        near = r_pt + gap
        far = r_pt + 22.0
        return [
            (near, 0, "left", "center", False),
            (-near, 0, "right", "center", False),
            (0, near, "center", "bottom", False),
            (0, -near, "center", "top", False),
            (far, 0, "left", "center", True),
            (-far, 0, "right", "center", True),
            (0, far, "center", "bottom", True),
            (0, -far, "center", "top", True),
            (far, far * 0.45, "left", "bottom", True),
            (-far, far * 0.45, "right", "bottom", True),
            (far, -far * 0.45, "left", "top", True),
            (-far, -far * 0.45, "right", "top", True),
        ]

    for idx, row in labels_df.iterrows():
        cx, cy = float(row["_x"]), float(row["_y"])
        size = float(sizes.loc[idx])
        r_pt = _scatter_radius_pts(size)
        name = _format_estado(str(row.get(label_col, "")))

        chosen = None
        for dx, dy, ha, va, needs_guide in _candidates(r_pt):
            props = _label_textprops(default_color, ha=ha, va=va)
            arrowprops = None
            if needs_guide:
                arrowprops = dict(
                    arrowstyle="-",
                    color=default_color,
                    lw=0.55,
                    shrinkA=0,
                    shrinkB=r_pt,
                )
            ann = ax.annotate(
                name,
                xy=(cx, cy),
                xytext=(dx, dy),
                textcoords="offset points",
                arrowprops=arrowprops,
                **props,
            )
            fig.canvas.draw()
            tbbox = ann.get_window_extent(renderer).expanded(1.08, 1.15)

            collides = any(tbbox.overlaps(pb) for pb in placed_text_bboxes)
            if not collides:
                for ox, oy, osize, oidx in all_circles:
                    if oidx == idx:
                        continue
                    if tbbox.overlaps(_circle_bbox(ox, oy, osize, pad=1.0)):
                        collides = True
                        break

            if not collides:
                chosen = (ann, needs_guide)
                placed_text_bboxes.append(tbbox)
                break
            ann.remove()

        if chosen is None:
            if allow_skip:
                continue
            ann = ax.annotate(
                name,
                xy=(cx, cy),
                xytext=(r_pt + 28, 0),
                textcoords="offset points",
                arrowprops=dict(
                    arrowstyle="-",
                    color=default_color,
                    lw=0.55,
                    shrinkA=0,
                    shrinkB=r_pt,
                ),
                **_label_textprops(default_color),
            )
            fig.canvas.draw()
            placed_text_bboxes.append(ann.get_window_extent(renderer).expanded(1.08, 1.15))
            results.append((name, True))
        else:
            results.append((name, chosen[1]))

    return results


def _verify_flannery_scaling() -> None:
    """Comprueba numéricamente el cociente de áreas 10:1 con corrección de Flannery."""
    v_big, v_small = 1000.0, 100.0
    area_big = _scaled_area(v_big, use_flannery=True)
    area_small = _scaled_area(v_small, use_flannery=True)
    ratio = area_big / area_small
    expected = 10 ** FLANNERY_AREA_EXP
    print(
        f"Verificación Flannery: área({int(v_big)})/área({int(v_small)}) = {ratio:.3f} "
        f"(esperado 10^{FLANNERY_AREA_EXP:.4f} ≈ {expected:.3f})"
    )


def _reference_values(max_val: float) -> list[float]:
    """Tres valores redondos representativos del rango (~máx, ~mitad, ~décima)."""
    if max_val <= 0:
        return [100.0, 50.0, 10.0]
    nice_steps = [1, 2, 5]
    magnitude = 10 ** math.floor(math.log10(max_val))
    v_max = magnitude
    for step in nice_steps:
        candidate = step * magnitude
        if candidate >= max_val * 0.85:
            v_max = candidate
            break
    else:
        v_max = 10 * magnitude
    v_mid = v_max / 2
    v_min = v_max / 10
    # Redondear a números redondos
    def _round_nice(v: float) -> float:
        if v >= 1000:
            return float(round(v / 500) * 500) if v >= 5000 else float(round(v / 250) * 250)
        if v >= 100:
            return float(round(v / 100) * 100)
        if v >= 10:
            return float(round(v / 10) * 10)
        return float(max(1, round(v)))

    return [_round_nice(v_max), _round_nice(v_mid), _round_nice(v_min)]


def _add_circle_legend(
    ax,
    ref_values: list[float],
    k: float,
    *,
    label: str,
    symbol_color: str,
    use_flannery: bool = True,
) -> None:
    """Leyenda de círculos alineados por la base, con separación mínima entre cifras."""
    from matplotlib.lines import Line2D
    from matplotlib.offsetbox import AnchoredOffsetbox, DrawingArea, HPacker, TextArea, VPacker
    from matplotlib.patches import Circle
    from matplotlib.text import Text as MplText

    MIN_LABEL_SEP = 12.0
    fontsize = 8

    sorted_vals = sorted(ref_values, reverse=True)
    radii = [
        math.sqrt(k * _scaled_area(v, use_flannery=use_flannery) / math.pi)
        for v in sorted_vals
    ]
    max_r = max(radii) if radii else 1.0

    pad_left = 6
    baseline = 10
    cx = pad_left + max_r
    label_x = cx + max_r + 16

    tops = [baseline + 2 * r for r in radii]
    top_anchor = baseline + 2 * max_r + 2
    label_ys = [top_anchor - i * MIN_LABEL_SEP for i in range(len(radii))]

    da_h = int(top_anchor + 12)
    da_w = int(label_x + 50)
    da = DrawingArea(da_w, da_h, clip=False)

    for val, r, top, ly in zip(sorted_vals, radii, tops, label_ys):
        cy = baseline + r
        da.add_artist(
            Circle(
                (cx, cy),
                r,
                facecolor=symbol_color,
                edgecolor="white",
                linewidth=0.9,
                alpha=0.72,
            )
        )
        anchor_x = cx + min(r, max_r * 0.35)
        anchor_y = top
        end_x = label_x - 4
        da.add_artist(
            Line2D(
                [anchor_x, end_x],
                [anchor_y, ly],
                color="#888888",
                linewidth=0.55,
            )
        )
        da.add_artist(
            MplText(label_x, ly, f"{int(val):,}".replace(",", "."), fontsize=fontsize, va="center", ha="left")
        )

    title = TextArea(f"{label}\n", textprops={"fontsize": 8, "fontweight": "bold"})
    legend_box = VPacker(children=[title, da], align="left", pad=0, sep=3)

    anchored = AnchoredOffsetbox(
        loc="lower left",
        child=legend_box,
        pad=0.4,
        frameon=True,
        bbox_to_anchor=(0.01, 0.01),
        bbox_transform=ax.transAxes,
        borderpad=0.6,
    )
    anchored.patch.set_facecolor("white")
    anchored.patch.set_alpha(0.92)
    anchored.patch.set_edgecolor("#CCCCCC")
    ax.add_artist(anchored)


def _plot_proportional_symbols(
    gdf,
    value_col: str,
    title: str,
    path: Path,
    *,
    label_col: str = "estado",
    top_n_labels: int = 4,
    legend_label: str = "Personas",
    symbol_color: str | None = None,
    use_flannery: bool = True,
    subtitle: str | None = None,
) -> None:
    """Mapa de círculos proporcionales (área ∝ valor) sobre fondo gris neutro."""
    import matplotlib.pyplot as plt

    from plot_style import (
        AZUL_CENTENARIO,
        GRIS_ALUMINIO,
        GRIS_PLATA,
        apply_tfm_style,
        save_figure,
    )

    if symbol_color is None:
        symbol_color = AZUL_CENTENARIO

    apply_tfm_style()
    fig, ax = plt.subplots(figsize=(10, 8))

    gdf.plot(ax=ax, color=GRIS_PLATA, edgecolor="white", linewidth=0.5)

    plot_df = gdf.dropna(subset=[value_col]).copy()
    plot_df["_rp"] = plot_df.geometry.apply(lambda g: g.representative_point())
    plot_df["_x"] = plot_df["_rp"].x
    plot_df["_y"] = plot_df["_rp"].y

    max_val = plot_df[value_col].max()
    ref_vals = _reference_values(max_val)
    max_scaled = _scaled_area(max_val, use_flannery=use_flannery)
    k = 900.0 / max_scaled if max_scaled > 0 else 1.0

    plot_df = plot_df.sort_values(value_col, ascending=False)
    sizes = pd.Series(
        k * plot_df[value_col].apply(lambda v: _scaled_area(v, use_flannery=use_flannery)).values,
        index=plot_df.index,
    )

    ax.scatter(
        plot_df["_x"],
        plot_df["_y"],
        s=sizes,
        c=symbol_color,
        alpha=0.72,
        edgecolors="white",
        linewidths=0.9,
        zorder=3,
    )

    top = plot_df.nlargest(top_n_labels, value_col)
    _annotate_states(ax, fig, top, plot_df, sizes, label_col, default_color=GRIS_ALUMINIO)

    _add_circle_legend(
        ax,
        ref_vals,
        k,
        label=legend_label,
        symbol_color=symbol_color,
        use_flannery=use_flannery,
    )

    ax.set_axis_off()
    ax.set_title(title, color=GRIS_ALUMINIO, fontweight="bold", pad=12)
    if subtitle:
        ax.text(
            0.5,
            1.01,
            subtitle,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=GRIS_ALUMINIO,
        )

    footer = (
        "Área del círculo proporcional al conteo, con corrección perceptual de Flannery; "
        "posición: punto representativo del polígono"
        if use_flannery
        else "Área del círculo proporcional al conteo; posición: punto representativo del polígono"
    )
    fig.text(0.5, 0.01, footer, ha="center", fontsize=7.5, color=GRIS_ALUMINIO)

    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


# Entidades a rotular en el mapa combinado tasa + conteo (2024)
COMBINED_LABEL_REQUIRED = {"ESTADO DE MEXICO", "ZACATECAS"}
COMBINED_LABEL_OPTIONAL = {"SONORA"}


def _plot_combined_rate_symbols(
    gdf,
    rate_col: str,
    count_col: str,
    title: str,
    path: Path,
    *,
    label_col: str = "estado",
) -> None:
    """Coroplético de tasa (fondo) + círculos proporcionales de conteo absoluto."""
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize

    from plot_style import (
        GRIS_ALUMINIO,
        GRIS_PLATA,
        ROJO_VITOR,
        apply_tfm_style,
        save_figure,
        sequential_cmap,
    )

    apply_tfm_style()
    fig, ax = plt.subplots(figsize=(10, 6.8))
    fig.subplots_adjust(top=0.80, bottom=0.07, left=0.02, right=0.84)

    cmap = sequential_cmap()
    gdf.plot(
        ax=ax,
        column=rate_col,
        cmap=cmap,
        edgecolor="white",
        linewidth=0.5,
        missing_kwds={"color": GRIS_PLATA},
        legend=False,
    )

    sm = ScalarMappable(norm=Normalize(vmin=gdf[rate_col].min(), vmax=gdf[rate_col].max()), cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.02)
    cbar.set_label("Tasa / 100k habitantes (color de fondo)", fontsize=9)

    plot_df = gdf.dropna(subset=[count_col]).copy()
    plot_df["_rp"] = plot_df.geometry.apply(lambda g: g.representative_point())
    plot_df["_x"] = plot_df["_rp"].x
    plot_df["_y"] = plot_df["_rp"].y

    max_val = plot_df[count_col].max()
    ref_vals = _reference_values(max_val)
    max_scaled = _scaled_area(max_val, use_flannery=True)
    k = 650.0 / max_scaled if max_scaled > 0 else 1.0

    plot_df = plot_df.sort_values(count_col, ascending=False)
    sizes = pd.Series(
        k * plot_df[count_col].apply(lambda v: _scaled_area(v, use_flannery=True)).values,
        index=plot_df.index,
    )

    ax.scatter(
        plot_df["_x"],
        plot_df["_y"],
        s=sizes,
        c=ROJO_VITOR,
        alpha=0.78,
        edgecolors="white",
        linewidths=0.9,
        zorder=3,
    )

    upper_names = plot_df[label_col].str.upper()
    required = plot_df[upper_names.isin(COMBINED_LABEL_REQUIRED)]
    optional = plot_df[upper_names.isin(COMBINED_LABEL_OPTIONAL)]

    _annotate_states(
        ax, fig, required, plot_df, sizes, label_col, default_color=GRIS_ALUMINIO
    )
    if not optional.empty:
        _annotate_states(
            ax,
            fig,
            optional,
            plot_df,
            sizes,
            label_col,
            default_color=GRIS_ALUMINIO,
            allow_skip=True,
        )

    _add_circle_legend(
        ax,
        ref_vals,
        k,
        label="Conteo absoluto (círculos)",
        symbol_color=ROJO_VITOR,
        use_flannery=True,
    )

    ax.set_axis_off()
    pos = ax.get_position()
    ax.set_position([pos.x0, 0.08, pos.width, 0.86])
    fig.text(
        0.5,
        0.975,
        title,
        ha="center",
        va="top",
        fontsize=12,
        fontweight="bold",
        color=GRIS_ALUMINIO,
    )
    fig.text(
        0.5,
        0.935,
        "El color indica la tasa; el tamaño del círculo, el conteo absoluto. "
        "Ambas lecturas pueden divergir (p. ej. volumen alto / tasa baja).",
        ha="center",
        va="top",
        fontsize=8.5,
        color=GRIS_ALUMINIO,
    )

    footer = (
        "Área del círculo proporcional al conteo, con corrección perceptual de Flannery; "
        "posición: punto representativo del polígono"
    )
    fig.text(0.5, 0.01, footer, ha="center", fontsize=7.5, color=GRIS_ALUMINIO)

    save_figure(fig, path)
    plt.close(fig)
    print(f"Escrito: {path}")


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

    from plot_style import (
        GRIS_ALUMINIO,
        RIESGO_ALTO,
        RIESGO_BAJO,
        RIESGO_NA,
        apply_tfm_style,
        save_figure,
        sequential_cmap,
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
            cmap=sequential_cmap(),
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
    gdf = load_geo()
    panel = pd.read_csv(PANEL)
    sub = panel[panel["anio"] == 2024][
        ["cve_estado", "estado", "tasa_desap_100k", "desap_count", "riesgo_cat"]
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
    _plot_combined_rate_symbols(
        merged,
        "tasa_desap_100k",
        "desap_count",
        "Tasa (color) y conteo absoluto (círculos) — 2024",
        OUT_FIGURES / "atlas_mapa_tasa_conteo_2024.png",
    )


def atlas_absolutos_acumulados() -> None:
    """Mapa de símbolos proporcionales — conteos absolutos acumulados 2010-2024."""
    gdf = load_geo()
    panel = pd.read_csv(PANEL)
    acum = (
        panel.groupby(["cve_estado", "estado"], as_index=False)["desap_count"]
        .sum()
        .rename(columns={"desap_count": "desap_count_acum"})
    )
    acum["cve_estado"] = acum["cve_estado"].astype(str).str.zfill(2)
    merged = gdf.merge(acum, left_on="cve_ent", right_on="cve_estado", how="left")

    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    table_path = OUT_TABLES / "ranking_estados_absolutos_2010_2024.csv"
    acum.sort_values("desap_count_acum", ascending=False).to_csv(
        table_path, index=False
    )
    print(f"Escrito: {table_path}")

    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    _plot_proportional_symbols(
        merged,
        "desap_count_acum",
        "Conteo absoluto acumulado de desapariciones/no localizaciones — 2010-2024",
        OUT_FIGURES / "atlas_mapa_absolutos_2010_2024.png",
        legend_label="Personas (acumulado)",
    )


def atlas_predicho_2024() -> None:
    gdf = load_geo()
    if not PREDS.exists():
        raise SystemExit(f"Falta {PREDS}. Ejecuta: python3 analysis/ml_panel.py")
    preds = pd.read_csv(PREDS)
    sub = preds[preds["anio"] == 2024].copy()
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

    from plot_style import sequential_cmap, verify_cmap_luminance_monotonic

    check = verify_cmap_luminance_monotonic(sequential_cmap())
    status = "MONÓTONA ✓" if check["monotonic"] else "NO monótona ✗"
    print(
        f"Comprobación luminancia sequential_cmap: {status} "
        f"(violaciones={check['violations']}, "
        f"L_inicio={check['luminance_start']:.4f}, L_fin={check['luminance_end']:.4f})"
    )
    _verify_flannery_scaling()

    atlas_observado_2024()
    atlas_absolutos_acumulados()
    atlas_predicho_2024()


if __name__ == "__main__":
    main()
