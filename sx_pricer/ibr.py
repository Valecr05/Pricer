"""
Margen nominal sobre IBR por el método «atajo» de la Calculadora IBR de la bvc.

Necesita dos insumos por fecha de valoración:

  - **La curva forward del día hábil anterior**, `IND_IBR_AAAAMMDD.txt`: una fila
    por día calendario y por tenor, separada por `;` y con coma decimal. El archivo
    del 28-jul-2026 trae 5.000 días por tenor, del 29 de julio de 2026 al 5 de abril
    de 2040; empieza en D+1, así que no contiene su propia fecha ni ninguna anterior.
    El margen de la fecha D se calcula con el archivo publicado **antes** de D —el
    más reciente disponible, que salta fines de semana y festivos— porque es la curva
    con la que se contaba al valorar. Como esa curva arranca en D, cubre todos los
    puntos que el atajo consulta, que son posteriores a D.
  - **El IBR previo**, de la senda histórica diaria (`IB1.xlsx`), tomando el valor
    del **propio día de valoración**: este no se desplaza a la fecha anterior.

Cada fecha usa la curva de su propio día hábil anterior y de ninguna otra. Si no hay
ningún archivo anterior a D, el margen de D no se calcula.

Convenciones aplicadas:

  - `J`: días calendario descontando los 29 de febrero del tramo (ACT/365 fijo).
  - `L`: días en base 30/360 US/NASD, la de `DAYS360` de Excel.
  - El cronograma se ancla en el vencimiento y retrocede en múltiplos exactos de
    mes, de modo que el día del mes no se arrastra al pasar por un mes corto.
  - Todos los títulos IB1 se tratan como «Previa»: el primer flujo se descuenta
    contra el IBR previo y los demás contra la curva leída en el flujo anterior,
    es decir al inicio del período y no en su pago.
  - El margen es el promedio simple de los márgenes por período, redondeado a
    cuatro decimales en decimal, que son dos decimales de porcentaje.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from dateutil.relativedelta import relativedelta   # viene con pandas

PATRON_ARCHIVO = "IND_IBR_{:%Y%m%d}.txt"
TENOR = "IB1"                     # el único indexante presente en los planos SX
NOMBRE_HISTORICO = "IB1.xlsx"
PAGOS_POR_ANIO = 12               # IB1 = mes vencido
ENCODING = "latin-1"

# La senda histórica llega de Bloomberg: la fila 6 son los títulos y los datos
# empiezan en la 7, con la fecha en la columna A y el valor en la B.
FILA_INICIAL_HISTORICO = 7


class IBRFormatError(Exception):
    """El archivo de curva o de senda histórica no tiene la forma esperada."""


# ----------------------------------------------------------------------------
# Convenciones de conteo de días
# ----------------------------------------------------------------------------

def dias_act365(desde: dt.date, hasta: dt.date) -> int:
    """Días calendario descontando los 29 de febrero del tramo."""
    n = (hasta - desde).days
    for anio in range(desde.year, hasta.year + 1):
        try:
            bisiesto = dt.date(anio, 2, 29)
        except ValueError:
            continue
        if desde < bisiesto <= hasta:
            n -= 1
    return n


def dias_360(desde: dt.date, hasta: dt.date) -> int:
    """Base 30/360 US/NASD, igual que DAYS360 de Excel con método FALSO."""
    d1 = min(desde.day, 30)
    d2 = hasta.day
    if d2 == 31 and d1 == 30:
        d2 = 30
    return (hasta.year - desde.year) * 360 + (hasta.month - desde.month) * 30 + (d2 - d1)


def cronograma(vencimiento: dt.date, fecha_val: dt.date,
               pagos_por_anio: int = PAGOS_POR_ANIO) -> list[dt.date]:
    """Fechas de flujo posteriores a la valoración, ancladas en el vencimiento.

    Se retrocede en múltiplos exactos de mes desde el vencimiento, no restando un
    período cada vez: así el día del mes no se arrastra al pasar por un mes corto.
    """
    meses = 12 // pagos_por_anio
    fechas: list[dt.date] = []
    k = 0
    while True:
        f = vencimiento - relativedelta(months=meses * k)
        if f <= fecha_val:
            break
        fechas.append(f)
        k += 1
    fechas.reverse()
    return fechas


# ----------------------------------------------------------------------------
# Cálculo del margen
# ----------------------------------------------------------------------------

def margen_atajo(*, fecha_val: dt.date, vencimiento: dt.date, tir: float,
                 ibr_previo: float, curva: dict[dt.date, float],
                 pagos_por_anio: int = PAGOS_POR_ANIO) -> float | None:
    """Margen nominal sobre IBR. Devuelve None si falta algún punto de curva.

    `tir`, `ibr_previo` y el resultado van en decimal (0,1352 = 13,52 %).
    """
    flujos = cronograma(vencimiento, fecha_val, pagos_por_anio)
    if not flujos:
        return None

    j_prev = l_prev = 0
    margenes = []
    for i, fecha in enumerate(flujos):
        j = dias_act365(fecha_val, fecha)
        l = dias_360(fecha_val, fecha)
        if l <= l_prev:
            return None
        # La tasa se lee al inicio del período: el primer flujo contra el IBR
        # previo y los demás contra la curva en el flujo anterior.
        n = ibr_previo if i == 0 else curva.get(flujos[i - 1])
        if n is None:
            return None
        z = ((1 + tir) ** ((j - j_prev) / 365) - 1) * 360 / (l - l_prev)
        margenes.append(z - n)
        j_prev, l_prev = j, l

    return round(sum(margenes) / len(margenes), 4)


# ----------------------------------------------------------------------------
# Lectura de los archivos
# ----------------------------------------------------------------------------

def leer_curva(path: str | Path, *, tenor: str = TENOR) -> dict[dt.date, float]:
    """Lee un IND_IBR_AAAAMMDD.txt y devuelve {fecha: tasa} del tenor pedido."""
    path = Path(path)
    curva: dict[dt.date, float] = {}
    malas = 0
    for linea in path.read_text(ENCODING).splitlines():
        if not linea.strip():
            continue
        partes = linea.split(";")
        if len(partes) < 4:
            malas += 1
            continue
        if partes[2].strip() != tenor:
            continue
        try:
            fecha = dt.datetime.strptime(partes[0].strip(), "%d/%m/%Y").date()
            curva[fecha] = float(partes[3].strip().replace(",", ".")) / 100
        except ValueError:
            malas += 1
    if not curva:
        raise IBRFormatError(
            f"{path.name}: no se encontró ninguna fila del tenor {tenor} "
            f"({malas} líneas ilegibles).")
    return curva


def leer_historico(path: str | Path) -> tuple[dict[dt.date, float], list[str]]:
    """Lee la senda histórica diaria de IBR. Devuelve ({fecha: tasa}, avisos)."""
    try:
        import openpyxl
    except ImportError:                                   # pragma: no cover
        raise IBRFormatError(
            "Para leer la senda histórica de IBR hace falta openpyxl: "
            "pip install openpyxl")

    path = Path(path)
    hoja = openpyxl.load_workbook(path, data_only=True, read_only=True).worksheets[0]
    serie: dict[dt.date, float] = {}
    descartadas = 0
    for fecha, valor in hoja.iter_rows(min_row=FILA_INICIAL_HISTORICO, max_col=2,
                                       values_only=True):
        if isinstance(fecha, dt.datetime) and isinstance(valor, (int, float)):
            serie[fecha.date()] = float(valor) / 100
        elif fecha is not None or valor is not None:
            descartadas += 1

    if not serie:
        raise IBRFormatError(
            f"{path.name}: no se leyó ninguna fecha a partir de la fila "
            f"{FILA_INICIAL_HISTORICO}. Se espera la fecha en la columna A y el "
            "valor en la columna B.")

    avisos = []
    if descartadas:
        avisos.append(
            f"{path.name}: se descartaron {descartadas} fila(s) sin fecha o sin "
            "valor legible. Suele ser el «#NAME?» que deja la fórmula de Bloomberg.")
    return serie, avisos


# ----------------------------------------------------------------------------
# Fuente combinada, con huella para el caché
# ----------------------------------------------------------------------------

@dataclass
class FuenteIBR:
    """Curvas diarias y senda histórica, listas para consultar por fecha."""
    carpeta: Path | None = None
    historico: dict[dt.date, float] = field(default_factory=dict)
    fechas_curva: list[dt.date] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @classmethod
    def cargar(cls, carpeta: str | Path | None,
               historico: str | Path | None = None) -> "FuenteIBR":
        """La senda histórica se busca dentro de la carpeta de curvas si no se
        indica una ruta."""
        avisos: list[str] = []
        carpeta = Path(carpeta) if carpeta else None
        if carpeta is not None and not carpeta.is_dir():
            raise IBRFormatError(f"No existe la carpeta de curvas: {carpeta}")

        ruta = Path(historico) if historico else None
        if ruta is not None and not ruta.exists():
            raise IBRFormatError(f"No existe la senda histórica de IBR: {ruta}")
        if ruta is None and carpeta is not None:
            candidata = carpeta / NOMBRE_HISTORICO
            ruta = candidata if candidata.exists() else None

        serie: dict[dt.date, float] = {}
        if ruta is not None:
            serie, avisos = leer_historico(ruta)
        elif carpeta is not None:
            avisos.append(
                f"No se encontró la senda histórica de IBR ({NOMBRE_HISTORICO}) en "
                f"{carpeta}. Sin ella no se puede calcular el margen: el primer "
                "flujo se descuenta contra el IBR previo, que no viene en la curva.")
        disponibles = fechas_disponibles(carpeta) if carpeta is not None else []
        return cls(carpeta=carpeta, historico=serie, fechas_curva=disponibles,
                   avisos=avisos)

    @property
    def activa(self) -> bool:
        return self.carpeta is not None

    def ruta_curva(self, fecha: dt.date) -> Path | None:
        """Archivo de curva de esa fecha exacta, si existe."""
        if self.carpeta is None:
            return None
        ruta = self.carpeta / PATRON_ARCHIVO.format(fecha)
        return ruta if ruta.exists() else None

    def fecha_curva_usada(self, fecha: dt.date) -> dt.date | None:
        """Fecha de la curva con la que se calcula el margen de `fecha`: la del
        archivo más reciente publicado **antes** de ella. Al buscar el más reciente
        y no el día calendario anterior, los lunes y los días después de festivo
        toman el último día hábil con archivo."""
        anteriores = [f for f in self.fechas_curva if f < fecha]
        return anteriores[-1] if anteriores else None

    def ruta_curva_usada(self, fecha: dt.date) -> Path | None:
        usada = self.fecha_curva_usada(fecha)
        return None if usada is None else self.ruta_curva(usada)

    def previo(self, fecha: dt.date) -> float | None:
        return self.historico.get(fecha)

    def huella(self, fecha: dt.date) -> str:
        """Identifica los insumos de una fecha, para que el caché se invalide
        cuando cambien."""
        if not self.activa:
            return "sin-curvas"
        ruta = self.ruta_curva_usada(fecha)
        if ruta is None:
            return "sin-archivo"
        st = ruta.stat()
        return f"{ruta.name}:{st.st_size}:{int(st.st_mtime)}:{self.previo(fecha)}"

    def para_fecha(self, fecha: dt.date) -> tuple[dict[dt.date, float], float] | None:
        """Curva del día hábil anterior e IBR previo de la propia fecha, o None si
        falta alguno de los dos."""
        ruta = self.ruta_curva_usada(fecha)
        previo = self.previo(fecha)
        if ruta is None or previo is None:
            return None
        return leer_curva(ruta), previo

    def motivo_faltante(self, fecha: dt.date) -> str | None:
        """Por qué no hay margen para esta fecha, en texto para el reporte."""
        if not self.activa:
            return "no se indicó carpeta de curvas"
        if self.fecha_curva_usada(fecha) is None:
            if self.fechas_curva:
                return ("no hay ninguna curva anterior a esta fecha; la más antigua "
                        f"disponible es la del {self.fechas_curva[0]}")
            return "no hay ningún archivo de curva en la carpeta"
        if self.previo(fecha) is None:
            return "la senda histórica de IBR no cubre esta fecha"
        return None


PATRON_NOMBRE = re.compile(r"^IND_IBR_(\d{8})\.txt$", re.IGNORECASE)


def fechas_disponibles(carpeta: str | Path) -> list[dt.date]:
    """Fechas para las que hay archivo de curva en una carpeta."""
    fuera = []
    for ruta in Path(carpeta).glob("*.txt"):
        m = PATRON_NOMBRE.match(ruta.name)
        if m:
            try:
                fuera.append(dt.datetime.strptime(m.group(1), "%Y%m%d").date())
            except ValueError:
                continue
    return sorted(fuera)


def nombres_descartados(carpeta: str | Path) -> list[tuple[str, str]]:
    """Archivos .txt de la carpeta que parecen curvas pero no se pueden usar.

    Un espacio en lugar de un guion bajo, un «(1)» que agrega el navegador o la fecha
    invertida bastan para que el archivo se ignore en silencio. Devuelve el nombre y
    el motivo de cada uno.
    """
    fuera = []
    for ruta in sorted(Path(carpeta).glob("*.txt")):
        m = PATRON_NOMBRE.match(ruta.name)
        if m:
            try:
                dt.datetime.strptime(m.group(1), "%Y%m%d")
            except ValueError:
                fuera.append((ruta.name, f"«{m.group(1)}» no es una fecha AAAAMMDD"))
            continue
        if "ibr" in ruta.name.lower() or "ind" in ruta.name.lower():
            fuera.append((ruta.name, "el nombre no encaja con IND_IBR_AAAAMMDD.txt"))
    return fuera
