"""Reporte de prueba con datos inventados.

Casi todas las pruebas de interfaz dependían de tener a mano los planos SX de
referencia, que no se versionan. Donde no están, esas pruebas se saltan — y así fue
como llegó a producirse un reporte cuyos paneles salían en blanco: la interfaz nunca
se había ejecutado. Este módulo fabrica una `Serie` con la misma forma que la real
—los tres bloques, sus familias, la rejilla mensual completa, el universo TES, la
senda de IBR y las tres sendas de proyección— para que el reporte se pueda armar y
abrir en un DOM en cualquier máquina.

Los números no significan nada: son curvas suaves y monótonas. Lo que se comprueba
contra ellos es que la pantalla se dibuja y reacciona, no cuánto vale un nodo.
"""
from __future__ import annotations

import datetime as dt
import math

from sx_pricer import config as cfg
from sx_pricer.config import MarketParams
from sx_pricer.curves import anclas_mensuales
from sx_pricer.escenarios import ESCENARIOS, Escenarios, Senda
from sx_pricer.store import SUMMARY_VERSION, Serie

FECHAS = ("2026-08-28", "2026-08-31")
IPC_POR_FECHA = {"2026-08-28": 0.0533, "2026-08-31": 0.0541}


def _resumen(fecha_iso: str, sesgo: float) -> dict:
    """Un resumen de fecha con la misma forma que el que produce `store.procesar`."""
    fecha = dt.date.fromisoformat(fecha_iso)
    meses_max = max(b.meses for b in cfg.BLOCKS)
    anclas = [a.date().isoformat() for a in anclas_mensuales(fecha, meses_max)]

    nodos: dict[str, dict] = {}
    for spec in cfg.BLOCKS:
        for i, familia in enumerate(spec.familias):
            base = 0.09 + 0.002 * i + sesgo
            bruta = [base + 0.004 * math.log1p(j) for j in range(spec.meses)]
            bloque = {"dur": [round(0.2 + j * 0.08, 6) for j in range(spec.meses)],
                      "cupon": [round(0.05 + 0.001 * j, 6) for j in range(spec.meses)],
                      "bruta": bruta,
                      "n": [12 + (j % 5) for j in range(spec.meses)]}
            if spec.margen_atajo:
                bloque["margen"] = [round(0.015 + 0.0005 * j + sesgo, 4)
                                    for j in range(spec.meses)]
            nodos[f"{spec.id}|{familia}"] = bloque

    # La senda de IBR: histórico hasta la valoración y curva forward después. El
    # precio de entrada lee ambas, así que tienen que cubrir todos los cupones.
    historico, curva = {}, {}
    dia = fecha - dt.timedelta(days=400)
    while dia < fecha + dt.timedelta(days=1_300):
        (historico if dia <= fecha else curva)[dia.isoformat()] = round(0.0925 + sesgo, 6)
        dia += dt.timedelta(days=1)

    catalogo, tes = {}, {"isin": [], "dias": [], "dur": [], "dm": [], "precio": [],
                         "bruta": []}
    # Doce referencias en pesos y seis en UVR: la gráfica traza una curva por
    # moneda y por fecha, así que las dos monedas tienen que estar representadas. El
    # grupo lo deduce el reporte del prefijo del nemotécnico, no de este campo.
    for grupo, nemo, cuantas in (("COP", "TFIT16", 12), ("UVR", "TUVT10", 6)):
        for j in range(cuantas):
            isin = f"CO{grupo}00000{j:03d}"
            catalogo[isin] = {
                "nemotecnico": f"{nemo}{j:02d}0630", "grupo": grupo,
                "moneda": "COP" if grupo == "COP" else "UVR", "periodicidad": "TV",
                "emision": (fecha - dt.timedelta(days=900)).isoformat(),
                "vencimiento": (fecha + dt.timedelta(days=200 + 400 * j)).isoformat(),
                "cupon": 0.07}
            tes["isin"].append(isin)
            tes["dias"].append(200 + 400 * j)
            tes["dur"].append(round(0.5 + j * 0.9, 6))
            tes["dm"].append(round(0.45 + j * 0.85, 6))
            tes["precio"].append(round(100 + j * 0.4, 6))
            tes["bruta"].append(0.085 + 0.002 * j + sesgo)

    return {
        "version": SUMMARY_VERSION, "fecha": fecha_iso, "archivo": f"SX_{fecha_iso}.txt",
        "archivo_bytes": 270_000, "archivo_mtime": 0, "n_registros": 1_000,
        "n_universo": 800, "ipc_duracion": 0.0614,
        "ibr": {"huella": "sintetica", "previo": 0.0925, "curva_usada": fecha_iso,
                "historico": historico, "curva": curva, "motivo": ""},
        "cinta": "X" * 270, "anclas": anclas, "integridad_ok": True,
        "checks": [{"nombre": "registros", "ok": True, "detalle": "1000"}],
        "exclusiones": [{"id": "sin_precio", "label": "Sin precio", "filas": 3}],
        "issues": [{"severidad": "aviso", "codigo": "prueba",
                    "mensaje": "Aviso de ejemplo", "filas": 2, "muestra": ["a"]}],
        "catalogo": catalogo, "nodos": nodos, "tes": tes, "segundos": 0.1,
    }


def _senda(nombre: str, base: float, pendiente: float) -> Senda:
    """Sesenta meses de senda, con los tres escenarios abriéndose en abanico."""
    fechas, valores = [], {e: [] for e in ESCENARIOS}
    for j in range(60):
        anios, mes = divmod(7 + j, 12)          # arranca en agosto de 2026
        fechas.append(dt.date(2026 + anios, mes + 1, 28))
        for k, escenario in enumerate(ESCENARIOS):
            valores[escenario].append(round(base + pendiente * j + 0.004 * (k - 1), 6))
    return Senda(nombre, fechas, valores)


def serie() -> Serie:
    return Serie([_resumen(FECHAS[0], 0.0), _resumen(FECHAS[1], 0.0007)])


def params() -> MarketParams:
    return MarketParams(ipc_referencia=0.0614, tasa_br=0.0925,
                        ipc_por_fecha=dict(IPC_POR_FECHA))


def escenarios() -> Escenarios:
    return Escenarios({"IPC": _senda("IPC", 0.053, 0.0004),
                       "IBR": _senda("IBR", 0.0925, -0.0003)},
                      origen="sintetico")


def html(*, con_escenarios: bool = True) -> str:
    from sx_pricer.report import render
    return render(serie=serie(), seleccion=FECHAS, params=params(),
                  tiempos={"total": 1.0}, version="prueba",
                  escenarios=escenarios() if con_escenarios else None)
