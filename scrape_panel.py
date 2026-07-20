#!/usr/bin/env python3
"""
Panel RNPDNO: año × estado × municipio × rango de edad × sexo.

Usa TablaDetalle (lista completa de municipios) con filtros de fecha y edad.
Guarda shards reanudables y consolida un CSV único (formato largo).

Uso:
  python3 scrape_panel.py                      # 2010–2025, estatus 7 (~1 h)
  python3 scrape_panel.py --desde 2024 --hasta 2024 --estados 14
  python3 scrape_panel.py --solo-consolidar
  python3 scrape_panel.py --con-geo            # cruza AGEEML al consolidar

Estatus: mismos códigos que scrape_rnpdno.py (default 7).
"""

from __future__ import annotations

import argparse
import csv
import html as htmllib
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BASE_URL = "https://versionpublicarnpdno.segob.gob.mx"

ESTATUS = {
    0: "PERSONAS DESAPARECIDAS, NO LOCALIZADAS Y LOCALIZADAS",
    2: "PERSONAS LOCALIZADAS CON VIDA",
    3: "PERSONAS LOCALIZADAS SIN VIDA",
    4: "PERSONAS DESAPARECIDAS",
    5: "PERSONAS NO LOCALIZADAS",
    6: "PERSONAS LOCALIZADAS",
    7: "PERSONAS DESAPARECIDAS Y NO LOCALIZADAS",
}

# (etiqueta, edadInicio, edadFin) — None/None = tabla total (para residual sin_edad)
AGE_BANDS: list[tuple[str, str | None, str | None]] = [
    ("0-4", "0", "4"),
    ("5-9", "5", "9"),
    ("10-14", "10", "14"),
    ("15-19", "15", "19"),
    ("20-24", "20", "24"),
    ("25-29", "25", "29"),
    ("30-34", "30", "34"),
    ("35-39", "35", "39"),
    ("40-44", "40", "44"),
    ("45-49", "45", "49"),
    ("50-54", "50", "54"),
    ("55-59", "55", "59"),
    ("60-64", "60", "64"),
    ("65-69", "65", "69"),
    ("70-74", "70", "74"),
    ("75-79", "75", "79"),
    ("80+", "80", "200"),
]

SEXOS = ("hombres", "mujeres", "indeterminado")

PANEL_FIELDS = [
    "estatus_id",
    "estatus",
    "anio",
    "id_estado",
    "estado",
    "municipio",
    "rango_edad",
    "sexo",
    "personas",
]


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._in = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in and self._row is not None:
            text = htmllib.unescape("".join(self._cell or [])).strip()
            self._row.append(re.sub(r"\s+", " ", text))
            self._in = False
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in and self._cell is not None:
            self._cell.append(data)


def to_int(value: str) -> int:
    value = value.replace(",", "").strip()
    return int(value) if value.isdigit() else 0


def parse_muni_table(html: str) -> list[dict[str, Any]]:
    parser = TableParser()
    parser.feed(html or "")
    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        if len(cells) < 4:
            continue
        if cells[0].strip().lower() in {"categoría", "categoria"}:
            continue
        hombres, mujeres, indeterminado = to_int(cells[1]), to_int(cells[2]), to_int(cells[3])
        if hombres == mujeres == indeterminado == 0:
            continue
        rows.append(
            {
                "municipio": cells[0].strip(),
                "hombres": hombres,
                "mujeres": mujeres,
                "indeterminado": indeterminado,
                "total": hombres + mujeres + indeterminado,
            }
        )
    return rows


class RNPDNOClient:
    def __init__(self, delay: float = 0.35, retries: int = 5) -> None:
        self.delay = delay
        self.retries = retries
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self.opener.addheaders = [
            (
                "User-Agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
            ("Accept", "application/json, text/javascript, */*; q=0.01"),
            ("Accept-Language", "es-MX,es;q=0.9,en;q=0.8"),
            ("X-Requested-With", "XMLHttpRequest"),
            ("Origin", BASE_URL),
            ("Referer", f"{BASE_URL}/Dashboard/Sociodemografico"),
        ]

    def open_session(self) -> None:
        print("Abriendo sesión en el RNPDNO…", flush=True)
        with self.opener.open(f"{BASE_URL}/", timeout=60) as resp:
            resp.read()
        names = {c.name for c in self.cj}
        if "ASP.NET_SessionId" not in names and ".AspNet.ApplicationCookie" not in names:
            raise RuntimeError("No se obtuvo cookie de sesión del RNPDNO.")
        print("Sesión lista.", flush=True)

    def _request(self, path: str, form: dict[str, str]) -> Any:
        body = urllib.parse.urlencode(form).encode("utf-8")
        url = f"{BASE_URL}{path}"
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Content-Length": str(len(body)),
                    },
                    method="POST",
                )
                with self.opener.open(req, timeout=90) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    raise ValueError("respuesta vacía")
                data = json.loads(raw)
                time.sleep(self.delay)
                return data
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                # 500 del RNPDNO: backoff más largo; renovar sesión a mitad de reintentos
                wait = min(2**attempt, 60)
                if "500" in str(exc):
                    wait = min(15 * attempt, 90)
                print(
                    f"  reintento {attempt}/{self.retries} {path}: {exc} (espera {wait}s)",
                    flush=True,
                )
                if attempt in {3, 6}:
                    try:
                        with self.opener.open(f"{BASE_URL}/", timeout=60) as resp:
                            resp.read()
                        print("  sesión renovada", flush=True)
                    except Exception as renew_err:
                        print(f"  no se pudo renovar sesión: {renew_err}", flush=True)
                time.sleep(wait)
        raise RuntimeError(f"Falló {path}: {last_err}")

    def catalogo_estados(self) -> list[dict[str, Any]]:
        data = self._request("/Catalogo/Estados", {})
        return [x for x in data if int(x["Value"]) != 0]

    def params(
        self,
        estatus: int,
        fecha_inicio: str,
        fecha_fin: str,
        id_estado: int,
        edad_inicio: str = "",
        edad_fin: str = "",
    ) -> dict[str, str]:
        return {
            "titulo": ESTATUS[estatus],
            "subtitulo": "POR MUNICIPIO",
            "idEstatusVictima": str(estatus),
            "fechaInicio": fecha_inicio,
            "fechaFin": fecha_fin,
            "idEstado": str(id_estado),
            "idMunicipio": "0",
            "mostrarFechaNula": "0",
            "idColonia": "0",
            "idNacionalidad": "0",
            "edadInicio": edad_inicio,
            "edadFin": edad_fin,
            "mostrarEdadNula": "0",
            "idHipotesis": "",
            "idMedioConocimiento": "",
            "idCircunstancia": "",
            "tieneDiscapacidad": "",
            "idTipoDiscapacidad": "0",
            "idEtnia": "0",
            "idLengua": "0",
            "idReligion": "",
            "esMigrante": "",
            "idEstatusMigratorio": "0",
            "esLgbttti": "",
            "esServidorPublico": "",
            "esDefensorDH": "",
            "esPeriodista": "",
            "esSindicalista": "",
            "esONG": "",
            "idHipotesisNoLocalizacion": "0",
            "idDelito": "0",
            "TipoDetalle": "3",
        }

    def tabla_municipios(self, params: dict[str, str]) -> list[dict[str, Any]]:
        payload = self._request("/SocioDemografico/TablaDetalle", params)
        return parse_muni_table(payload.get("Html", ""))


def shard_path(
    shards_dir: Path, estatus: int, anio: int, id_estado: int, rango: str
) -> Path:
    safe = rango.replace("+", "plus").replace("/", "_")
    return shards_dir / f"e{estatus}_{anio}_{id_estado:02d}_{safe}.csv"


def write_shard(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def melt_sex(row: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = [
        ("hombres", "hombre"),
        ("mujeres", "mujer"),
        ("indeterminado", "indeterminado"),
    ]
    out = []
    for src, label in mapping:
        n = int(row[src])
        if n > 0:
            out.append({**meta, "municipio": row["municipio"], "sexo": label, "personas": n})
    return out


def compute_sin_edad(
    total_table: list[dict[str, Any]],
    band_tables: list[list[dict[str, Any]]],
    *,
    estatus: int,
    anio: int,
    id_estado: int,
    estado: str,
) -> list[dict[str, Any]]:
    """Residual por municipio: total − suma de rangos etarios."""
    acc: dict[str, dict[str, int]] = {}
    for table in band_tables:
        for row in table:
            slot = acc.setdefault(
                row["municipio"], {"hombres": 0, "mujeres": 0, "indeterminado": 0}
            )
            for s in SEXOS:
                slot[s] += int(row[s])

    residual_table: list[dict[str, Any]] = []
    for row in total_table:
        mun = row["municipio"]
        used = acc.get(mun, {"hombres": 0, "mujeres": 0, "indeterminado": 0})
        hombres = max(0, int(row["hombres"]) - used["hombres"])
        mujeres = max(0, int(row["mujeres"]) - used["mujeres"])
        indeterminado = max(0, int(row["indeterminado"]) - used["indeterminado"])
        if hombres == mujeres == indeterminado == 0:
            continue
        residual_table.append(
            {
                "municipio": mun,
                "hombres": hombres,
                "mujeres": mujeres,
                "indeterminado": indeterminado,
            }
        )
    # también municipios solo en bandas? no aportan residual positivo
    meta = {
        "estatus_id": estatus,
        "estatus": ESTATUS[estatus],
        "anio": anio,
        "id_estado": id_estado,
        "estado": estado,
        "rango_edad": "sin_edad",
    }
    rows: list[dict[str, Any]] = []
    for mun in residual_table:
        rows.extend(melt_sex(mun, meta))
    return rows


def scrape_panel(
    *,
    salida_dir: Path,
    estatus: int,
    desde: int,
    hasta: int,
    estados_filter: list[int] | None,
    delay: float,
) -> None:
    shards_dir = salida_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    failures_path = salida_dir / "failures.csv"
    failures: list[dict[str, str]] = []
    if failures_path.exists():
        with failures_path.open(encoding="utf-8") as fh:
            failures = list(csv.DictReader(fh))

    client = RNPDNOClient(delay=delay)
    client.open_session()
    estados = client.catalogo_estados()
    if estados_filter:
        wanted = set(estados_filter)
        estados = [e for e in estados if int(e["Value"]) in wanted]

    years = list(range(desde, hasta + 1))
    total_jobs = len(years) * len(estados) * (len(AGE_BANDS) + 2)  # bands + total + sin_edad
    done = 0
    print(
        f"Plan: {len(years)} años × {len(estados)} estados × "
        f"{len(AGE_BANDS)} rangos (+ total/sin_edad) ≈ {total_jobs} peticiones",
        flush=True,
    )

    def log_failure(anio: int, id_estado: int, estado: str, rango: str, err: Exception) -> None:
        failures.append(
            {
                "anio": str(anio),
                "id_estado": str(id_estado),
                "estado": estado,
                "rango_edad": rango,
                "error": str(err)[:300],
            }
        )
        with failures_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["anio", "id_estado", "estado", "rango_edad", "error"]
            )
            writer.writeheader()
            writer.writerows(failures)
        print(f"  FALLO registrado → continúo ({err})", flush=True)
        time.sleep(max(delay * 4, 5))

    for anio in years:
        for estado_row in estados:
            id_estado = int(estado_row["Value"])
            estado = str(estado_row["Text"]).strip()
            band_tables: list[list[dict[str, Any]]] = []
            band_ok = True

            # 1) rangos etarios
            for rango, e0, e1 in AGE_BANDS:
                path = shard_path(shards_dir, estatus, anio, id_estado, rango)
                done += 1
                if path.exists() and path.stat().st_size > 0:
                    wide = _shard_to_wide(path)
                    band_tables.append(wide)
                    print(f"[{done}/{total_jobs}] skip {anio} {estado} {rango}", flush=True)
                    continue
                print(f"[{done}/{total_jobs}] {anio} {estado} {rango}", flush=True)
                assert e0 is not None and e1 is not None
                try:
                    params = client.params(
                        estatus,
                        f"{anio:04d}-01-01",
                        f"{anio:04d}-12-31",
                        id_estado,
                        edad_inicio=e0,
                        edad_fin=e1,
                    )
                    table = client.tabla_municipios(params)
                except Exception as exc:
                    band_ok = False
                    log_failure(anio, id_estado, estado, rango, exc)
                    band_tables.append([])
                    continue
                band_tables.append(table)
                meta = {
                    "estatus_id": estatus,
                    "estatus": ESTATUS[estatus],
                    "anio": anio,
                    "id_estado": id_estado,
                    "estado": estado,
                    "rango_edad": rango,
                }
                rows: list[dict[str, Any]] = []
                for mun in table:
                    rows.extend(melt_sex(mun, meta))
                write_shard(path, rows)

            # 2) total sin filtro de edad
            total_path = shard_path(shards_dir, estatus, anio, id_estado, "total")
            done += 1
            total_table: list[dict[str, Any]] = []
            if total_path.exists() and total_path.stat().st_size > 0:
                print(f"[{done}/{total_jobs}] skip {anio} {estado} total", flush=True)
                total_table = _shard_to_wide(total_path)
            else:
                print(f"[{done}/{total_jobs}] {anio} {estado} total", flush=True)
                try:
                    params = client.params(
                        estatus,
                        f"{anio:04d}-01-01",
                        f"{anio:04d}-12-31",
                        id_estado,
                    )
                    total_table = client.tabla_municipios(params)
                    meta = {
                        "estatus_id": estatus,
                        "estatus": ESTATUS[estatus],
                        "anio": anio,
                        "id_estado": id_estado,
                        "estado": estado,
                        "rango_edad": "total",
                    }
                    rows = []
                    for mun in total_table:
                        rows.extend(melt_sex(mun, meta))
                    write_shard(total_path, rows)
                except Exception as exc:
                    band_ok = False
                    log_failure(anio, id_estado, estado, "total", exc)

            # 3) sin_edad residual (solo si hay total + todos los rangos)
            sin_path = shard_path(shards_dir, estatus, anio, id_estado, "sin_edad")
            done += 1
            if sin_path.exists() and sin_path.stat().st_size > 0:
                print(f"[{done}/{total_jobs}] skip {anio} {estado} sin_edad", flush=True)
                continue
            if not band_ok or not total_path.exists():
                print(
                    f"[{done}/{total_jobs}] posponer sin_edad {anio} {estado} (faltan shards)",
                    flush=True,
                )
                continue
            print(f"[{done}/{total_jobs}] {anio} {estado} sin_edad (residual)", flush=True)
            if len(band_tables) != len(AGE_BANDS):
                band_tables = [
                    _shard_to_wide(shard_path(shards_dir, estatus, anio, id_estado, r))
                    for r, _, _ in AGE_BANDS
                ]
            if not total_table:
                total_table = _shard_to_wide(total_path)
            # exige que existan todos los shards de rango
            missing = [
                r
                for r, _, _ in AGE_BANDS
                if not shard_path(shards_dir, estatus, anio, id_estado, r).exists()
            ]
            if missing:
                print(f"  faltan rangos {missing}; sin_edad pospuesto", flush=True)
                continue
            sin_rows = compute_sin_edad(
                total_table,
                band_tables,
                estatus=estatus,
                anio=anio,
                id_estado=id_estado,
                estado=estado,
            )
            write_shard(sin_path, sin_rows)

    if failures:
        print(f"Fallos acumulados: {len(failures)} (ver {failures_path})", flush=True)


def _shard_to_wide(path: Path) -> list[dict[str, Any]]:
    """Reconstruye tabla ancha por municipio desde shard largo."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    acc: dict[str, dict[str, int]] = {}
    sexo_map = {"hombre": "hombres", "mujer": "mujeres", "indeterminado": "indeterminado"}
    for r in rows:
        mun = r["municipio"]
        slot = acc.setdefault(mun, {"hombres": 0, "mujeres": 0, "indeterminado": 0})
        key = sexo_map.get(r["sexo"], r["sexo"])
        if key in slot:
            slot[key] += int(r["personas"])
    return [{"municipio": m, **vals} for m, vals in acc.items()]


def consolidar(
    shards_dir: Path,
    salida: Path,
    *,
    estatus: int,
    desde: int,
    hasta: int,
    incluir_total: bool = False,
) -> int:
    prefix = f"e{estatus}_"
    files = sorted(
        fp
        for fp in shards_dir.glob(f"{prefix}*.csv")
        if _shard_year(fp, prefix) is not None
        and desde <= _shard_year(fp, prefix) <= hasta  # type: ignore[operator]
        and (incluir_total or not fp.name.endswith("_total.csv"))
    )
    if not files:
        print(f"No hay shards en {shards_dir} para e{estatus} {desde}-{hasta}")
        return 0
    salida.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with salida.open("w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        for fp in files:
            with fp.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    writer.writerow(row)
                    n += 1
    print(f"Consolidado {salida} ({n:,} filas)")
    return n


def _shard_year(path: Path, prefix: str) -> int | None:
    # e7_2024_14_15-19.csv
    name = path.name
    if not name.startswith(prefix):
        return None
    parts = name[len(prefix) :].split("_", 2)
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


def aplicar_geo(panel_csv: Path, salida_geo: Path) -> None:
    """Añade columnas AGEEML reutilizando cruzar_municipios."""
    import cruzar_municipios as geo

    catalog = geo.cargar_catalogo()
    ref = geo.build_ref(catalog)
    overrides, corrections = geo.load_manuals(ref)

    with panel_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    out_fields = PANEL_FIELDS + [
        "cvegeo",
        "cve_estado",
        "cve_mun",
        "estado_inegi",
        "municipio_inegi",
        "estado_corregido",
        "match_type",
    ]
    # cache por (id_estado, municipio)
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["id_estado"]), row["municipio"])
        if key not in cache:
            fake = {
                "id_estado": row["id_estado"],
                "estado": row["estado"],
                "municipio": row["municipio"],
                "hombres": "0",
                "mujeres": "0",
                "indeterminado": "0",
                "total": "0",
            }
            matched = geo.match_row(fake, ref, overrides, corrections)
            cache[key] = {
                "cvegeo": matched.get("cvegeo", ""),
                "cve_estado": matched.get("cve_estado", ""),
                "cve_mun": matched.get("cve_mun", ""),
                "estado_inegi": matched.get("estado_inegi", ""),
                "municipio_inegi": matched.get("municipio_inegi", ""),
                "estado_corregido": matched.get("estado_corregido", ""),
                "match_type": matched.get("match_type", ""),
            }
        enriched.append({**row, **cache[key]})

    salida_geo.parent.mkdir(parents=True, exist_ok=True)
    with salida_geo.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched)
    print(f"Panel con geo: {salida_geo} ({len(enriched):,} filas)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Panel RNPDNO año×estado×municipio×edad×sexo")
    p.add_argument("--estatus", type=int, default=7, choices=sorted(ESTATUS))
    p.add_argument("--desde", type=int, default=2010)
    p.add_argument("--hasta", type=int, default=2025)
    p.add_argument("--estados", type=int, nargs="*", default=None, help="IDs de estado (ej. 14 15)")
    p.add_argument("--delay", type=float, default=0.35)
    p.add_argument(
        "--salida-dir",
        type=Path,
        default=ROOT / "data" / "panel",
        help="Carpeta de shards y consolidados",
    )
    p.add_argument("--solo-consolidar", action="store_true")
    p.add_argument("--incluir-total", action="store_true", help="Incluye rango_edad=total en el CSV")
    p.add_argument("--con-geo", action="store_true", help="Cruza con AGEEML al consolidar")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.desde > args.hasta:
        print("Error: --desde > --hasta", file=sys.stderr)
        return 2

    shards = args.salida_dir / "shards"
    tag = f"estatus{args.estatus}_{args.desde}_{args.hasta}"
    panel_csv = args.salida_dir / f"panel_{tag}.csv"
    panel_geo = args.salida_dir / f"panel_{tag}_geo.csv"

    try:
        if not args.solo_consolidar:
            scrape_panel(
                salida_dir=args.salida_dir,
                estatus=args.estatus,
                desde=args.desde,
                hasta=args.hasta,
                estados_filter=args.estados,
                delay=args.delay,
            )
        consolidar(
            shards,
            panel_csv,
            estatus=args.estatus,
            desde=args.desde,
            hasta=args.hasta,
            incluir_total=args.incluir_total,
        )
        if args.con_geo:
            aplicar_geo(panel_csv, panel_geo)
        print("Listo.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrumpido. Puedes reanudar con el mismo comando (omite shards existentes).", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
