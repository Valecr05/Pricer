"""
Línea de comandos.

    python -m sx_pricer --archivos "Z:/.../SX*.001" --params params.json -o reporte.html

Procesa todos los planos que encuentre, reutilizando el caché, y emite un reporte con
toda la serie embebida. El par de fechas a comparar se elige dentro del reporte;
`--t` y `--t1` solo fijan la selección con la que abre.

Códigos de salida:
    0  todo bien
    1  error de uso, o ningún archivo procesable
    2  el reporte se generó, pero hay controles de integridad fallidos
    3  el reporte se generó, pero hay errores de calidad de datos en el par elegido
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
import time
from pathlib import Path

from . import __version__, config as cfg, store
from .config import MarketParams
from .curves import analizar_tes, comparar_bloque
from .escenarios import Escenarios, EscenariosFormatError
from .ibr import FuenteIBR, IBRFormatError
from .loader import SXFormatError, read_sx
from .report import render
from .store import Serie
from .transform import build_valuation


def _fecha(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida: {s!r} (se espera AAAA-MM-DD)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sx-pricer",
        description="Convierte una serie de planos SX en un reporte HTML de curvas "
                    "donde el par de fechas a comparar se elige en pantalla.")
    p.add_argument("--archivos", nargs="+", metavar="RUTA", default=[],
                   help="planos SX; acepta comodines, por ejemplo \"Archivos Planos/SX*.001\"")
    p.add_argument("--t", type=_fecha, default=None, metavar="AAAA-MM-DD",
                   help="fecha de valoración con la que abre el reporte (por defecto, la última)")
    p.add_argument("--t1", type=_fecha, default=None, metavar="AAAA-MM-DD",
                   help="fecha de comparación con la que abre (por defecto, la anterior)")
    p.add_argument("--params", required=True, metavar="JSON",
                   help="parámetros de mercado")
    p.add_argument("-o", "--salida", default=None, metavar="HTML",
                   help="ruta del reporte (por defecto reporte_<fecha>.html)")
    p.add_argument("--cache", default=".sx-cache", metavar="CARPETA",
                   help="carpeta de resúmenes por fecha (por defecto .sx-cache)")
    p.add_argument("--sin-cache", action="store_true",
                   help="no leer ni escribir la carpeta de caché")
    p.add_argument("--rehacer", action="store_true",
                   help="reprocesar todo, ignorando lo que haya en caché")
    p.add_argument("--solo-cache", action="store_true",
                   help="no leer planos: armar el reporte con lo que ya está en caché")
    p.add_argument("--curvas", default=None, metavar="CARPETA",
                   help="carpeta con las curvas IND_IBR_AAAAMMDD.txt y la senda "
                        "histórica IB1.xlsx; sin ella no se calcula el margen IBR")
    p.add_argument("--ibr-historico", default=None, metavar="XLSX",
                   help="senda histórica diaria de IBR (por defecto, IB1.xlsx dentro "
                        "de la carpeta de curvas)")
    p.add_argument("--escenarios", default=None, metavar="XLSX",
                   help="sendas de proyección de IPC e IBR (por defecto, "
                        f"{cfg.NOMBRE_ESCENARIOS} dentro de la carpeta de curvas)")
    p.add_argument("--procesos", type=int, default=1, metavar="N",
                   help="procesar N archivos en paralelo (útil con historia larga)")
    p.add_argument("--csv", default=None, metavar="CARPETA",
                   help="exporta a CSV las tablas del par elegido, desde los planos")
    p.add_argument("--estricto", action="store_true",
                   help="aborta si un control de integridad falla")
    p.add_argument("--silencioso", action="store_true", help="no imprime progreso")
    p.add_argument("--version", action="version", version=f"sx-pricer {__version__}")
    return p


def _expandir(patrones: list[str]) -> list[Path]:
    """Resuelve comodines y ordena. El shell de Windows no expande, así que hay que
    hacerlo aquí."""
    rutas: list[Path] = []
    for patron in patrones:
        encontrados = [Path(x) for x in glob.glob(patron)]
        if encontrados:
            rutas.extend(sorted(encontrados))
        elif Path(patron).exists():
            rutas.append(Path(patron))
        else:
            print(f"Sin coincidencias para {patron!r}", file=sys.stderr)
    vistos, unicas = set(), []
    for r in rutas:
        clave = r.resolve()
        if clave not in vistos:
            vistos.add(clave)
            unicas.append(r)
    return unicas


def _exportar_csv(carpeta: Path, ruta_t: Path, ruta_t1: Path, params: MarketParams,
                  log) -> None:
    """Vuelve a leer los dos planos del par elegido y exporta las tablas."""
    carpeta.mkdir(parents=True, exist_ok=True)
    a_t, a_t1 = read_sx(ruta_t), read_sx(ruta_t1)
    v_t = build_valuation(a_t.data, fecha=a_t.fecha_val,
                          ipc=params.ipc_de(a_t.fecha_val), etiqueta="T")
    v_t1 = build_valuation(a_t1.data, fecha=a_t1.fecha_val,
                           ipc=params.ipc_de(a_t1.fecha_val), etiqueta="T-1")
    tes = analizar_tes(v_t1.data, v_t.data, nominal_dv01=params.nominal_dv01)
    tes.tabla.to_csv(carpeta / "tes.csv", index=False, sep=";", decimal=",")
    for spec in cfg.BLOCKS:
        for familia in spec.familias:
            res = comparar_bloque(v_t1.data, v_t.data, spec, familia,
                                  fecha_t=a_t.fecha_val, fecha_t1=a_t1.fecha_val)
            nombre = f"{spec.id}_{familia.replace(' ', '_').lower()}.csv"
            res.tabla.to_csv(carpeta / nombre, index=False, sep=";", decimal=",")
    v_t.data.to_csv(carpeta / "valoracion_t.csv", index=False, sep=";", decimal=",")
    log(f"CSV en {carpeta}/")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.silencioso else (lambda *a: print(*a, file=sys.stderr))
    t_ini = time.perf_counter()

    try:
        params = MarketParams.from_dict(json.loads(Path(args.params).read_text("utf-8")))
    except FileNotFoundError:
        print(f"No existe el archivo de parámetros: {args.params}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValueError, TypeError) as ex:
        print(f"Parámetros inválidos en {args.params}: {ex}", file=sys.stderr)
        return 1
    for aviso in params.avisos:
        log(f"  parámetros: {aviso}")

    try:
        fuente_ibr = FuenteIBR.cargar(args.curvas, args.ibr_historico)
    except IBRFormatError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    for aviso in fuente_ibr.avisos:
        log(f"  curvas IBR: {aviso}")
    if fuente_ibr.activa:
        from .ibr import nombres_descartados
        disponibles = fuente_ibr.fechas_curva
        if disponibles:
            listado = (", ".join(str(f) for f in disponibles) if len(disponibles) <= 14
                       else f"del {disponibles[0]} al {disponibles[-1]}")
            log(f"  curvas IBR: {len(disponibles)} archivo(s) · {listado}")
        else:
            log(f"  curvas IBR: no se encontró ningún IND_IBR_AAAAMMDD.txt en "
                f"{args.curvas}")
        ignorados = nombres_descartados(args.curvas)
        if ignorados:
            log("  curvas IBR: estos archivos se IGNORARON:")
            for nombre, motivo in ignorados:
                log(f"      {nombre}  ->  {motivo}")
        log(f"  curvas IBR: {len(fuente_ibr.historico)} día(s) de senda histórica")

    ruta_esc = args.escenarios
    if ruta_esc is None and args.curvas:
        candidata = Path(args.curvas) / cfg.NOMBRE_ESCENARIOS
        ruta_esc = str(candidata) if candidata.exists() else None
    try:
        escenarios = Escenarios.cargar(ruta_esc)
    except EscenariosFormatError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    if escenarios.activo:
        for nombre, senda in escenarios.sendas.items():
            log(f"  escenarios: {nombre} con {len(senda.fechas)} fechas, "
                f"hasta {senda.ultima}")
    else:
        log("  escenarios: sin archivo; la pestaña de rentabilidades esperadas "
            "quedará vacía")

    cache = None if args.sin_cache else Path(args.cache)

    if args.solo_cache:
        if cache is None:
            print("--solo-cache necesita una carpeta de caché.", file=sys.stderr)
            return 1
        resumenes = store.cargar_cache(cache)
        log(f"{len(resumenes)} fecha(s) leídas del caché")
        fallidos: list[tuple[str, str]] = []
        t_proceso = 0.0
    else:
        rutas = _expandir(args.archivos)
        if not rutas:
            print("No hay archivos por procesar. Usa --archivos con rutas o comodines, "
                  "o --solo-cache para armar el reporte con lo que ya está procesado.",
                  file=sys.stderr)
            return 1
        log(f"{len(rutas)} archivo(s) encontrados")
        proc = store.procesar(rutas, params=params, cache=cache,
                              fuente_ibr=fuente_ibr, rehacer=args.rehacer,
                              procesos=max(1, args.procesos), log=log)
        resumenes, fallidos, t_proceso = proc.resumenes, proc.fallidos, proc.segundos
        if cache is not None:
            # completar con fechas de corridas anteriores
            en_cache = {r["fecha"]: r for r in store.cargar_cache(cache)}
            en_cache.update({r["fecha"]: r for r in resumenes})
            resumenes = [en_cache[f] for f in sorted(en_cache)]

    if len(resumenes) < 2:
        print(f"Se necesitan al menos dos fechas para comparar; hay {len(resumenes)}.",
              file=sys.stderr)
        return 1

    serie = Serie(resumenes)
    try:
        f_t = serie.resolver(args.t, posicion=0)
        f_t1 = serie.resolver(args.t1, posicion=1)
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    if f_t1 >= f_t:
        print(f"T-1 ({f_t1}) debe ser anterior a T ({f_t}).", file=sys.stderr)
        return 1
    log(f"serie de {len(serie.fechas)} fecha(s): {serie.fechas[0]} a {serie.fechas[-1]}")
    log(f"abre comparando T {f_t} contra T-1 {f_t1}")

    integridad = [(r["fecha"], c) for r in resumenes for c in r["checks"] if not c["ok"]]
    for fecha, c in integridad:
        log(f"  control fallido en {fecha}: {c['nombre']} — {c['detalle']}")
    if integridad and args.estricto:
        print("Se abortó por --estricto.", file=sys.stderr)
        return 2

    tiempos = {"proceso": round(t_proceso, 2)}
    salida = Path(args.salida or f"reporte_{f_t.replace('-', '')}.html")
    tiempos["total"] = round(time.perf_counter() - t_ini, 2)
    salida.write_text(render(serie=serie, seleccion=(f_t1, f_t), params=params,
                             escenarios=escenarios, tiempos=tiempos,
                             version=__version__), encoding="utf-8")

    if args.csv:
        rutas_por_fecha = {r["fecha"]: r["archivo"] for r in resumenes}
        try:
            base = {p.name: p for p in _expandir(args.archivos)}
            _exportar_csv(Path(args.csv), base[rutas_por_fecha[f_t]],
                          base[rutas_por_fecha[f_t1]], params, log)
        except KeyError:
            print("Para exportar CSV hacen falta los planos de las dos fechas "
                  "elegidas en --archivos.", file=sys.stderr)

    tam = salida.stat().st_size / 1024
    log(f"Listo: {salida}  ({tam:.0f} KB, {len(serie.fechas)} fechas, "
        f"{tiempos['total']:.1f} s)")
    for nombre, error in fallidos:
        log(f"  archivo omitido: {nombre} — {error}")

    errores = {i["codigo"] for f in (f_t, f_t1)
               for i in serie.get(f)["issues"] if i["severidad"] == "error"}
    for cod in sorted(errores):
        log(f"  error de datos: {cod}")

    if integridad:
        return 2
    if errores:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
