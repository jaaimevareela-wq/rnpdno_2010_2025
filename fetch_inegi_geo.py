#!/usr/bin/env python3
"""Descarga geometrías estatales del Marco Geoestadístico INEGI (GeoJSON).

Fuente oficial (sin token):
  https://gaia.inegi.org.mx/wscatgeo/v2/geo/mgee/{cve_ent}

Salida:
  data/external/geo/entidades_federativas.geojson
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "external" / "geo" / "entidades_federativas.geojson"
BASE = "https://gaia.inegi.org.mx/wscatgeo/v2/geo/mgee"


def fetch_entidad(cve: str) -> dict:
    url = f"{BASE}/{cve}"
    req = urllib.request.Request(url, headers={"User-Agent": "rnpdno-tfm/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # La API puede devolver Feature, FeatureCollection o envoltorio {datos: ...}
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data
    if isinstance(data, dict) and data.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [data]}
    if isinstance(data, dict) and "features" in data:
        return {"type": "FeatureCollection", "features": data["features"]}
    # Algunos endpoints envuelven en 'datos'
    if isinstance(data, dict) and "datos" in data:
        datos = data["datos"]
        if isinstance(datos, dict) and datos.get("type") == "Feature":
            return {"type": "FeatureCollection", "features": [datos]}
        if isinstance(datos, list):
            feats = []
            for item in datos:
                if isinstance(item, dict) and item.get("type") == "Feature":
                    feats.append(item)
                elif isinstance(item, dict) and "geometry" in item:
                    feats.append(
                        {
                            "type": "Feature",
                            "properties": {k: v for k, v in item.items() if k != "geometry"},
                            "geometry": item["geometry"],
                        }
                    )
            if feats:
                return {"type": "FeatureCollection", "features": feats}
    raise ValueError(f"Formato inesperado para {cve}: keys={list(data)[:8] if isinstance(data, dict) else type(data)}")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    features: list[dict] = []
    for i in range(1, 33):
        cve = f"{i:02d}"
        print(f"Descargando entidad {cve}…", flush=True)
        fc = fetch_entidad(cve)
        for feat in fc["features"]:
            props = feat.setdefault("properties", {})
            # Normalizar clave
            props["cve_ent"] = props.get("cve_ent") or props.get("CVE_ENT") or props.get("cvegeo") or cve
            if isinstance(props["cve_ent"], (int, float)):
                props["cve_ent"] = f"{int(props['cve_ent']):02d}"
            props["cve_ent"] = str(props["cve_ent"]).zfill(2)
            features.append(feat)
    collection = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(f"Escrito: {OUT} ({len(features)} features)")

    # Versión ligera para el repositorio / mapas del TFM
    try:
        import geopandas as gpd

        gdf = gpd.read_file(OUT)
        gdf["geometry"] = gdf.geometry.simplify(0.01, preserve_topology=True)
        light = OUT.with_name("entidades_federativas_simplificado.geojson")
        gdf.to_file(light, driver="GeoJSON")
        print(f"Escrito: {light} ({light.stat().st_size / 1e6:.2f} MB)")
    except ImportError:
        print("geopandas no disponible; omitiendo simplificado")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(exc, file=sys.stderr)
        sys.exit(1)
