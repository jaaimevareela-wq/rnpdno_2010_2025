#!/usr/bin/env python3
"""
Compara la dummy institucional por decreto vs. por nombramiento de titular.

Uso:
  python3 analysis/compare_comision_busqueda.py
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECRETO = ROOT / "data" / "manual" / "comision_busqueda.csv"
TITULAR = ROOT / "data" / "manual" / "comision_busqueda_titular.csv"
CATALOGO = ROOT / "data" / "manual" / "comision_busqueda_titular_catalogo.csv"
OUT = ROOT / "data" / "processed" / "comision_busqueda_comparacion.csv"


def read_panel(path: Path, col: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(row["cve_estado"], row["anio"])] = row[col]
    return out


def main() -> None:
    decreto = read_panel(DECRETO, "comision_busqueda")
    titular = read_panel(TITULAR, "comision_busqueda_titular")

    rows = []
    for key in sorted(decreto):
        d, t = decreto[key], titular.get(key, "")
        rows.append(
            {
                "cve_estado": key[0],
                "anio": key[1],
                "comision_busqueda_decreto": d,
                "comision_busqueda_titular": t,
                "diferencia": int(d or 0) - int(t or 0),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "cve_estado",
                "anio",
                "comision_busqueda_decreto",
                "comision_busqueda_titular",
                "diferencia",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    by_year: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        y = r["anio"]
        by_year[y]["decreto"] += int(r["comision_busqueda_decreto"])
        by_year[y]["titular"] += int(r["comision_busqueda_titular"])
        if r["diferencia"]:
            by_year[y]["diff_rows"] += 1

    conf = Counter()
    with CATALOGO.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conf[row["confianza"]] += 1

    print("=== Comisión de búsqueda: decreto vs. titular ===\n")
    print(f"Filas comparadas: {len(rows)}")
    print(f"Filas distintas: {sum(1 for r in rows if r['diferencia'])}")
    print(f"Confianza catálogo titular: {dict(conf)}\n")
    print("Entidades con comisión (conteo anual):")
    print(f"{'Año':>6}  {'Decreto':>8}  {'Titular':>8}  {'Δ filas':>8}")
    for y in sorted(by_year):
        c = by_year[y]
        print(f"{y:>6}  {c['decreto']:>8}  {c['titular']:>8}  {c['diff_rows']:>8}")

    lag: dict[str, int] = {}
    with CATALOGO.open(encoding="utf-8") as f:
        cat = {r["cve_estado"]: r for r in csv.DictReader(f)}
    with DECRETO.open(encoding="utf-8") as f:
        dec_year = {}
        for row in csv.DictReader(f):
            if row["comision_busqueda"] == "1" and row["cve_estado"] not in dec_year:
                dec_year[row["cve_estado"]] = int(row["anio"])
    for cve, meta in sorted(cat.items()):
        lag[cve] = int(meta["anio_primer_titular"]) - dec_year.get(cve, 999)

    print("\nRetraso titular − decreto (años, por entidad):")
    for cve, years in sorted(lag.items(), key=lambda x: (-x[1], x[0])):
        if years == 999:
            continue
        estado = cat[cve]["estado"]
        confianza = cat[cve]["confianza"]
        print(f"  {cve} {estado:22}  +{years}  ({confianza})")

    print(f"\nTabla detalle: {OUT}")


if __name__ == "__main__":
    main()
