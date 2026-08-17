#!/usr/bin/env python3
"""Estilo visual compartido para figuras del TFM (identidad UGR + USAL).

Paleta pública:
- USAL Rojo Vítor #D22020, Azul Centenario #385E9D, Gris Aluminio #4D4D4D, Gris Plata #EAEAEA
- UGR Pantone 711 #CB2C30
"""

from __future__ import annotations

from pathlib import Path

# Colores institucionales
ROJO_VITOR = "#D22020"
ROJO_UGR = "#CB2C30"
AZUL_CENTENARIO = "#385E9D"
AZUL_CLARO = "#6B8FC2"
GRIS_ALUMINIO = "#4D4D4D"
GRIS_PLATA = "#EAEAEA"
GRIS_EJE = "#8A8A8A"
BLANCO = "#FFFFFF"

# Semántica de riesgo (atlas / categorías)
RIESGO_BAJO = AZUL_CENTENARIO
RIESGO_ALTO = ROJO_VITOR
RIESGO_NA = "#9E9E9E"

# Series
SERIE_PRINCIPAL = ROJO_VITOR
SERIE_HOMBRES = AZUL_CENTENARIO
SERIE_MUJERES = ROJO_UGR
BARRAS_IMPORTANCIA = AZUL_CENTENARIO
BARRAS_SHAP = ROJO_VITOR

# Okabe-Ito — accesible (daltonismo + escala de grises)
OKABE_BLUE = "#0072B2"
OKABE_SKY = "#56B4E9"
OKABE_VERMILLION = "#D55E00"
OKABE_ORANGE = "#E69F00"
OKABE_GREEN = "#009E73"
OKABE_GRAY = "#999999"

# Bandas de edad: contraste suficiente entre 30-44 y 45-59
EDAD_BAND_COLORS = {
    "0-17": OKABE_SKY,
    "18-29": OKABE_BLUE,
    "30-44": OKABE_VERMILLION,
    "45-59": OKABE_ORANGE,
    "60+": OKABE_GRAY,
    "Sin edad": "#B0B0B0",
}

DPI = 200
FACECOLOR = BLANCO
# Acento editorial (booktabs / pies): mismo azul institucional
EDITORIAL_RULE = AZUL_CENTENARIO


def apply_tfm_style() -> None:
    """Configura matplotlib rcParams con tipografía y colores del TFM.

    Criterio visual alineado con tablas tipo booktabs: tipografía sans limpia,
    sin marco superior/derecho, rejilla suave y acento azul Centenario.
    """
    import matplotlib as mpl
    from matplotlib import pyplot as plt

    mpl.rcParams.update(
        {
            "figure.facecolor": FACECOLOR,
            "axes.facecolor": FACECOLOR,
            "savefig.facecolor": FACECOLOR,
            "savefig.dpi": DPI,
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica Neue", "Lato", "DejaVu Sans"],
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.labelcolor": GRIS_ALUMINIO,
            "axes.edgecolor": AZUL_CENTENARIO,
            "axes.linewidth": 0.9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titlecolor": GRIS_ALUMINIO,
            "xtick.color": GRIS_ALUMINIO,
            "ytick.color": GRIS_ALUMINIO,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "text.color": GRIS_ALUMINIO,
            "grid.color": GRIS_PLATA,
            "grid.linewidth": 0.6,
            "grid.alpha": 0.9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "figure.dpi": 120,
            "axes.grid": False,
        }
    )
    plt.style.use("default")
    # Reaplicar tras style.use
    mpl.rcParams.update(
        {
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": AZUL_CENTENARIO,
            "axes.linewidth": 0.9,
            "axes.labelcolor": GRIS_ALUMINIO,
            "axes.titlecolor": GRIS_ALUMINIO,
            "xtick.color": GRIS_ALUMINIO,
            "ytick.color": GRIS_ALUMINIO,
            "grid.color": GRIS_PLATA,
            "font.sans-serif": ["Arial", "Helvetica Neue", "Lato", "DejaVu Sans"],
        }
    )


def risk_cmap():
    """Colormap continuo blanco → azul → rojo (legacy; preferir sequential_cmap)."""
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "tfm_risk",
        [BLANCO, "#D6E0F0", AZUL_CLARO, AZUL_CENTENARIO, "#A33A3A", ROJO_VITOR],
        N=256,
    )


def sequential_cmap():
    """Rampa secuencial monótona en luminosidad (blanco → azul centenario oscuro).

    Adecuada para magnitudes continuas (tasas, conteos en heatmap). Segura para
    daltonismo al usar un solo tono azul institucional con luminancia decreciente.
    """
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "tfm_sequential",
        [BLANCO, "#F0F4FA", "#D6E0F0", "#A8BDD9", AZUL_CLARO, AZUL_CENTENARIO, "#243D66"],
        N=256,
    )


def relative_luminance(hex_color: str) -> float:
    """Luminancia relativa WCAG 2.x de un color hex."""
    from matplotlib import colors as mcolors

    r, g, b = mcolors.to_rgb(hex_color)

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = (_lin(c) for c in (r, g, b))
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def verify_cmap_luminance_monotonic(cmap, n: int = 256) -> dict:
    """Comprueba que la luminancia de *cmap* decrece monótonamente."""
    from matplotlib import colors as mcolors
    import numpy as np

    samples = [cmap(i / (n - 1)) for i in range(n)]
    luminances = [relative_luminance(mcolors.to_hex(c)) for c in samples]
    diffs = np.diff(luminances)
    violations = int(np.sum(diffs > 1e-9))
    return {
        "monotonic": violations == 0,
        "n_samples": n,
        "luminance_start": luminances[0],
        "luminance_end": luminances[-1],
        "max_increase": float(np.max(diffs)) if len(diffs) else 0.0,
        "violations": violations,
    }


def confusion_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        "tfm_cm",
        [BLANCO, "#C5D4EB", AZUL_CENTENARIO],
        N=256,
    )


def style_axes(ax, *, grid_y: bool = True, grid_x: bool = False) -> None:
    ax.set_facecolor(FACECOLOR)
    if grid_y:
        ax.yaxis.grid(True, linestyle="-", alpha=0.85, linewidth=0.6, color=GRIS_PLATA)
        ax.set_axisbelow(True)
    if grid_x:
        ax.xaxis.grid(True, linestyle="-", alpha=0.85, linewidth=0.6, color=GRIS_PLATA)
        ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    # Ejes con acento editorial (equivalente a la regla azul de las tablas)
    ax.spines["left"].set_color(AZUL_CENTENARIO)
    ax.spines["bottom"].set_color(AZUL_CENTENARIO)
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)


def save_figure(fig, path: Path, *, dpi: int = DPI) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=FACECOLOR, edgecolor="none")


def make_logo_placeholders(out_dir: Path) -> tuple[Path, Path]:
    """Genera PNGs hueco para pegar escudos oficiales encima."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    specs = [
        ("logo_ugr_placeholder.png", "Logo UGR", ROJO_UGR, "Pegar escudo / marca\nUniversidad de Granada"),
        ("logo_usal_placeholder.png", "Logo USAL", ROJO_VITOR, "Pegar escudo / marca\nUniversidad de Salamanca"),
    ]
    for fname, title, color, hint in specs:
        fig, ax = plt.subplots(figsize=(2.8, 2.2))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        fig.patch.set_facecolor(FACECOLOR)
        box = FancyBboxPatch(
            (0.05, 0.05),
            0.9,
            0.9,
            boxstyle="round,pad=0.02,rounding_size=0.04",
            linewidth=1.6,
            edgecolor=color,
            facecolor=GRIS_PLATA,
            linestyle="--",
        )
        ax.add_patch(box)
        ax.text(0.5, 0.62, title, ha="center", va="center", fontsize=13, fontweight="bold", color=color)
        ax.text(0.5, 0.32, hint, ha="center", va="center", fontsize=8, color=GRIS_ALUMINIO)
        path = out_dir / fname
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=FACECOLOR)
        plt.close(fig)
        paths.append(path)
    return paths[0], paths[1]
