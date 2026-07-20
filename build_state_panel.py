#!/usr/bin/env python3
"""
Construye el panel estatal año × entidad para el TFM (ML).

Agrega RNPDNO estatus 7 desde panel_estatus7_2010_2025_geo.csv, calcula tasas,
variables de calidad de registro, categoría de riesgo binaria (Dalenius-Hodges, 2 estratos) y
fusiona fuentes externas (población, CONEVAL, SESNSP, institucional).

Uso:
  python3 build_state_panel.py
  python3 build_state_panel.py --desde 2010 --hasta 2024
  python3 build_state_panel.py --generar-poblacion  # interpola desde censos 2010/2020
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PANEL_GEO = ROOT / "data" / "panel" / "panel_estatus7_2010_2025_geo.csv"
EXTERNAL = ROOT / "data" / "external"
PROCESSED = ROOT / "data" / "processed"
MANUAL = ROOT / "data" / "manual"

POBLACION_PATH = EXTERNAL / "poblacion_estatal.csv"
CONEVAL_PATH = EXTERNAL / "coneval_estatal.csv"
SESNSP_PATH = EXTERNAL / "sesnsp_victimas_estatal.csv"
INSTITUCIONAL_PATH = MANUAL / "comision_busqueda.csv"
INSTITUCIONAL_TITULAR_PATH = MANUAL / "comision_busqueda_titular.csv"
OUTPUT_PATH = PROCESSED / "panel_ml_estatal_2010_2024.csv"
OUTPUT_SENS_PATH = PROCESSED / "panel_ml_estatal_2010_2024_sin_sentinels.csv"

SENTINEL_MUN = {"998", "999"}
UNKNOWN_STATE_ID = "33"
RANGO_TOTAL = "total"

# Población intercensal (INEGI Censo 2010 y 2020, conteos oficiales)
POB_CENSO: dict[str, dict[int, int]] = {
    "01": {2010: 1_184_996, 2020: 1_425_607},
    "02": {2010: 3_155_070, 2020: 3_769_020},
    "03": {2010: 637_026, 2020: 798_447},
    "04": {2010: 822_441, 2020: 928_363},
    "05": {2010: 2_748_391, 2020: 3_146_771},
    "06": {2010: 650_555, 2020: 731_391},
    "07": {2010: 4_796_580, 2020: 5_543_828},
    "08": {2010: 3_406_465, 2020: 3_741_869},
    "09": {2010: 8_851_080, 2020: 9_209_944},
    "10": {2010: 1_632_934, 2020: 1_832_650},
    "11": {2010: 5_486_372, 2020: 6_166_934},
    "12": {2010: 3_388_769, 2020: 3_540_685},
    "13": {2010: 2_665_018, 2020: 3_082_841},
    "14": {2010: 7_350_682, 2020: 8_348_151},
    "15": {2010: 15_175_862, 2020: 16_992_418},
    "16": {2010: 4_351_037, 2020: 4_748_846},
    "17": {2010: 1_777_227, 2020: 1_971_520},
    "18": {2010: 1_084_979, 2020: 1_235_456},
    "19": {2010: 4_653_458, 2020: 5_784_442},
    "20": {2010: 3_801_962, 2020: 4_132_148},
    "21": {2010: 5_779_829, 2020: 6_583_278},
    "22": {2010: 1_827_937, 2020: 2_368_467},
    "23": {2010: 1_325_578, 2020: 1_857_985},
    "24": {2010: 2_585_518, 2020: 2_822_255},
    "25": {2010: 2_767_761, 2020: 3_026_943},
    "26": {2010: 2_662_480, 2020: 2_944_840},
    "27": {2010: 2_238_603, 2020: 2_402_598},
    "28": {2010: 3_268_554, 2020: 3_527_735},
    "29": {2010: 1_169_936, 2020: 1_342_977},
    "30": {2010: 7_643_194, 2020: 8_062_579},
    "31": {2010: 1_955_577, 2020: 2_320_898},
    "32": {2010: 1_490_668, 2020: 1_622_138},
}

STATE_NAMES: dict[str, str] = {
    "01": "AGUASCALIENTES",
    "02": "BAJA CALIFORNIA",
    "03": "BAJA CALIFORNIA SUR",
    "04": "CAMPECHE",
    "05": "COAHUILA",
    "06": "COLIMA",
    "07": "CHIAPAS",
    "08": "CHIHUAHUA",
    "09": "CIUDAD DE MEXICO",
    "10": "DURANGO",
    "11": "GUANAJUATO",
    "12": "GUERRERO",
    "13": "HIDALGO",
    "14": "JALISCO",
    "15": "ESTADO DE MEXICO",
    "16": "MICHOACAN",
    "17": "MORELOS",
    "18": "NAYARIT",
    "19": "NUEVO LEON",
    "20": "OAXACA",
    "21": "PUEBLA",
    "22": "QUERETARO",
    "23": "QUINTANA ROO",
    "24": "SAN LUIS POTOSI",
    "25": "SINALOA",
    "26": "SONORA",
    "27": "TABASCO",
    "28": "TAMAULIPAS",
    "29": "TLAXCALA",
    "30": "VERACRUZ",
    "31": "YUCATAN",
    "32": "ZACATECAS",
}


def interpolate_poblacion(cve: str, anio: int) -> int:
    pts = POB_CENSO[cve]
    years = sorted(pts)
    if anio <= years[0]:
        return pts[years[0]]
    if anio >= years[-1]:
        # extrapolación lineal 2020→2024 con la tasa 2010–2020
        y0, y1 = years[0], years[-1]
        rate = (pts[y1] - pts[y0]) / (y1 - y0)
        return max(1, int(round(pts[y1] + rate * (anio - y1))))
    y0, y1 = years[0], years[-1]
    frac = (anio - y0) / (y1 - y0)
    return int(round(pts[y0] + frac * (pts[y1] - pts[y0])))


def write_poblacion_template(path: Path, desde: int, hasta: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cve_estado", "estado", "anio", "poblacion", "fuente"])
        for cve in sorted(POB_CENSO):
            for anio in range(desde, hasta + 1):
                w.writerow(
                    [
                        cve,
                        STATE_NAMES[cve],
                        anio,
                        interpolate_poblacion(cve, anio),
                        "INEGI Censo 2010/2020 interpolado",
                    ]
                )


def read_csv_keyed(
    path: Path,
    key_cols: tuple[str, ...],
    value_cols: tuple[str, ...] | None = None,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = tuple(row[k] for k in key_cols)
            if value_cols:
                out[key] = {c: row.get(c, "") for c in value_cols}
            else:
                out[key] = dict(row)
    return out


def dalenius_hodges(values: list[float], n_strata: int = 3) -> list[float]:
    """Umbrales superiores para n_strata clases (método Dalenius-Hodges)."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return []
    k = max(2, int(round(math.log10(n))))
    if k < 2:
        k = 2
    # intervalos sobre el rango
    xmin, xmax = xs[0], xs[-1]
    if xmin == xmax:
        return [xmax]
    step = (xmax - xmin) / k
    bounds = [xmin + step * (i + 1) for i in range(k)]
    # acumular sqrt de frecuencias por intervalo
    freq = [0] * k
    for v in xs:
        idx = min(k - 1, int((v - xmin) / step) if step else 0)
        freq[idx] += 1
    sqrt_cum = []
    s = 0
    for f in freq:
        s += math.sqrt(f)
        sqrt_cum.append(s)
    total_sqrt = sqrt_cum[-1] if sqrt_cum else 1
    target = total_sqrt / n_strata
    cuts: list[float] = []
    for i in range(1, n_strata):
        goal = target * i
        # valor del intervalo más cercano al goal acumulado
        best_j = 0
        best_d = float("inf")
        for j, sc in enumerate(sqrt_cum):
            d = abs(sc - goal)
            if d < best_d:
                best_d = d
                best_j = j
        cuts.append(bounds[best_j])
    return sorted(set(cuts))


def assign_stratum(value: float, cuts: list[float]) -> str:
    """Asigna etiqueta según cortes Dalenius-Hodges (2 clases: bajo/alto)."""
    labels = ["bajo", "alto"] if len(cuts) <= 1 else ["bajo", "medio", "alto"]
    for i, cut in enumerate(cuts):
        if value <= cut:
            return labels[i]
    return labels[-1]


def aggregate_rnpdno(
    panel_path: Path,
    desde: int,
    hasta: int,
    exclude_sentinels: bool = False,
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    agg: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {
            "desap_count": 0,
            "desap_hombres": 0,
            "desap_mujeres": 0,
            "sin_municipio": 0,
            "total_filas": 0,
        }
    )

    with panel_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["estatus_id"] != "7":
                continue
            if row["id_estado"] == UNKNOWN_STATE_ID:
                continue
            if row["rango_edad"] == RANGO_TOTAL:
                continue
            anio = int(row["anio"])
            if anio < desde or anio > hasta:
                continue
            cve = row["cve_estado"].zfill(2) if row["cve_estado"] else ""
            if not cve or cve == "99":
                # usar id_estado como respaldo
                cve = str(int(row["id_estado"])).zfill(2)
            personas = int(row["personas"])
            key = (cve, str(anio))
            bucket = agg[key]
            is_sentinel = row["cve_mun"] in SENTINEL_MUN or row["match_type"].startswith(
                "sentinel"
            )
            if exclude_sentinels and is_sentinel:
                continue
            bucket["desap_count"] += personas
            bucket["total_filas"] += 1
            if is_sentinel:
                bucket["sin_municipio"] += personas
            if row["sexo"] == "hombre":
                bucket["desap_hombres"] += personas
            elif row["sexo"] == "mujer":
                bucket["desap_mujeres"] += personas

    for cve in sorted(STATE_NAMES):
        for anio in range(desde, hasta + 1):
            b = agg.get((cve, str(anio)), None)
            if b is None:
                b = {
                    "desap_count": 0,
                    "desap_hombres": 0,
                    "desap_mujeres": 0,
                    "sin_municipio": 0,
                    "total_filas": 0,
                }
            total = b["desap_count"]
            pct_sin = (100.0 * b["sin_municipio"] / total) if total else 0.0
            pct_h = (100.0 * b["desap_hombres"] / total) if total else 0.0
            rows_out.append(
                {
                    "cve_estado": cve,
                    "estado": STATE_NAMES[cve],
                    "anio": anio,
                    "desap_count": total,
                    "desap_hombres": b["desap_hombres"],
                    "desap_mujeres": b["desap_mujeres"],
                    "pct_hombres": round(pct_h, 2),
                    "pct_sin_municipio": round(pct_sin, 2),
                }
            )
    return rows_out


def merge_external(
    base: list[dict[str, Any]],
    poblacion: dict[tuple[str, str], dict[str, Any]],
    coneval: dict[tuple[str, str], dict[str, Any]],
    sesnsp: dict[tuple[str, str], dict[str, Any]],
    institucional: dict[tuple[str, str], dict[str, Any]],
    institucional_titular: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for row in base:
        cve = row["cve_estado"]
        anio = str(row["anio"])
        key = (cve, anio)
        out = dict(row)
        pob_row = poblacion.get(key, {})
        pob = int(pob_row["poblacion"]) if pob_row.get("poblacion") else 0
        if pob <= 0:
            pob = interpolate_poblacion(cve, int(anio))
        out["poblacion"] = pob
        out["tasa_desap_100k"] = round(
            100_000 * row["desap_count"] / pob, 4
        )
        out["log_poblacion"] = round(math.log(pob), 4)

        for src, mapping in (
            (coneval, ("pobreza_pct", "pobreza_ext_pct", "carencias_pct", "gini")),
            (
                sesnsp,
                (
                    "tasa_hom_doloso",
                    "tasa_secuestro",
                    "tasa_feminicidio",
                    "tasa_extorsion",
                ),
            ),
            (institucional, ("comision_busqueda",)),
            (institucional_titular, ("comision_busqueda_titular",)),
        ):
            data = src.get(key, {})
            for col in mapping:
                out[col] = data.get(col, "")

        merged.append(out)
    return merged


def apply_riesgo(merged: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[float]]:
    tasas = [r["tasa_desap_100k"] for r in merged]
    cuts = dalenius_hodges(tasas, n_strata=2)
    for row in merged:
        row["riesgo_cat"] = assign_stratum(row["tasa_desap_100k"], cuts)
        row["log_tasa_desap"] = round(
            math.log(row["tasa_desap_100k"] + 0.1), 4
        )
    return merged, cuts


def write_panel(path: Path, rows: list[dict[str, Any]], cuts: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cve_estado",
        "estado",
        "anio",
        "desap_count",
        "desap_hombres",
        "desap_mujeres",
        "pct_hombres",
        "pct_sin_municipio",
        "poblacion",
        "tasa_desap_100k",
        "log_tasa_desap",
        "riesgo_cat",
        "pobreza_pct",
        "pobreza_ext_pct",
        "carencias_pct",
        "gini",
        "tasa_hom_doloso",
        "tasa_secuestro",
        "tasa_feminicidio",
        "tasa_extorsion",
        "comision_busqueda",
        "comision_busqueda_titular",
        "log_poblacion",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    meta = path.with_suffix(".meta.txt")
    meta.write_text(
        f"filas={len(rows)}\n"
        f"umbrales_dalenius_hodges={cuts}\n"
        f"clases_riesgo=bajo,alto\n"
        f"estrata_dalenius_hodges=2\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Panel estatal ML para TFM")
    parser.add_argument("--entrada", type=Path, default=PANEL_GEO)
    parser.add_argument("--desde", type=int, default=2010)
    parser.add_argument("--hasta", type=int, default=2024)
    parser.add_argument("--salida", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--generar-poblacion",
        action="store_true",
        help="Escribe data/external/poblacion_estatal.csv interpolada",
    )
    args = parser.parse_args()

    if args.generar_poblacion:
        write_poblacion_template(POBLACION_PATH, args.desde, args.hasta)
        print(f"Población generada: {POBLACION_PATH}")

    if not POBLACION_PATH.exists():
        write_poblacion_template(POBLACION_PATH, args.desde, args.hasta)
        print(f"Población creada (primera vez): {POBLACION_PATH}")

    poblacion = read_csv_keyed(POBLACION_PATH, ("cve_estado", "anio"))
    coneval = read_csv_keyed(CONEVAL_PATH, ("cve_estado", "anio"))
    sesnsp = read_csv_keyed(SESNSP_PATH, ("cve_estado", "anio"))
    institucional = read_csv_keyed(INSTITUCIONAL_PATH, ("cve_estado", "anio"))
    institucional_titular = read_csv_keyed(
        INSTITUCIONAL_TITULAR_PATH, ("cve_estado", "anio")
    )

    base = aggregate_rnpdno(args.entrada, args.desde, args.hasta)
    merged = merge_external(
        base, poblacion, coneval, sesnsp, institucional, institucional_titular
    )
    merged, cuts = apply_riesgo(merged)
    write_panel(args.salida, merged, cuts)

    base_s = aggregate_rnpdno(
        args.entrada, args.desde, args.hasta, exclude_sentinels=True
    )
    merged_s = merge_external(
        base_s, poblacion, coneval, sesnsp, institucional, institucional_titular
    )
    merged_s, cuts_s = apply_riesgo(merged_s)
    write_panel(OUTPUT_SENS_PATH, merged_s, cuts_s)

    print(f"Panel ML: {args.salida} ({len(merged)} filas)")
    print(f"Sensibilidad sin sentinels: {OUTPUT_SENS_PATH} ({len(merged_s)} filas)")
    print(f"Umbrales Dalenius-Hodges (tasa/100k): {cuts}")
    if not coneval:
        print("Nota: sin CONEVAL — rellena data/external/coneval_estatal.csv")
    if not sesnsp:
        print("Nota: sin SESNSP — rellena data/external/sesnsp_victimas_estatal.csv")
    if not institucional:
        print("Nota: sin institucional — rellena data/manual/comision_busqueda.csv")
    if not institucional_titular:
        print(
            "Nota: sin titular — rellena data/manual/comision_busqueda_titular.csv "
            "(catálogo en comision_busqueda_titular_catalogo.csv)"
        )


if __name__ == "__main__":
    main()
