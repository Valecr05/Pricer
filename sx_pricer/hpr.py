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
  - **Tasa de descuento**: una sola por bloque, nunca una por flujo. La de salida es
        TF    TIR(T) + delta
        IPC   (1 + margen + delta) × (1 + IPC(T+h)) − 1
        IBR   (1 + (IBR(T+h) + margen + delta) / 12)^(365/30) − 1
    En IBR la suma índice + margen es **nominal mes vencido**: se divide entre 12 para
    la periódica y se lleva a efectiva anual con el exponente 365/30 —un año de 365
    días sobre un mes de 30—, no con 12. La de entrada no siempre es la misma cuenta:
    ver el bullet de V₀.
  - **V₀**: convención de los proveedores de precios, distinta en cada índice. En los
    dos, el primer cupón usa el índice ya publicado y la senda de escenarios no
    interviene, así que V₀ sale igual en los tres escenarios. En **IPC** los demás
    cupones usan el índice de hoy «pegado» y todo se descuenta a (1+margen)(1+IPC)−1;
    en **IBR** los demás leen la curva forward IND_IBR del día hábil anterior y todo se
    descuenta a la Tasa (T) del rango, tal cual.
  - **V₁** en el día h: los flujos posteriores, proyectados con el escenario y
    descontados desde h con la tasa recompuesta usando el índice proyectado en
    T+h y el margen desplazado por el delta.
  - **HPR**: XIRR sobre −V₀ en el día 0, los cupones cobrados en sus días y +V₁ en
    el día h, en base ACT/365.

Con la senda del índice plana y delta cero, en IPC el HPR devuelve exactamente la tasa
de entrada en los tres horizontes; eso pide además que el índice de hoy —el de la barra—
sea el mismo valor de esa senda plana, porque si no, V₀ y los flujos que se cobran quedan
armados con inflaciones distintas y la diferencia aparece como rentabilidad.

En IBR la igualdad solo se cumple al vencimiento. La entrada descuenta a la Tasa (T) del
proveedor y la salida rearma su tasa desde el margen con la conversión 365/30: son unos
21 pb distintos aunque el mercado no se mueva, y la duración los amplifica a 90 y 180
días. Está documentado en el README como pendiente de decisión.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

from .escenarios import Escenarios

HORIZONTES = (90, 180)           # el tercero es el vencimiento
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


# Exponente con el que la tasa periódica mensual de IBR se lleva a efectiva anual: un
# año de 365 días sobre un mes de 30. No es 12: son 12,1667 períodos.
PERIODOS_ANIO_IBR = 365 / 30


def tasa_descuento(tipo: str, tir: float, margen: float, indice: float) -> float:
    """Tasa efectiva anual con la que se descuenta.

    En IBR la suma `índice + margen` es **nominal mes vencido**: se divide entre 12
    para obtener la periódica y se lleva a efectiva anual elevando a 365/30.
    """
    if tipo == "fs":
        return tir
    if tipo == "ipc":
        return (1 + margen) * (1 + indice) - 1
    return (1 + (indice + margen) / 12) ** PERIODOS_ANIO_IBR - 1


def _cupon(tipo: str, cupon_facial: float, indice: float, pagos: int) -> float:
    """Cupón del período. En IPC el exponente es la fracción fija 1/pagos."""
    if tipo == "fs":
        return cupon_facial / pagos
    if tipo == "ipc":
        return ((1 + indice) * (1 + cupon_facial)) ** (1 / pagos) - 1
    return (indice + cupon_facial) / pagos


def fecha_del_indice(fecha_cupon: dt.date, paso: int) -> dt.date:
    """Con qué fecha se lee el índice del cupón que se paga en `fecha_cupon`.

    Se toma el índice del **inicio del período**, un paso antes del pago, tanto en
    IPC como en IBR: un cupón trimestral del 25 de agosto de 2026 usa el IPC de mayo
    de 2026, y uno mensual del 27 de agosto usa el IBR vigente el 27 de julio. Es la
    misma convención del atajo de la bvc, donde la tasa se lee al inicio del período
    y no en su pago.

    En el primer cupón el inicio del período siempre cae en o antes de la fecha de
    valoración, así que ahí el índice es un dato publicado y no una proyección.

    Esto rige solo la **tasa cupón**. La tasa de descuento es otra cosa: usa el
    índice de hoy en la entrada y el proyectado en T+h en la salida.
    """
    return menos_meses(fecha_cupon, paso)


def _flujos(tipo: str, fechas: list[dt.date], vencimiento: dt.date,
            fecha_val: dt.date, cupon_facial: float, escenarios: Escenarios | None,
            escenario: str,
            historico: dict[dt.date, float] | None = None,
            indice_pegado: float | None = None,
            curva: dict[dt.date, float] | None = None
            ) -> tuple[list[tuple[dt.date, float]], bool]:
    """Flujos del título, proyectados con la senda del escenario.

    `historico` es la senda diaria publicada. Cuando se pasa, las lecturas que caen
    en o antes de la valoración salen de ahí y no del archivo de escenarios: son
    datos publicados, y es la misma fuente contra la que se calcula el margen. Si al
    histórico le falta ese día se cae a la senda de proyección, para no dejar el
    rango sin cifra.

    `indice_pegado` y `curva` arman en cambio los flujos del **precio de entrada**, y
    son la convención de los proveedores de precios: las lecturas posteriores a la
    valoración no se buscan en la senda sino que toman ese valor fijo —el índice de
    hoy, en IPC— o se leen en la curva forward IND_IBR del día hábil anterior, en IBR.
    Las anteriores siguen siendo el dato publicado que se les fijó. Si a la curva le
    falta una fecha se cae a la senda, para no dejar el rango sin cifra.
    """
    pagos = PAGOS_POR_ANIO[tipo]
    paso = 12 // pagos
    senda = None if tipo == "fs" else escenarios.senda(INDICE_DE[tipo])
    extrapolado = False
    fuera = []
    for f in fechas:
        indice = 0.0
        if senda is not None:
            inicio = fecha_del_indice(f, paso)
            publicado = (historico or {}).get(inicio) if inicio <= fecha_val else None
            if publicado is not None:
                indice = publicado
            elif indice_pegado is not None and inicio > fecha_val:
                indice = indice_pegado
            elif curva is not None and inicio > fecha_val and inicio in curva:
                indice = curva[inicio]
            else:
                indice, ex = senda.vigente(inicio, escenario)
                extrapolado = extrapolado or ex
        flujo = _cupon(tipo, cupon_facial, indice, pagos)
        if f == vencimiento:
            flujo += 1.0
        fuera.append((f, flujo))
    return fuera, extrapolado


# El **precio de entrada** de los dos bloques indexados se arma con la convención de
# los proveedores de precios colombianos, que no es la misma en los dos índices:
#
#   IPC  el primer cupón usa el índice que ya se le fijó —tres meses antes de su pago,
#        fecha pasada y por tanto publicada— y los demás el índice de hoy, «pegado».
#        Todo se descuenta a (1 + margen) × (1 + IPC de hoy) − 1.
#   IBR  el primer cupón usa el IBR publicado del mes anterior, y los demás la **curva
#        forward IND_IBR** del día hábil anterior, leída también en modalidad previa.
#        Todo se descuenta a la «Tasa (T)» del rango, tal cual: ya es efectiva anual.
#
# En los dos casos la senda de escenarios **no interviene** en V₀, así que el precio de
# entrada sale igual en los tres escenarios: lo que se paga hoy no depende de la
# expectativa propia. La salida sí proyecta con la senda.


def _valor_presente(flujos, desde: dt.date, tasa: float) -> float:
    """Base ACT/365, con una sola tasa efectiva anual para todos los flujos."""
    return sum(fl * (1 + tasa) ** (-((f - desde).days) / 365.0) for f, fl in flujos)


def calcular(*, tipo: str, fecha_val: dt.date, vencimiento: dt.date, tir: float,
             cupon_facial: float, margen: float, escenarios: Escenarios | None,
             escenario: str = "Base", delta_pb: float = 0.0,
             horizontes=HORIZONTES, indice_entrada: float | None = None,
             historico: dict[dt.date, float] | None = None,
             curva: dict[dt.date, float] | None = None) -> list[ResultadoHPR]:
    """HPR del CDT sintético de un rango, a cada horizonte y al vencimiento.

    `historico` es la senda diaria publicada del índice: de ahí salen las lecturas
    anteriores a la valoración, en vez del archivo de escenarios. `curva` es la curva
    forward IND_IBR del día hábil anterior, con la que IBR arma los cupones de V₀.

    `indice_entrada` es el índice con el que se recompone la tasa de entrada. Tiene
    que ser **el mismo** con el que se despejó `margen`: solo así los dos se
    cancelan y V₀ descuenta a la TIR del nodo. Si se omite se toma el de la senda
    en la fecha de valoración, que es lo correcto cuando el margen salió de ahí.
    """
    pagos = PAGOS_POR_ANIO[tipo]
    fechas = calendario_cupones(vencimiento, fecha_val, pagos)
    dias_venc = (vencimiento - fecha_val).days
    if not fechas or dias_venc <= 1:
        return []

    senda = None if tipo == "fs" else escenarios.senda(INDICE_DE[tipo])
    if indice_entrada is not None:
        indice_hoy = indice_entrada
    else:
        indice_hoy = 0.0 if senda is None else senda.vigente(fecha_val, escenario)[0]

    con_escenario, ex_esc = _flujos(tipo, fechas, vencimiento, fecha_val,
                                    cupon_facial, escenarios, escenario, historico)

    # El precio de entrada: convención del proveedor, distinta en cada índice. Ver el
    # comentario de arriba, junto a _valor_presente.
    def _v0(**fuente):
        return _flujos(tipo, fechas, vencimiento, fecha_val, cupon_facial,
                       escenarios, escenario, historico, **fuente)[0]

    if tipo == "ipc":
        flujos_v0 = _v0(indice_pegado=indice_hoy)
        tasa_ent = tasa_descuento(tipo, tir, margen, indice_hoy)
    elif tipo == "ibr":
        flujos_v0 = _v0(curva=curva)
        tasa_ent = tir                      # la «Tasa (T)» del rango, ya efectiva anual
    else:
        flujos_v0 = con_escenario
        tasa_ent = tasa_descuento(tipo, tir, margen, indice_hoy)
    v0 = 100 * _valor_presente(flujos_v0, fecha_val, tasa_ent)

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
