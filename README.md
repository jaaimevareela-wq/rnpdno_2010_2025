# Desapariciones en México: mapas y cifras abiertas (2010–2024)

Este sitio reúne **gráficas y mapas** hechos a partir del **Registro Nacional de Personas Desaparecidas y No Localizadas (RNPDNO)** — la fuente oficial del gobierno federal.

Está pensado para **familias, colectivos de búsqueda y cualquier persona** que quiera entender, con datos públicos, cómo se reparten las desapariciones entre estados y en el tiempo.

**Autor del proyecto:** Jaime Adrian Arreola Varela  
**Repositorio:** https://github.com/jaaimevareela-wq/rnpdno_2010_2025

> El trabajo académico completo (TFM para tutores) **no está aquí**. Solo lo que sirve para consultar y verificar cifras y mapas.

---

## Empieza aquí

1. Lee la **[guía en lenguaje sencillo](docs/GUIA.md)** — qué muestran los mapas, qué no significan y de dónde salen los datos.
2. Mira las **imágenes** en la carpeta [`output/figures/`](output/figures/).

### Mapas y gráficas principales

| Archivo | Qué muestra |
|---------|-------------|
| [`atlas_mapa_observado_2024.png`](output/figures/atlas_mapa_observado_2024.png) | Mapa de México 2024 según el RNPDNO (lo que el registro oficial muestra) |
| [`atlas_mapa_tasa_2024.png`](output/figures/atlas_mapa_tasa_2024.png) | Misma información en tasas por cada 100.000 habitantes |
| [`serie_nacional_2010_2024.png`](output/figures/serie_nacional_2010_2024.png) | Evolución nacional año por año |
| [`serie_nacional_sexo_2010_2024.png`](output/figures/serie_nacional_sexo_2010_2024.png) | Reparto por sexo en el registro |
| [`serie_nacional_edad_2010_2024.png`](output/figures/serie_nacional_edad_2010_2024.png) | Reparto por edad en el registro |
| [`heatmap_riesgo_estatal.png`](output/figures/heatmap_riesgo_estatal.png) | Comparación entre estados a lo largo del tiempo |

Las tablas con números (CSV) están en [`output/tables/`](output/tables/).

---

## Importante

- Los datos vienen del **RNPDNO**. No incluyen todos los casos que existen en la realidad: dependen de denuncias, registros y actualización de expedientes.
- Los mapas **no señalan culpables** ni sustituyen la investigación de cada caso.
- **No deben usarse** para señalar o vigilar barrios o personas.
- Si citas una cifra, indica **fuente: RNPDNO** y la fecha de consulta del proyecto.

Más detalle en [`docs/GUIA.md`](docs/GUIA.md).

---

## Para quien quiera reproducir los cálculos

Hay scripts en Python para volver a generar tablas y figuras a partir de fuentes públicas (RNPDNO, CONEVAL, SESNSP). Requiere conocimientos de análisis de datos.

```bash
pip3 install -r requirements.txt
python3 fetch_external_data.py
python3 build_state_panel.py
python3 analysis/01_descriptivos_nacionales.py
python3 analysis/02_edad_nacional.py
python3 fetch_inegi_geo.py
python3 analysis/03_atlas_mapas.py
```

La extracción del RNPDNO (`scrape_panel.py`) no está versionada porque pesa mucho; se puede regenerar siguiendo el código.

---

## Fuentes

- [RNPDNO — Comisión Nacional de Búsqueda](https://versionpublicarnpdno.segob.gob.mx/)
- [CONEVAL](https://www.coneval.org.mx) (pobreza)
- [SESNSP](https://www.gob.mx/sesnsp) (delitos de alto impacto)
- [INEGI](https://www.inegi.org.mx) (población y mapas)
