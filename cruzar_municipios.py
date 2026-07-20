#!/usr/bin/env python3
"""
Cruza municipios del RNPDNO con el catálogo AGEEML (INEGI).

Corrige casos en los que el municipio no pertenece al estado reportado
por el dashboard, asigna CVEGEO / CVE_ENT / CVE_MUN y deja un reporte
de calidad.

Uso:
  python3 cruzar_municipios.py
  python3 cruzar_municipios.py --entrada data/por_municipio_estatus7_2010_2025.csv
  python3 cruzar_municipios.py --descargar-catalogo
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
EXTERNAL = ROOT / "data" / "external"
MANUAL = ROOT / "data" / "manual"
PROCESSED = ROOT / "data" / "processed"
CATALOG_PATH = EXTERNAL / "ageeml_catalog.csv"
INEGI_MGEE = "https://gaia.inegi.org.mx/wscatgeo/v2/mgee/"
INEGI_MGEM = "https://gaia.inegi.org.mx/wscatgeo/v2/mgem/{ent}"

_ABBREV = [
    (r"\bdr\b", "doctor"),
    (r"\bgral\b", "general"),
    (r"\bcd\b", "ciudad"),
    (r"\bsta\b", "santa"),
    (r"\bsto\b", "santo"),
    (r"\bmto\b", "maestro"),
    (r"\bprof\b", "profesor"),
    (r"\bing\b", "ingeniero"),
    (r"\blic\b", "licenciado"),
]

SENTINEL_UNKNOWN_STATE = "99998"
SENTINEL_NO_MUN = "998"
SENTINEL_UNKNOWN_MUN = "999"

UNKNOWN_PATTERNS = (
    "se desconoce",
    "sin municipio de referencia",
    "sin municipio",
    "no especificado",
    "no identificado",
    "desconoce",
)


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    if not text or text.lower() == "nan":
        return ""
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r" +", " ", text).strip()


def normalize_aggressive(text: Any) -> str:
    text = normalize_text(text)
    if not text:
        return text
    for pattern, expansion in _ABBREV:
        text = re.sub(pattern, expansion, text)
    text = re.sub(r"\bde\b", " ", text)
    return re.sub(r" +", " ", text).strip()


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def descargar_catalogo(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    print("Descargando estados INEGI…")
    estados = {e["cve_ent"]: e["nomgeo"] for e in http_json(INEGI_MGEE)["datos"]}
    rows: list[dict[str, str]] = []
    for ent in sorted(estados):
        print(f"  municipios {ent} {estados[ent]}")
        payload = http_json(INEGI_MGEM.format(ent=ent))
        for m in payload["datos"]:
            rows.append(
                {
                    "CVEGEO": m["cvegeo"],
                    "CVE_ENT": m["cve_ent"],
                    "NOM_ENT": estados[ent],
                    "CVE_MUN": m["cve_mun"],
                    "NOM_MUN": m["nomgeo"],
                }
            )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["CVEGEO", "CVE_ENT", "NOM_ENT", "CVE_MUN", "NOM_MUN"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Catálogo guardado: {path} ({len(rows)} municipios)")
    return rows


def cargar_catalogo(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size < 100:
        return descargar_catalogo(path)
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or "CVEGEO" not in rows[0]:
        return descargar_catalogo(path)
    print(f"Catálogo AGEEML: {path} ({len(rows)} municipios)")
    return rows


def load_csv_dict(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_ref(catalog: list[dict[str, str]]) -> dict[str, Any]:
    by_state_simple: dict[tuple[str, str], dict[str, str]] = {}
    by_state_agg: dict[tuple[str, str], dict[str, str]] = {}
    by_name_simple: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name_agg: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_cvegeo: dict[str, dict[str, str]] = {}
    agg_counts: Counter[tuple[str, str]] = Counter()

    enriched: list[dict[str, str]] = []
    for row in catalog:
        item = {
            "cvegeo": row["CVEGEO"].zfill(5),
            "cve_estado": row["CVE_ENT"].zfill(2),
            "cve_mun": row["CVE_MUN"].zfill(3),
            "estado_inegi": row["NOM_ENT"].strip(),
            "municipio_inegi": row["NOM_MUN"].strip(),
            "municipio_norm": normalize_text(row["NOM_MUN"]),
            "municipio_agg": normalize_aggressive(row["NOM_MUN"]),
            "estado_norm": normalize_text(row["NOM_ENT"]),
        }
        enriched.append(item)
        by_cvegeo[item["cvegeo"]] = item
        by_state_simple[(item["cve_estado"], item["municipio_norm"])] = item
        agg_counts[(item["cve_estado"], item["municipio_agg"])] += 1
        by_name_simple[item["municipio_norm"]].append(item)
        by_name_agg[item["municipio_agg"]].append(item)

    for item in enriched:
        key = (item["cve_estado"], item["municipio_agg"])
        if agg_counts[key] == 1:
            by_state_agg[key] = item

    return {
        "by_state_simple": by_state_simple,
        "by_state_agg": by_state_agg,
        "by_name_simple": by_name_simple,
        "by_name_agg": by_name_agg,
        "by_cvegeo": by_cvegeo,
    }


def load_manuals(ref: dict[str, Any]) -> tuple[dict, dict]:
    overrides: dict[tuple[str, str], dict[str, str]] = {}
    for row in load_csv_dict(MANUAL / "geo_overrides.csv"):
        cvegeo = row["cvegeo"].zfill(5)
        geo = ref["by_cvegeo"].get(cvegeo)
        if not geo:
            print(f"  aviso: override sin CVEGEO en catálogo: {cvegeo} ({row['raw_municipio']})")
            continue
        key = (str(row["raw_id_estado"]).zfill(2), normalize_text(row["raw_municipio"]))
        overrides[key] = geo

    corrections: dict[tuple[str, str], dict[str, str]] = {}
    for row in load_csv_dict(MANUAL / "geo_state_corrections.csv"):
        cvegeo = f"{str(row['target_cve_estado']).zfill(2)}{str(row['target_cve_mun']).zfill(3)}"
        geo = ref["by_cvegeo"].get(cvegeo)
        if not geo:
            print(f"  aviso: corrección sin CVEGEO en catálogo: {cvegeo}")
            continue
        key = (
            str(row["source_id_estado"]).zfill(2),
            normalize_text(row["raw_municipio"]),
        )
        corrections[key] = geo
    return overrides, corrections


def is_unknown_muni(name_norm: str) -> bool:
    return any(p in name_norm for p in UNKNOWN_PATTERNS)


def match_row(
    row: dict[str, str],
    ref: dict[str, Any],
    overrides: dict,
    corrections: dict,
) -> dict[str, Any]:
    id_estado = int(row["id_estado"])
    cve_raw = None if id_estado == 33 else f"{id_estado:02d}"
    mun_raw = row["municipio"].strip()
    mun_norm = normalize_text(mun_raw)
    mun_agg = normalize_aggressive(mun_raw)
    key = (cve_raw or "33", mun_norm)

    out = {
        **row,
        "municipio_norm": mun_norm,
        "cve_estado_raw": cve_raw or "",
        "cvegeo": "",
        "cve_estado": "",
        "cve_mun": "",
        "estado_inegi": "",
        "municipio_inegi": "",
        "estado_corregido": "",
        "match_type": "unmatched",
    }

    if is_unknown_muni(mun_norm):
        if cve_raw:
            sent = SENTINEL_UNKNOWN_MUN if "desconoce" in mun_norm else SENTINEL_NO_MUN
            out.update(
                {
                    "cvegeo": f"{cve_raw}{sent}",
                    "cve_estado": cve_raw,
                    "cve_mun": sent,
                    "estado_inegi": row["estado"],
                    "municipio_inegi": mun_raw,
                    "match_type": "sentinel",
                }
            )
        else:
            out.update(
                {
                    "cvegeo": SENTINEL_UNKNOWN_STATE,
                    "cve_estado": "99",
                    "cve_mun": SENTINEL_UNKNOWN_MUN,
                    "estado_inegi": row["estado"],
                    "municipio_inegi": mun_raw,
                    "match_type": "sentinel_unknown_state",
                }
            )
        return out

    geo = overrides.get(key) or corrections.get(key)
    match_type = None
    if geo and key in overrides:
        match_type = "override"
    elif geo and key in corrections:
        match_type = "state_correction"

    if not geo and cve_raw:
        geo = ref["by_state_simple"].get((cve_raw, mun_norm))
        if geo:
            match_type = "simple"
        else:
            geo = ref["by_state_agg"].get((cve_raw, mun_agg))
            if geo:
                match_type = "aggressive"

    # Único a nivel nacional: corrige estado erróneo del RNPDNO
    if not geo:
        candidates = ref["by_name_simple"].get(mun_norm, [])
        if len(candidates) == 1:
            geo = candidates[0]
            match_type = "unique_nationwide"
        else:
            candidates = ref["by_name_agg"].get(mun_agg, [])
            if len(candidates) == 1:
                geo = candidates[0]
                match_type = "unique_nationwide_agg"

    if geo:
        estado_corregido = (
            "si"
            if cve_raw and geo["cve_estado"] != cve_raw
            else ("si" if not cve_raw else "no")
        )
        if match_type in ("simple", "aggressive", "override") and cve_raw == geo["cve_estado"]:
            estado_corregido = "no"
        if match_type == "override" and cve_raw and geo["cve_estado"] != cve_raw:
            estado_corregido = "si"
        out.update(
            {
                "cvegeo": geo["cvegeo"],
                "cve_estado": geo["cve_estado"],
                "cve_mun": geo["cve_mun"],
                "estado_inegi": geo["estado_inegi"],
                "municipio_inegi": geo["municipio_inegi"],
                "estado_corregido": estado_corregido,
                "match_type": match_type or "matched",
            }
        )
        return out

    if not cve_raw:
        out["match_type"] = "unknown_state"
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Guardado {path} ({len(rows)} filas)")


def cruzar(entrada: Path, salida: Path, reporte: Path) -> int:
    catalog = cargar_catalogo()
    ref = build_ref(catalog)
    overrides, corrections = load_manuals(ref)
    print(f"Overrides: {len(overrides)} | Correcciones de estado: {len(corrections)}")

    with entrada.open(encoding="utf-8") as fh:
        raw_rows = list(csv.DictReader(fh))
    print(f"Entrada: {entrada} ({len(raw_rows)} filas)")

    matched = [match_row(r, ref, overrides, corrections) for r in raw_rows]
    counts = Counter(r["match_type"] for r in matched)
    corregidos = sum(1 for r in matched if r.get("estado_corregido") == "si")
    personas = sum(int(r["total"]) for r in matched)
    personas_ok = sum(
        int(r["total"])
        for r in matched
        if r["match_type"] not in ("unmatched", "unknown_state")
    )

    print("Resultado del cruce:")
    for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k}: {v}")
    print(f"  estados corregidos: {corregidos}")
    print(f"  personas cubiertas: {personas_ok:,} / {personas:,}")

    fields = [
        "estatus_id",
        "estatus",
        "fecha_inicio",
        "fecha_fin",
        "id_estado",
        "estado",
        "municipio",
        "hombres",
        "mujeres",
        "indeterminado",
        "total",
        "cvegeo",
        "cve_estado",
        "cve_mun",
        "estado_inegi",
        "municipio_inegi",
        "estado_corregido",
        "match_type",
    ]
    write_csv(salida, matched, fields)

    # reporte de problemas / correcciones
    report_rows = [
        r
        for r in matched
        if r["match_type"] in ("unmatched", "unknown_state", "state_correction", "unique_nationwide", "unique_nationwide_agg")
        or r.get("estado_corregido") == "si"
    ]
    report_rows.sort(key=lambda r: (-int(r["total"]), r["match_type"], r["estado"], r["municipio"]))
    write_csv(reporte, report_rows, fields)

    unmatched = [r for r in matched if r["match_type"] in ("unmatched", "unknown_state")]
    if unmatched:
        print(f"Sin match AGEEML: {len(unmatched)} filas (ver {reporte.name})")
        for r in unmatched[:20]:
            print(
                f"  - [{r['id_estado']}] {r['estado']} / {r['municipio']} "
                f"(total={r['total']})"
            )
        if len(unmatched) > 20:
            print(f"  … y {len(unmatched) - 20} más")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cruce RNPDNO × AGEEML/INEGI")
    p.add_argument(
        "--entrada",
        type=Path,
        default=ROOT / "data" / "por_municipio_estatus7_2010_2025.csv",
    )
    p.add_argument(
        "--salida",
        type=Path,
        default=PROCESSED / "por_municipio_estatus7_2010_2025_geo.csv",
    )
    p.add_argument(
        "--reporte",
        type=Path,
        default=PROCESSED / "por_municipio_geo_reporte.csv",
    )
    p.add_argument(
        "--descargar-catalogo",
        action="store_true",
        help="Fuerza descarga del catálogo AGEEML desde INEGI",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.descargar_catalogo or not CATALOG_PATH.exists():
            descargar_catalogo()
        if not args.entrada.exists():
            print(f"No existe la entrada: {args.entrada}", file=sys.stderr)
            print("Corre antes: python3 scrape_rnpdno.py --dimensiones municipio", file=sys.stderr)
            return 2
        return cruzar(args.entrada, args.salida, args.reporte)
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
