#!/usr/bin/env python3
"""Reintenta shards fallidos usando desglose mensual si el año completo devuelve 500."""

from __future__ import annotations

import calendar
import csv
import sys
from pathlib import Path
from typing import Any

from scrape_panel import (
    AGE_BANDS,
    RNPDNOClient,
    compute_sin_edad,
    melt_sex,
    shard_path,
    write_shard,
)

ROOT = Path(__file__).resolve().parent
SHARDS = ROOT / "data" / "panel" / "shards"
FAILURES = ROOT / "data/panel/failures.csv"

# (anio, id_estado, estado, rango_edad, edad_inicio, edad_fin)
RETRY: list[tuple[int, int, str, str, str, str]] = [
    (2010, 28, "TAMAULIPAS", "15-19", "15", "19"),
    (2010, 28, "TAMAULIPAS", "20-24", "20", "24"),
    (2010, 28, "TAMAULIPAS", "25-29", "25", "29"),
    (2010, 28, "TAMAULIPAS", "30-34", "30", "34"),
    (2011, 4, "CAMPECHE", "25-29", "25", "29"),
]

ESTATUS = 7


def aggregate_tables(tables: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, int]] = {}
    for table in tables:
        for row in table:
            slot = acc.setdefault(
                row["municipio"],
                {"hombres": 0, "mujeres": 0, "indeterminado": 0},
            )
            slot["hombres"] += row["hombres"]
            slot["mujeres"] += row["mujeres"]
            slot["indeterminado"] += row["indeterminado"]
    out = []
    for mun, vals in acc.items():
        total = vals["hombres"] + vals["mujeres"] + vals["indeterminado"]
        if total > 0:
            out.append({"municipio": mun, **vals, "total": total})
    return out


def fetch_yearly(client: RNPDNOClient, anio: int, id_estado: int, e0: str, e1: str) -> list[dict[str, Any]]:
    params = client.params(
        ESTATUS,
        f"{anio:04d}-01-01",
        f"{anio:04d}-12-31",
        id_estado,
        edad_inicio=e0,
        edad_fin=e1,
    )
    return client.tabla_municipios(params)


def fetch_monthly(client: RNPDNOClient, anio: int, id_estado: int, e0: str, e1: str) -> list[dict[str, Any]]:
    tables: list[list[dict[str, Any]]] = []
    for month in range(1, 13):
        last = calendar.monthrange(anio, month)[1]
        params = client.params(
            ESTATUS,
            f"{anio:04d}-{month:02d}-01",
            f"{anio:04d}-{month:02d}-{last:02d}",
            id_estado,
            edad_inicio=e0,
            edad_fin=e1,
        )
        tables.append(client.tabla_municipios(params))
        print(f"    mes {month:02d}: {sum(r['total'] for r in tables[-1])} personas", flush=True)
    return aggregate_tables(tables)


def fetch_band(
    client: RNPDNOClient, anio: int, id_estado: int, e0: str, e1: str
) -> tuple[list[dict[str, Any]], str]:
    try:
        return fetch_yearly(client, anio, id_estado, e0, e1), "anual"
    except Exception as exc:
        if "500" not in str(exc):
            raise
        print(f"    anual falló ({exc}); usando mensual…", flush=True)
        return fetch_monthly(client, anio, id_estado, e0, e1), "mensual"


def recompute_sin_edad(client: RNPDNOClient, anio: int, id_estado: int, estado: str) -> None:
    sin_path = shard_path(SHARDS, ESTATUS, anio, id_estado, "sin_edad")
    total_path = shard_path(SHARDS, ESTATUS, anio, id_estado, "total")
    if not total_path.exists():
        print(f"  sin total para {anio} {estado}; sin_edad pospuesto", flush=True)
        return
    missing = [
        r
        for r, _, _ in AGE_BANDS
        if not shard_path(SHARDS, ESTATUS, anio, id_estado, r).exists()
    ]
    if missing:
        print(f"  faltan rangos {missing}; sin_edad pospuesto", flush=True)
        return

    from scrape_panel import _shard_to_wide

    band_tables = [
        _shard_to_wide(shard_path(SHARDS, ESTATUS, anio, id_estado, r))
        for r, _, _ in AGE_BANDS
    ]
    total_table = _shard_to_wide(total_path)
    sin_rows = compute_sin_edad(
        total_table,
        band_tables,
        estatus=ESTATUS,
        anio=anio,
        id_estado=id_estado,
        estado=estado,
    )
    write_shard(sin_path, sin_rows)
    print(f"  sin_edad → {sin_path.name} ({len(sin_rows)} filas)", flush=True)


def main() -> int:
    client = RNPDNOClient(delay=0.5, retries=5)
    client.open_session()
    ok = 0
    still_failed: list[tuple[int, int, str, str, str]] = []

    for anio, id_estado, estado, rango, e0, e1 in RETRY:
        path = shard_path(SHARDS, ESTATUS, anio, id_estado, rango)
        if path.exists() and path.stat().st_size > 0:
            print(f"skip {anio} {estado} {rango} (ya existe)", flush=True)
            ok += 1
            continue
        print(f"reintento {anio} {estado} {rango}…", flush=True)
        try:
            table, mode = fetch_band(client, anio, id_estado, e0, e1)
            meta = {
                "estatus_id": ESTATUS,
                "estatus": "PERSONAS DESAPARECIDAS Y NO LOCALIZADAS",
                "anio": anio,
                "id_estado": id_estado,
                "estado": estado,
                "rango_edad": rango,
            }
            rows = []
            for mun in table:
                rows.extend(melt_sex(mun, meta))
            write_shard(path, rows)
            print(
                f"  OK ({mode}): {path.name} — {sum(r['total'] for r in table)} personas, {len(rows)} filas",
                flush=True,
            )
            ok += 1
        except Exception as exc:
            print(f"  FALLO: {exc}", flush=True)
            still_failed.append((anio, id_estado, estado, rango, str(exc)))

    for ys in [(2010, 28, "TAMAULIPAS"), (2011, 4, "CAMPECHE")]:
        recompute_sin_edad(client, ys[0], ys[1], ys[2])

    # actualizar failures.csv
    remaining = still_failed
    with FAILURES.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["anio", "id_estado", "estado", "rango_edad", "error"])
        for anio, id_estado, estado, rango, err in remaining:
            writer.writerow([anio, id_estado, estado, rango, err])

    if still_failed:
        print(f"\nQuedan {len(still_failed)} fallos.", file=sys.stderr)
        return 1

    print("\nTodos los shards reintentados. Reconsolidando panel…", flush=True)
    from scrape_panel import aplicar_geo, consolidar

    panel = ROOT / "data" / "panel" / "panel_estatus7_2010_2025.csv"
    panel_geo = ROOT / "data" / "panel" / "panel_estatus7_2010_2025_geo.csv"
    consolidar(SHARDS, panel, estatus=ESTATUS, desde=2010, hasta=2025)
    aplicar_geo(panel, panel_geo)

    import csv as csvmod
    from collections import Counter

    rows = list(csvmod.DictReader(panel.open()))
    by_year = Counter()
    for r in rows:
        if r["rango_edad"] != "total":
            by_year[r["anio"]] += int(r["personas"])
    anio_ref = list(csvmod.DictReader((ROOT / "data/por_anio_estatus7_2010_2025.csv").open()))
    print("Validación 2010:", by_year["2010"], "vs dashboard", anio_ref[0]["total"])
    print("Panel total:", sum(int(r["personas"]) for r in rows))
    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
