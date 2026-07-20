#!/usr/bin/env python3
"""
Extrae totales agregados del RNPDNO (versión pública estadística) 2010–2025.

Solo usa la biblioteca estándar de Python. Consulta la API interna del dashboard
tras abrir una sesión (cookie), sin navegador ni CAPTCHA.

Uso:
  python3 scrape_rnpdno.py
  python3 scrape_rnpdno.py --estatus 7 --desde 2010 --hasta 2025
  python3 scrape_rnpdno.py --dimensiones totales estado municipio edad anio
  python3 scrape_rnpdno.py --salida data --delay 0.4

Estatus de víctima:
  0  PERSONAS DESAPARECIDAS, NO LOCALIZADAS Y LOCALIZADAS
  2  PERSONAS LOCALIZADAS CON VIDA
  3  PERSONAS LOCALIZADAS SIN VIDA
  4  PERSONAS DESAPARECIDAS
  5  PERSONAS NO LOCALIZADAS
  6  PERSONAS LOCALIZADAS
  7  PERSONAS DESAPARECIDAS Y NO LOCALIZADAS  (default)
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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

ENDPOINTS = {
    "totales": "/Sociodemografico/Totales",
    "estado": "/SocioDemografico/BarChartSexoEstados",
    "municipio": "/SocioDemografico/BarChartSexoMunicipio",
    "anio": "/SocioDemografico/AreaChartSexoAnio",
    "edad": "/SocioDemografico/AreaChartSexoRango",
    "nacionalidad": "/SocioDemografico/BarChartSexoNacionalidad",
}

SERIES_MAP = {
    "hombre": "hombres",
    "hombres": "hombres",
    "mujer": "mujeres",
    "mujeres": "mujeres",
    "indeterminado": "indeterminado",
}


class RNPDNOClient:
    def __init__(self, delay: float = 0.35, retries: int = 4) -> None:
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
        print("Abriendo sesión en el RNPDNO…")
        with self.opener.open(f"{BASE_URL}/", timeout=60) as resp:
            resp.read()
        names = {c.name for c in self.cj}
        if "ASP.NET_SessionId" not in names and ".AspNet.ApplicationCookie" not in names:
            raise RuntimeError("No se obtuvo cookie de sesión del RNPDNO.")
        print("Sesión lista.")

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
                wait = min(2 ** attempt, 20)
                print(f"  reintento {attempt}/{self.retries} {path}: {exc} (espera {wait}s)")
                time.sleep(wait)
        raise RuntimeError(f"Falló {path}: {last_err}")

    def catalogo_estados(self) -> list[dict[str, Any]]:
        data = self._request("/Catalogo/Estados", {})
        return [x for x in data if int(x["Value"]) != 0]

    def catalogo_municipios(self, id_estado: int) -> list[dict[str, Any]]:
        data = self._request("/Catalogo/Municipios", {"idEstado": str(id_estado)})
        return [x for x in data if int(x["Value"]) != 0]

    def params(
        self,
        estatus: int,
        fecha_inicio: str,
        fecha_fin: str,
        id_estado: int = 0,
        id_municipio: int = 0,
    ) -> dict[str, str]:
        return {
            "titulo": ESTATUS[estatus],
            "idEstatusVictima": str(estatus),
            "fechaInicio": fecha_inicio,
            "fechaFin": fecha_fin,
            "idEstado": str(id_estado),
            "idMunicipio": str(id_municipio),
            "mostrarFechaNula": "0",
            "idColonia": "0",
            "idNacionalidad": "0",
            "edadInicio": "",
            "edadFin": "",
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
        }

    def chart(self, dimension: str, params: dict[str, str]) -> dict[str, Any]:
        return self._request(ENDPOINTS[dimension], params)

    def totales(self, params: dict[str, str]) -> dict[str, str]:
        raw = self._request(ENDPOINTS["totales"], params)
        out: dict[str, str] = {}
        for key, value in raw.items():
            out[key] = str(value).replace(",", "").replace(" %", "").strip()
        return out


def chart_to_rows(payload: dict[str, Any], extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    categories = payload.get("XAxisCategories") or []
    series = payload.get("Series") or []
    by_sex: dict[str, list[Any]] = {"hombres": [], "mujeres": [], "indeterminado": []}
    for serie in series:
        key = SERIES_MAP.get(str(serie.get("name", "")).strip().lower())
        if key:
            by_sex[key] = list(serie.get("data") or [])

    rows: list[dict[str, Any]] = []
    for i, categoria in enumerate(categories):
        hombres = int(by_sex["hombres"][i]) if i < len(by_sex["hombres"]) else 0
        mujeres = int(by_sex["mujeres"][i]) if i < len(by_sex["mujeres"]) else 0
        indeterminado = (
            int(by_sex["indeterminado"][i]) if i < len(by_sex["indeterminado"]) else 0
        )
        row = {
            "categoria": str(categoria).strip(),
            "hombres": hombres,
            "mujeres": mujeres,
            "indeterminado": indeterminado,
            "total": hombres + mujeres + indeterminado,
        }
        if extra:
            row = {**extra, **row}
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        print(f"  sin filas → {path}")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  guardado {path} ({len(rows)} filas)")


def scrape(
    salida: Path,
    estatus: int,
    desde: int,
    hasta: int,
    dimensiones: list[str],
    delay: float,
) -> None:
    client = RNPDNOClient(delay=delay)
    client.open_session()

    fecha_inicio = f"{desde:04d}-01-01"
    fecha_fin = f"{hasta:04d}-12-31"
    params = client.params(estatus, fecha_inicio, fecha_fin)
    meta = {
        "estatus_id": estatus,
        "estatus": ESTATUS[estatus],
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
    }
    tag = f"estatus{estatus}_{desde}_{hasta}"

    if "totales" in dimensiones:
        print("Extrayendo totales…")
        tot = client.totales(params)
        write_csv(
            salida / f"totales_{tag}.csv",
            [{**meta, **tot}],
        )

    if "estado" in dimensiones:
        print("Extrayendo por estado…")
        rows = chart_to_rows(client.chart("estado", params), {**meta, "nivel": "estado"})
        for row in rows:
            row["estado"] = row.pop("categoria")
        write_csv(
            salida / f"por_estado_{tag}.csv",
            rows,
            [
                "estatus_id",
                "estatus",
                "fecha_inicio",
                "fecha_fin",
                "nivel",
                "estado",
                "hombres",
                "mujeres",
                "indeterminado",
                "total",
            ],
        )

    if "anio" in dimensiones:
        print("Extrayendo por año…")
        rows = chart_to_rows(client.chart("anio", params), {**meta, "nivel": "anio"})
        for row in rows:
            row["anio"] = row.pop("categoria")
        write_csv(
            salida / f"por_anio_{tag}.csv",
            rows,
            [
                "estatus_id",
                "estatus",
                "fecha_inicio",
                "fecha_fin",
                "nivel",
                "anio",
                "hombres",
                "mujeres",
                "indeterminado",
                "total",
            ],
        )

    if "edad" in dimensiones:
        print("Extrayendo por rango de edad…")
        rows = chart_to_rows(client.chart("edad", params), {**meta, "nivel": "edad"})
        for row in rows:
            row["rango_edad"] = row.pop("categoria")
        write_csv(
            salida / f"por_edad_{tag}.csv",
            rows,
            [
                "estatus_id",
                "estatus",
                "fecha_inicio",
                "fecha_fin",
                "nivel",
                "rango_edad",
                "hombres",
                "mujeres",
                "indeterminado",
                "total",
            ],
        )

    if "nacionalidad" in dimensiones:
        print("Extrayendo por nacionalidad…")
        rows = chart_to_rows(
            client.chart("nacionalidad", params), {**meta, "nivel": "nacionalidad"}
        )
        for row in rows:
            row["nacionalidad"] = row.pop("categoria")
        write_csv(
            salida / f"por_nacionalidad_{tag}.csv",
            rows,
            [
                "estatus_id",
                "estatus",
                "fecha_inicio",
                "fecha_fin",
                "nivel",
                "nacionalidad",
                "hombres",
                "mujeres",
                "indeterminado",
                "total",
            ],
        )

    if "municipio" in dimensiones:
        print("Extrayendo por municipio (iterando estados)…")
        estados = client.catalogo_estados()
        all_rows: list[dict[str, Any]] = []
        for i, estado in enumerate(estados, start=1):
            id_estado = int(estado["Value"])
            nombre = str(estado["Text"]).strip()
            print(f"  [{i}/{len(estados)}] {nombre}")
            p = client.params(estatus, fecha_inicio, fecha_fin, id_estado=id_estado)
            payload = client.chart("municipio", p)
            rows = chart_to_rows(
                payload,
                {
                    **meta,
                    "nivel": "municipio",
                    "id_estado": id_estado,
                    "estado": nombre,
                },
            )
            for row in rows:
                row["municipio"] = row.pop("categoria")
                if row["total"] > 0:
                    all_rows.append(row)
        write_csv(
            salida / f"por_municipio_{tag}.csv",
            all_rows,
            [
                "estatus_id",
                "estatus",
                "fecha_inicio",
                "fecha_fin",
                "nivel",
                "id_estado",
                "estado",
                "municipio",
                "hombres",
                "mujeres",
                "indeterminado",
                "total",
            ],
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scraper de totales agregados del RNPDNO (2010–2025)."
    )
    parser.add_argument(
        "--estatus",
        type=int,
        default=7,
        choices=sorted(ESTATUS),
        help="Estatus de víctima (default: 7 = desaparecidas y no localizadas)",
    )
    parser.add_argument("--desde", type=int, default=2010, help="Año inicial (inclusive)")
    parser.add_argument("--hasta", type=int, default=2025, help="Año final (inclusive)")
    parser.add_argument(
        "--dimensiones",
        nargs="+",
        default=["totales", "estado", "municipio", "edad", "anio"],
        choices=list(ENDPOINTS),
        help="Dimensiones a extraer",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path("data"),
        help="Carpeta de salida CSV (default: data/)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Pausa entre peticiones en segundos (default: 0.35)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.desde > args.hasta:
        print("Error: --desde no puede ser mayor que --hasta", file=sys.stderr)
        return 2
    try:
        scrape(
            salida=args.salida,
            estatus=args.estatus,
            desde=args.desde,
            hasta=args.hasta,
            dimensiones=args.dimensiones,
            delay=args.delay,
        )
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
