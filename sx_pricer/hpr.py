"""
Rentabilidad esperada (holding period return) de un CDT sintético por rango.

Cada ventana de la rejilla se trata como un CDT independiente que vence al final
de la ventana. No se promedia ni se interpola entre rangos.

  - **Calendario**: hacia atrás desde el vencimiento, en pasos de 12/pagos meses,
    conservando las fechas posteriores a la valoración. El primer cupón es de
    período completo: se cobra entero, y por eso V₀ es precio sucio.
  - **Cupón del período**, por tipo:
        TF    cupón_T / pagos
        IPC   ((1 + IPC(inicio del período)) × (1 + cupón_T))^(1/4) − 1
        IBR   (IBR(inicio del período) + cupón_T) / 12
    En los dos índices la tasa se lee al **inicio del período** y no en su pago: un
    cupón trimestral del 25 de agosto de 2026 usa el IPC de mayo de 2026, y uno
    mensual del 27 de agosto usa el IBR del 27 de julio.
  - **Tasa de descuento**, recompuesta desde el margen y el índice:
        TF    TIR(T)
        IPC   (1 + margen) × (1 + IPC) − 1
        IBR   (1 + (IBR + margen) / 12)^12 − 1
  - **V₀**: los cupones descontados con la tasa recompuesta con el índice de hoy,
    que es la TIR del nodo. Cómo se proyectan esos cupones depende del tipo, ver
    `V0_CON_ESCENARIO`: en IBR se aplana la senda al índice de hoy y V₀ sale igual
    en los tres escenarios; en IPC cada cupón lee el índice tres meses antes de su
    propio pago, también más allá de la valoración, así que V₀ cambia con el
    escenario.
  - **V₁** en el día h: los flujos posteriores, proyectados con el escenario y
    descontados desde h con la tasa recompuesta usando el índice proyectado en
    T+h y el margen desplazado por el delta.
  - **HPR**: XIRR sobre −V₀ en el día 0, los cupones cobrados en sus días y +V₁ en
    el día h, en base ACT/365.

Que entrada y salida usen la misma construcción es lo que hace el resultado
consistente: con la senda del índice plana y delta cero, el HPR devuelve
exactamente la tasa de entrada.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

from .escenarios import Escenarios

HORIZONTES = (90, 180)           # el tercero es el vencimiento

# Tipos cuyo precio de entrada se proyecta con la senda del escenario elegido, en
# vez de aplanarla al índice de hoy. Es una decisión de negocio, no una propiedad
# del método: en IPC el cupón de cada período se lee tres meses antes de su pago
# también más allá de la valoración, así que V₀ —y con él el precio de entrada—
# cambia con el escenario. En IBR el precio de entrada sigue siendo plano.
V0_CON_ESCENARIO = frozenset({"ipc"})
PAGOS_POR_ANIO = {"fs": 4, "ipc": 4, "ibr": 12}
INDICE_DE = {"ipc": "IPC", "ibr": "IBR"}

# Newton-Raphson para el XIRR
SEMILLA = 0.10
TOLERANCIA = 1e-11
MAX_ITER = 300


def menos_meses(fecha: dt.date, meses: int) -> dt.date:
    """Resta meses conservando el día, recortado al último día del mes destino."""
    total = fecha.year * 12 + (fecha.month - 1) - meses
    anio, mes = divmod(total, 12)
    dia = min(fecha.day, calendar.monthrange(anio, mes + 1)[1])
    return dt.date(anio, mes + 1, dia)


def calendario_cupones(vencimiento: dt.date, fecha_val: dt.date,
                       pagos_por_anio: int) -> list[dt.date]:
    """Fechas de cupón posteriores a la valoración, ancladas en el vencimiento."""
    paso = 12 // pagos_por_anio
    fechas: list[dt.date] = []
    k = 0
    while True:
        f = menos_meses(vencimiento, paso * k)
        if f <= fecha_val:
            break
        fechas.append(f)
        k += 1
    fechas.reverse()
    return fechas


def xirr(flujos: list[tuple[float, float]]) -> float | None:
    """Tasa efectiva anual que anula el valor presente, base ACT/365."""
    r = SEMILLA
    for _ in range(MAX_ITER):
        f = df = 0.0
        for dia, c in flujos:
            t = dia / 365.0
            f += c * (1 + r) ** (-t)
            df += -c * t * (1 + r) ** (-t - 1)
        if abs(df) < 1e-14:
            return None
        nuevo = r - f / df
        if nuevo <= -0.999:
            nuevo = (r - 0.999) / 2
        if abs(nuevo - r) < TOLERANCIA:
            return nuevo
        r = nuevo
    return None


@dataclass
class ResultadoHPR:
    horizonte: int          # el pedido: 90, 180 o los días al vencimiento
    dias: int               # el efectivamente usado
    hpr: float | None
    v0: float
    v1: float
    tasa_entrada: float
    tasa_salida: float
    cupones: int
    al_vencimiento: bool    # el rango vence antes del horizonte pedido
    extrapolado: bool


def tasa_descuento(tipo: str, tir: float, margen: float, indice: float) -> float:
    if tipo == "fs":
        return tir
    if tipo == "ipc":
        return (1 + margen) * (1 + indice) - 1
    return (1 + (indice + margen) / 12) ** 12 - 1


def _cupon(tipo: str, cupon_facial: float, indice: float, pagos: int) -> float:
    """Cupón del período. En IPC el exponente es la fracción fija 1/pagos."""
    if tipo == "fs":
        return cupon_facial / pagos
    if tipo == "ipc":
        return ((1 + indice) * (1 + cupon_facial)) ** (1 / pagos) - 1
    return (indice + cupon_facial) / pagos


def fecha_del_indice(fecha_cupon: dt.date, paso: int, fecha_val: dt.date,
                     plano: bool) -> dt.date:
    """Con qué fecha se lee el índice del cupón que se paga en `fecha_cupon`.

    Se toma el índice del **inicio del período**, un paso antes del pago, tanto en
    IPC como en IBR: un cupón trimestral del 25 de agosto de 2026 usa el IPC de mayo
    de 2026, y uno mensual del 27 de agosto usa el IBR vigente el 27 de julio. Es la
    misma convención del atajo de la bvc, donde la tasa se lee al inicio del período
    y no en su pago.

    En el primer cupón el inicio del período siempre cae en o antes de la fecha de
    valoración, así que ahí el índice es un dato publicado y no una proyección.

    En modo plano, el que sostiene V₀, cualquier fecha posterior a la valoración se
    reemplaza por la de valoración: así el precio de entrada no depende del escenario.
    Las anteriores se dejan como están, por lo mismo de arriba.

    Esto rige solo la **tasa cupón**. La tasa de descuento sigue usando el índice de
    hoy en la entrada y el proyectado en T+h en la salida.
    """
    base = menos_meses(fecha_cupon, paso)
    return fecha_val if (plano and base > fecha_val) else base


def _flujos(tipo: str, fechas: list[dt.date], vencimiento: dt.date,
            fecha_val: dt.date, cupon_facial: float, escenarios: Escenarios | None,
            escenario: str, plano: bool) -> tuple[list[tuple[dt.date, float]], bool]:
    """Flujos del título. `plano` proyecta todo con el índice de hoy."""
    pagos = PAGOS_POR_ANIO[tipo]
    paso = 12 // pagos
    senda = None if tipo == "fs" else escenarios.senda(INDICE_DE[tipo])
    extrapolado = False
    fuera = []
    for f in fechas:
        indice = 0.0
        if senda is not None:
            indice, ex = senda.vigente(
                fecha_del_indice(f, paso, fecha_val, plano), escenario)
            extrapolado = extrapolado or ex
        flujo = _cupon(tipo, cupon_facial, indice, pagos)
        if f == vencimiento:
            flujo += 1.0
        fuera.append((f, flujo))
    return fuera, extrapolado


def _valor_presente(flujos, desde: dt.date, tasa: float) -> float:
    return sum(fl * (1 + tasa) ** (-((f - desde).days) / 365.0) for f, fl in flujos)


def calcular(*, tipo: str, fecha_val: dt.date, vencimiento: dt.date, tir: float,
             cupon_facial: float, margen: float, escenarios: Escenarios | None,
             escenario: str = "Base", delta_pb: float = 0.0,
             horizontes=HORIZONTES) -> list[ResultadoHPR]:
    """HPR del CDT sintético de un rango, a cada horizonte y al vencimiento."""
    pagos = PAGOS_POR_ANIO[tipo]
    fechas = calendario_cupones(vencimiento, fecha_val, pagos)
    dias_venc = (vencimiento - fecha_val).days
    if not fechas or dias_venc <= 1:
        return []

    senda = None if tipo == "fs" else escenarios.senda(INDICE_DE[tipo])
    indice_hoy = 0.0 if senda is None else senda.vigente(fecha_val, escenario)[0]

    con_escenario, ex_esc = _flujos(tipo, fechas, vencimiento, fecha_val,
                                    cupon_facial, escenarios, escenario, plano=False)
    if tipo in V0_CON_ESCENARIO:
        planos = con_escenario
    else:
        planos, _ = _flujos(tipo, fechas, vencimiento, fecha_val, cupon_facial,
                            escenarios, escenario, plano=True)

    tasa_ent = tasa_descuento(tipo, tir, margen, indice_hoy)
    v0 = 100 * _valor_presente(planos, fecha_val, tasa_ent)

    delta = delta_pb / 10000.0
    fuera = []
    # los horizontes fijos, y al final el vencimiento. En la fila del vencimiento
    # se usa `dias_venc − 1` por definición, no por quedarse corto el plazo: ahí la
    # marca «al vencimiento» no aplica.
    for pedido, es_venc in [(h, False) for h in horizontes] + [(dias_venc, True)]:
        h = min(pedido, dias_venc - 1)
        salida = fecha_val + dt.timedelta(days=h)
        indice_salida, ex_sal = (0.0, False) if senda is None else senda.vigente(salida, escenario)
        tasa_sal = tasa_descuento(tipo, tir + delta, margen + delta, indice_salida)

        cupones = [(f, fl) for f, fl in con_escenario if fecha_val < f <= salida]
        resto = [(f, fl) for f, fl in con_escenario if f > salida]
        v1 = 100 * _valor_presente(resto, salida, tasa_sal)

        flujos = ([(0.0, -v0)]
                  + [(float((f - fecha_val).days), 100 * fl) for f, fl in cupones]
                  + [(float(h), v1)])
        fuera.append(ResultadoHPR(
            horizonte=pedido, dias=h, hpr=xirr(flujos), v0=v0, v1=v1,
            tasa_entrada=tasa_ent, tasa_salida=tasa_sal, cupones=len(cupones),
            al_vencimiento=(not es_venc) and h < pedido,
            extrapolado=ex_esc or ex_sal))
    return fuera
