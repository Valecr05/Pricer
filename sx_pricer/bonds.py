"""
Duración de Macaulay al vencimiento.

El proveedor reporta, en los títulos indexados, la sensibilidad hasta el próximo
corte de cupón y no hasta el vencimiento: en los IPC con más de 2 años al
vencimiento la duración que envía es el 1,6 % del plazo, contra el 89 % en tasa
fija. Este módulo la calcula al vencimiento a partir del flujo de caja.

Convenciones, determinadas empíricamente contra los títulos de tasa fija del
archivo del 28-jul-2026, donde la duración del proveedor sí es al vencimiento:

  - `PV` y `NO` son pago único al vencimiento y su duración es exactamente el
    plazo: la diferencia contra el proveedor es de 3e-5 años en la mediana.
  - `MV`, `BV`, `TV`, `SV` y `AV` pagan cupón vencido cada 1, 2, 3, 6 y 12 meses.
    El cupón facial es **nominal**, no efectivo anual: el cupón del período es
    `facial · meses / 12`. Con esa convención el precio teórico reproduce el
    precio sucio del proveedor con un error mediano de 0,03. Con la convención
    efectiva anual el error sube a 0,73.
  - El calendario se ancla en el vencimiento y se cuenta hacia atrás en múltiplos
    exactos de meses. Restar el plazo de un cupón repetidamente, en cambio,
    arrastra el día del mes: un vencimiento el 31 de agosto pasa por un 28 de
    febrero y se queda en 28 para siempre.
  - Se descuenta a la tasa de valoración del propio archivo, base ACT/365.

Validación sobre 4.000 títulos de tasa fija con cupón tomados al azar: diferencia
mediana de 0,00003 años contra el proveedor y de 0,0046 en el percentil 99.

En los títulos IPC el cupón proyectado es `IPC + facial`, que ajusta el precio del
proveedor mejor que `(1+IPC)·(1+facial)−1` (error mediano 0,63 contra 1,71). La
duración es poco sensible a esa elección: 4,162 contra 4,143 años en la mediana.

En los indexados a una tasa de corto plazo (IBR, DTF) el cupón proyectado es la
propia tasa de valoración, porque cotizan a la par. Ver INDEXADOS_CORTO_PLAZO.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Meses entre pagos de cupón. Los códigos ausentes son pago único al vencimiento.
MESES_POR_CUPON: dict[str, int] = {"MV": 1, "BV": 2, "TV": 3, "SV": 6, "AV": 12}

# Índices cuyo cupón facial es un spread sobre la inflación: el cupón proyectado
# es IPC + facial.
INDEXADOS_IPC = ("IPC", "ICP", "IP4")

# Indexados a una tasa de mercado de corto plazo. Su cupón se repone en cada corte
# y cotizan muy cerca de la par (precio sucio entre 100,3 y 101,6 en el archivo del
# 28-jul-2026), así que el cupón proyectado es su propia tasa de valoración. Con esa
# proyección el precio teórico reproduce el del proveedor con un error mediano de
# 0,36; proyectando solo el spread facial el error es de 11 puntos de precio.
INDEXADOS_CORTO_PLAZO = ("IB1", "IB3", "DTF", "DTE")

_LLAVES = ["vencimiento", "fecha_val", "periodicidad"]


def calendario(vencimiento: pd.Timestamp, fecha_val: pd.Timestamp,
               meses: int) -> np.ndarray:
    """Tiempos, en años ACT/365, de los cupones que faltan por pagar.

    El vector va en orden ascendente y su último elemento es el vencimiento.
    """
    dias = (vencimiento - fecha_val).days
    if dias <= 0:
        return np.empty(0)
    n = int(np.ceil(dias / 365.0 * 12.0 / meses)) + 1
    fechas = [vencimiento - pd.DateOffset(months=meses * k) for k in range(n)]
    t = np.array(sorted((f - fecha_val).days for f in fechas), dtype="float64") / 365.0
    return t[t > 0]


def _duracion_bloque(t: np.ndarray, cupon_anual: np.ndarray, tasa: np.ndarray,
                     meses: int) -> np.ndarray:
    """Duración de varios títulos que comparten el mismo calendario."""
    cupon_periodo = (cupon_anual * meses / 12.0)[:, None]
    descuento = (1.0 + tasa[:, None]) ** (-t[None, :])
    vp = 100.0 * cupon_periodo * descuento
    vp[:, -1] += 100.0 * descuento[:, -1]          # amortización al vencimiento
    total = vp.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        dur = (vp * t[None, :]).sum(axis=1) / total
    return np.where(total > 0, dur, np.nan)


def duracion_al_vencimiento(df: pd.DataFrame, *, ipc: float) -> pd.Series:
    """Duración de Macaulay al vencimiento, en años, para cada fila.

    Los títulos de pago único se resuelven de forma vectorizada: su duración es el
    plazo. Para los que pagan cupón, el calendario se calcula una sola vez por
    combinación de vencimiento, fecha de valoración y periodicidad (4.513
    combinaciones en un archivo de 300.000 títulos) y sobre cada calendario se
    descuentan de golpe todos los pares de cupón y tasa que lo comparten.
    """
    plazo = (df["vencimiento"] - df["fecha_val"]).dt.days / 365.0
    out = pd.Series(np.where(plazo > 0, plazo, np.nan), index=df.index, dtype="float64")

    con_cupon = df["periodicidad"].isin(MESES_POR_CUPON) & (plazo > 0)
    if not con_cupon.any():
        return out

    sub = df[con_cupon]
    cupon = sub["cupon"] / 100.0
    tasa = sub["tasa_val"] / 100.0
    proyectado = np.where(
        sub["indicador"].isin(INDEXADOS_IPC), ipc + cupon,
        np.where(sub["indicador"].isin(INDEXADOS_CORTO_PLAZO), tasa, cupon))

    llave = pd.DataFrame({
        "vencimiento": sub["vencimiento"],
        "fecha_val": sub["fecha_val"],
        "periodicidad": sub["periodicidad"],
        "cupon": np.round(proyectado, 10),
        "tasa": np.round(tasa, 10),
    })

    unicos = llave.drop_duplicates().reset_index(drop=True)
    cupones = unicos["cupon"].to_numpy()
    tasas = unicos["tasa"].to_numpy()
    dur = np.full(len(unicos), np.nan)

    for (vto, fval, per), pos in unicos.groupby(_LLAVES, sort=False).indices.items():
        t = calendario(vto, fval, MESES_POR_CUPON[per])
        if len(t):
            dur[pos] = _duracion_bloque(t, cupones[pos], tasas[pos],
                                        MESES_POR_CUPON[per])

    unicos["_dur"] = dur
    calculada = llave.merge(unicos, how="left", on=list(llave.columns))["_dur"]
    out.loc[llave.index] = calculada.to_numpy()
    return out
