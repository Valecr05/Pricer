"""
Resúmenes por fecha y caché incremental.

Un archivo SX pesa 82 MB y tarda unos seis segundos en procesarse. Para poder
comparar cualquier par de fechas de un año entero sin volver a leerlos todos, cada
archivo se reduce una sola vez a un **resumen**: los nodos de cada bloque y las
referencias de Nación, más los controles de integridad y las observaciones de
calidad. Son unos 5 KB por fecha, así que un año completo entra en un HTML de poco
más de un megabyte.

Lo que se guarda de cada nodo es la **tasa de valoración sin convertir**. El margen
real de los indexados se calcula después, en el navegador, con el IPC que el usuario
elija: el margen es una función afín de la tasa, así que promediar los márgenes de
los títulos de un nodo da lo mismo que aplicar la fórmula al promedio de sus tasas.

El caché se invalida por sí solo. Cada resumen recuerda el nombre, el tamaño y la
fecha de modificación del archivo que lo produjo, además de la versión del formato;
si algo de eso cambia, el archivo se vuelve a procesar. Añadir el plano de hoy a una
carpeta con un año de historia cuesta un solo archivo de trabajo.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as cfg
from .config import MarketParams
from .curves import _grupo_tes, anclas_mensuales, nodos_por_ventana, universo_tes
from .hpr import PAGOS_POR_ANIO, calendario_cupones, fecha_del_indice
from .ibr import FuenteIBR, margen_atajo
from .loader import SXFormatError, read_sx
from .transform import build_valuation

# Subir esta versión invalida todos los resúmenes en caché.
SUMMARY_VERSION = 10

# Campos del catálogo de instrumentos: no cambian entre fechas, así que se guardan
# una sola vez por ISIN en lugar de repetirse en cada resumen.
CATALOGO_CAMPOS = ("nemotecnico", "grupo", "moneda", "periodicidad",
                   "emision", "vencimiento", "cupon")


def vencimiento_del_nodo(fecha, dia_fin: int):
    """Vencimiento supuesto del CDT sintético de un nodo.

    Es el **último día de su ventana**. La ventana es semiabierta —`[desde, hasta)`,
    ver `curves.nodos_por_ventana`—, así que el último día en que un título puede
    vencer y aún contar en el nodo es `hasta − 1`, y `dia_fin` es el desplazamiento
    hasta `hasta`. Un rango que va del 28 de agosto al 27 de septiembre vence el 27
    de septiembre.

    Es la misma definición que usa la pestaña de rentabilidades esperadas, así que
    el margen y el HPR de un rango hablan del mismo instrumento.
    """
    return pd.Timestamp(fecha).date() + dt.timedelta(days=int(dia_fin) - 1)


def _n(x, dec: int | None = None):
    """Número listo para JSON: lo no finito viaja como null."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, dec) if dec is not None else v


def _i(x):
    v = _n(x)
    return None if v is None else int(v)


def _fecha(x) -> str | None:
    if x is None or x is pd.NaT:
        return None
    return pd.Timestamp(x).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------
# Construcción del resumen de una fecha
# ----------------------------------------------------------------------------

def resumir(path: str | Path, *, params: MarketParams,
            fuente_ibr: FuenteIBR | None = None) -> dict:
    """Procesa un plano SX y devuelve su resumen compacto."""
    t0 = time.perf_counter()
    path = Path(path)
    archivo = read_sx(path)
    fecha = archivo.fecha_val

    # El IPC solo se usa aquí para la duración al vencimiento de los indexados, que
    # es muy poco sensible a él. Los márgenes se calculan en el navegador.
    ipc = params.ipc_referencia
    val = build_valuation(archivo.data, fecha=fecha, ipc=ipc)

    # Curva del día hábil anterior, y la senda histórica para los períodos que ya
    # habían empezado al valorar.
    insumos_ibr = fuente_ibr.para_fecha(fecha) if fuente_ibr is not None else None
    motivo_ibr = (fuente_ibr.motivo_faltante(fecha) if fuente_ibr is not None
                  else "no se indicó carpeta de curvas")

    def margen_del_nodo(vencimiento, tir):
        if insumos_ibr is None or vencimiento is None or tir is None:
            return None
        curva, historico = insumos_ibr
        return margen_atajo(fecha_val=fecha, vencimiento=vencimiento,
                            tir=tir, historico=historico, curva=curva)

    # Rejilla mensual anclada en la propia fecha de valoración. Se guarda la del
    # bloque más largo; los demás usan sus primeros anclajes.
    meses_max = max(spec.meses for spec in cfg.BLOCKS)
    anclas = [_fecha(a) for a in anclas_mensuales(fecha, meses_max)]

    nodos: dict[str, dict] = {}
    for spec in cfg.BLOCKS:
        for familia in spec.familias:
            n = nodos_por_ventana(val.data, spec, familia, fecha)
            bruta = [_n(x) for x in n["tasa_bruta"]]
            bloque = {
                "dur": [_n(x, 6) for x in n["duracion"]],
                "cupon": [_n(x, 6) for x in n["cupon"]],
                # sin redondear: la tasa bruta es la base de todo lo que el
                # navegador recalcula, y json.dumps ya escribe la representación
                # más corta que vuelve al mismo float
                "bruta": bruta,
                "n": [int(x) for x in n["n"]],
            }
            if spec.margen_atajo:
                # El vencimiento supuesto es el último día de la ventana. La TIR es
                # la del propio nodo.
                bloque["margen"] = [
                    margen_del_nodo(vencimiento_del_nodo(fecha, fin), tir)
                    for fin, tir in zip(n["dia_fin"], bruta)
                ]
            nodos[f"{spec.id}|{familia}"] = bloque

    # Senda publicada que la pestaña de rentabilidades necesita. El cupón de cada
    # período se lee al inicio del período; el del primer cupón cae en o antes de la
    # valoración, así que es un dato publicado y sale de IB1.xlsx y no del archivo de
    # escenarios — la misma fuente contra la que se calcula el margen. En la práctica
    # todos los rangos comparten ese primer cupón, así que suele ser una sola fecha.
    publicada: dict[str, float] = {}
    if fuente_ibr is not None and fuente_ibr.historico:
        for spec in cfg.BLOCKS:
            if not spec.margen_atajo:
                continue
            pagos = PAGOS_POR_ANIO[spec.id]
            for ancla in anclas_mensuales(fecha, spec.meses)[1:]:
                venc = vencimiento_del_nodo(fecha, (ancla.date() - fecha).days)
                cupones = calendario_cupones(venc, fecha, pagos)
                if not cupones:
                    continue
                inicio = fecha_del_indice(cupones[0], 12 // pagos)
                if inicio <= fecha and inicio in fuente_ibr.historico:
                    publicada[inicio.isoformat()] = _n(fuente_ibr.historico[inicio])

    u = universo_tes(val.data).copy()
    u["grupo"] = _grupo_tes(u["nemotecnico"])
    u = u[~u["isin"].duplicated()].sort_values("dias")
    catalogo = {
        r.isin: {
            "nemotecnico": r.nemotecnico, "grupo": r.grupo, "moneda": r.moneda,
            "periodicidad": r.periodicidad, "emision": _fecha(r.emision),
            "vencimiento": _fecha(r.vencimiento), "cupon": _n(r.cupon, 4),
        }
        for r in u.itertuples()
    }
    tes = {
        "isin": u["isin"].tolist(),
        "dias": [_i(x) for x in u["dias"]],
        "dur": [_n(x, 6) for x in u["duracion"]],
        "dm": [_n(x, 6) for x in u["dm"]],
        "precio": [_n(x, 6) for x in u["precio_sucio"]],
        "bruta": [_n(x) for x in u["tasa_bruta"]],
    }

    st = path.stat()
    return {
        "version": SUMMARY_VERSION,
        "fecha": _fecha(fecha),
        "archivo": path.name,
        "archivo_bytes": st.st_size,
        "archivo_mtime": int(st.st_mtime),
        "n_registros": archivo.n_registros,
        "n_universo": val.n_final,
        "ipc_duracion": ipc,
        "ibr": {
            "huella": fuente_ibr.huella(fecha) if fuente_ibr is not None else "sin-curvas",
            "previo": _n(fuente_ibr.previo(fecha)) if fuente_ibr is not None else None,
            # el margen se calcula con la curva del día hábil anterior
            "curva_usada": (_fecha(fuente_ibr.fecha_curva_usada(fecha))
                            if fuente_ibr is not None else None),
            # lecturas publicadas que necesita la pestaña de rentabilidades
            "historico": publicada,
            "motivo": motivo_ibr,
        },
        "cinta": archivo.raw_primer_registro,
        "anclas": anclas,
        "integridad_ok": archivo.integridad_ok,
        "checks": [{"nombre": c.nombre, "ok": bool(c.ok), "detalle": c.detalle}
                   for c in archivo.checks],
        "exclusiones": [{"id": x.id, "label": x.label, "filas": x.filas}
                        for x in val.exclusiones],
        "issues": [{"severidad": i.severidad, "codigo": i.codigo, "mensaje": i.mensaje,
                    "filas": i.filas, "muestra": [str(m) for m in i.muestra]}
                   for i in val.issues],
        "catalogo": catalogo,
        "nodos": nodos,
        "tes": tes,
        "segundos": round(time.perf_counter() - t0, 2),
    }


# ----------------------------------------------------------------------------
# Caché en disco
# ----------------------------------------------------------------------------

def _ruta_cache(carpeta: Path, fecha: str) -> Path:
    return carpeta / f"{fecha}.json"


def _sirve(resumen: dict, path: Path, ipc: float, huella_ibr: str) -> bool:
    """Un resumen sirve si el plano no cambió y los insumos de IBR son los mismos.

    La huella incluye el archivo de curva y el IBR previo de esa fecha, así que
    agregar la curva de un día ya procesado lo vuelve a procesar solo a él.
    """
    try:
        st = path.stat()
    except OSError:
        return False
    return (resumen.get("version") == SUMMARY_VERSION
            and resumen.get("archivo") == path.name
            and resumen.get("archivo_bytes") == st.st_size
            and resumen.get("archivo_mtime") == int(st.st_mtime)
            and _n(resumen.get("ipc_duracion"), 10) == _n(ipc, 10)
            and (resumen.get("ibr") or {}).get("huella") == huella_ibr)


def _buscar_en_cache(carpeta: Path, path: Path, ipc: float,
                     fuente_ibr: FuenteIBR | None) -> dict | None:
    """Busca un resumen válido para este archivo sin abrirlo."""
    if not carpeta.is_dir():
        return None
    for candidato in carpeta.glob("*.json"):
        try:
            resumen = json.loads(candidato.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if resumen.get("archivo") != path.name:
            continue
        fecha = resumen.get("fecha")
        if not fecha:
            continue
        huella = (fuente_ibr.huella(dt.date.fromisoformat(fecha))
                  if fuente_ibr is not None else "sin-curvas")
        if _sirve(resumen, path, ipc, huella):
            return resumen
    return None


@dataclass
class Procesado:
    resumenes: list[dict] = field(default_factory=list)
    reutilizados: int = 0
    nuevos: int = 0
    fallidos: list[tuple[str, str]] = field(default_factory=list)
    segundos: float = 0.0


def _trabajo(args) -> tuple[str, dict | None, str | None]:
    """Función de nivel de módulo para que sea utilizable con multiprocessing."""
    ruta, params_dict, fuente_ibr = args
    try:
        resumen = resumir(ruta, params=MarketParams.from_dict(params_dict),
                          fuente_ibr=fuente_ibr)
        return str(ruta), resumen, None
    except (SXFormatError, FileNotFoundError, ValueError) as ex:
        return str(ruta), None, str(ex)


def procesar(rutas, *, params: MarketParams, cache: Path | None,
             fuente_ibr: FuenteIBR | None = None,
             rehacer: bool = False, procesos: int = 1, log=lambda *a: None) -> Procesado:
    """Procesa una lista de planos reutilizando el caché y lo actualiza.

    Devuelve los resúmenes ordenados por fecha. Un archivo ilegible no aborta la
    corrida: queda registrado en `fallidos`.
    """
    t0 = time.perf_counter()
    out = Procesado()
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    pendientes = []
    for ruta in rutas:
        ruta = Path(ruta)
        ipc = params.ipc_referencia
        if not rehacer and cache is not None:
            previo = _buscar_en_cache(cache, ruta, ipc, fuente_ibr)
            if previo is not None:
                out.resumenes.append(previo)
                out.reutilizados += 1
                continue
        pendientes.append(ruta)

    if pendientes:
        log(f"  {len(pendientes)} archivo(s) por procesar, "
            f"{out.reutilizados} desde caché")
        pd_ = params.to_dict()
        tareas = [(r, pd_, fuente_ibr) for r in pendientes]
        if procesos > 1 and len(tareas) > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=procesos) as pool:
                resultados = list(pool.map(_trabajo, tareas))
        else:
            resultados = [_trabajo(t) for t in tareas]

        for ruta, resumen, error in resultados:
            nombre = Path(ruta).name
            if error is not None:
                log(f"  no se pudo procesar {nombre}: {error}")
                out.fallidos.append((nombre, error))
                continue
            out.resumenes.append(resumen)
            out.nuevos += 1
            info_ibr = resumen.get("ibr") or {}
            motivo = info_ibr.get("motivo")
            if motivo is not None:
                nota = f" · sin margen IBR: {motivo}"
            elif info_ibr.get("curva_usada"):
                nota = f" · margen con la curva del {info_ibr['curva_usada']}"
            else:
                nota = ""
            log(f"  {nombre} -> {resumen['fecha']} "
                f"({resumen['n_universo']:,} títulos, {resumen['segundos']} s)"
                .replace(",", ".") + nota)
            if cache is not None:
                _ruta_cache(cache, resumen["fecha"]).write_text(
                    json.dumps(resumen, separators=(",", ":"), ensure_ascii=False),
                    encoding="utf-8")

    # Una misma fecha en dos archivos: gana el que se procesó de último.
    por_fecha = {r["fecha"]: r for r in out.resumenes}
    out.resumenes = [por_fecha[f] for f in sorted(por_fecha)]
    out.segundos = time.perf_counter() - t0
    return out


def cargar_cache(carpeta: Path) -> list[dict]:
    """Lee todos los resúmenes de una carpeta de caché, ordenados por fecha."""
    if not carpeta.is_dir():
        return []
    fuera = []
    for archivo in sorted(carpeta.glob("*.json")):
        try:
            resumen = json.loads(archivo.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if resumen.get("version") == SUMMARY_VERSION and resumen.get("fecha"):
            fuera.append(resumen)
    por_fecha = {r["fecha"]: r for r in fuera}
    return [por_fecha[f] for f in sorted(por_fecha)]


# ----------------------------------------------------------------------------
# Serie de fechas lista para el reporte
# ----------------------------------------------------------------------------

@dataclass
class Serie:
    resumenes: list[dict]

    @property
    def fechas(self) -> list[str]:
        return [r["fecha"] for r in self.resumenes]

    def get(self, fecha: str) -> dict:
        for r in self.resumenes:
            if r["fecha"] == fecha:
                return r
        raise KeyError(fecha)

    @property
    def catalogo(self) -> dict:
        """Catálogo de instrumentos unificado. Las fechas recientes ganan."""
        out: dict = {}
        for r in self.resumenes:
            out.update(r.get("catalogo", {}))
        return out

    def para_json(self) -> dict:
        """Payload que se embebe en el HTML.

        Se saca del resumen de cada fecha todo lo que se repite igual en todas: el
        catálogo de instrumentos, los mensajes de calidad y las etiquetas de las
        exclusiones. Con un año de historia eso ahorra cerca de un 20 % del archivo.
        """
        mensajes: dict[str, str] = {}
        etiquetas: dict[str, str] = {}
        por_fecha: dict[str, dict] = {}

        for r in self.resumenes:
            liviano = {k: v for k, v in r.items() if k not in ("catalogo", "issues",
                                                               "exclusiones")}
            liviano["issues"] = []
            for i in r.get("issues", []):
                mensajes[i["codigo"]] = i["mensaje"]
                liviano["issues"].append({"sev": i["severidad"], "cod": i["codigo"],
                                          "filas": i["filas"], "muestra": i["muestra"]})
            liviano["exclusiones"] = []
            for x in r.get("exclusiones", []):
                etiquetas[x["id"]] = x["label"]
                liviano["exclusiones"].append({"id": x["id"], "filas": x["filas"]})
            por_fecha[r["fecha"]] = liviano

        return {"fechas": self.fechas, "catalogo": self.catalogo,
                "mensajes": mensajes, "etiquetas": etiquetas, "porFecha": por_fecha}

    def resolver(self, pedido: str | dt.date | None, *, posicion: int) -> str:
        """Traduce lo que pidió el usuario a una fecha disponible.

        `posicion` es el índice contando desde el final: 0 es la última fecha
        disponible y 1 la anterior.
        """
        if not self.fechas:
            raise ValueError("no hay fechas procesadas")
        if pedido is None:
            idx = max(0, len(self.fechas) - 1 - posicion)
            return self.fechas[idx]
        texto = pedido if isinstance(pedido, str) else pedido.isoformat()
        if texto in self.fechas:
            return texto
        disponibles = ", ".join(self.fechas[-8:])
        raise ValueError(f"la fecha {texto} no está procesada. "
                         f"Últimas disponibles: {disponibles}")
