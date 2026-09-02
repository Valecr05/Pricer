"""
Parametría del pricer. Todo lo que un analista puede necesitar cambiar vive aquí
o en el JSON de parámetros de mercado. Nada de esto está enterrado en el código.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ----------------------------------------------------------------------------
# 1. Layout del archivo plano SX (ancho fijo, 270 bytes por registro de detalle)
#    Posiciones 0-based [inicio, fin). Verificado contra SX_T.001 y SX_T-1.001.
# ----------------------------------------------------------------------------

Kind = Literal["txt", "num", "date", "skip"]


@dataclass(frozen=True)
class Field:
    name: str
    start: int
    end: int
    kind: Kind
    desc: str = ""

    @property
    def width(self) -> int:
        return self.end - self.start


DETAIL_LAYOUT: tuple[Field, ...] = (
    Field("consecutivo",      0,   7,   "skip", "Consecutivo del registro"),
    Field("tipo_registro",    7,   8,   "skip", "C = control, D = detalle"),
    Field("nemotecnico",      8,   20,  "txt",  "Nemotécnico del título"),
    Field("isin",             20,  32,  "txt",  "ISIN"),
    Field("_relleno_1",       32,  51,  "skip", "Ceros + indicador de estado"),
    Field("fecha_val",        51,  59,  "date", "Fecha de valoración"),
    Field("emision",          59,  67,  "date", "Fecha de emisión"),
    Field("vencimiento",      67,  75,  "date", "Fecha de vencimiento"),
    Field("periodicidad",     75,  77,  "txt",  "PV/MV/TV/SV/AV/BV/NO"),
    Field("dias",             77,  81,  "num",  "Días al vencimiento"),
    Field("moneda",           81,  84,  "txt",  "COP / UVR / TRM"),
    Field("tipo",             84,  86,  "txt",  "1 = tasa fija, 3 = indexado"),
    Field("indicador",        86,  90,  "txt",  "FS/IPC/ICP/IB1/IB3/DTF/DTE/IP4"),
    Field("cupon",            90,  108, "num",  "Tasa facial (%)"),
    Field("tipo_2",           108, 110, "txt",  "Convención de conteo de días"),
    Field("precio_sucio",     110, 129, "num",  "Precio sucio"),
    Field("_relleno_2",       129, 168, "skip", "Campo en ceros + relleno"),
    Field("precio_limpio",    168, 187, "num",  "Precio limpio"),
    Field("_relleno_3",       187, 199, "skip", "Relleno"),
    Field("tasa_val",         199, 210, "num",  "Tasa de valoración (%)"),
    Field("duracion",         210, 220, "num",  "Duración de Macaulay (años)"),
    Field("dm",               220, 230, "num",  "Duración modificada"),
    Field("convexidad",       230, 240, "num",  "Convexidad (interpretación por confirmar)"),
    Field("cupon_acumulado",  240, 250, "num",  "Intereses causados"),
    Field("margen_proveedor", 250, 260, "num",  "Margen del proveedor (se recalcula)"),
    Field("calificacion",     260, 270, "txt",  "Calificación de riesgo"),
)

# Registro de control (línea 1, 90 bytes)
CONTROL_LAYOUT: tuple[Field, ...] = (
    Field("consecutivo",   0,  7,  "skip", ""),
    Field("tipo_registro", 7,  8,  "txt",  "C"),
    Field("marca",         8,  13, "txt",  "SPVSX"),
    Field("fecha_corta",   13, 19, "txt",  "MMDDYY"),
    Field("_sep",          19, 20, "skip", ""),
    Field("codigo",        20, 33, "txt",  "Código del emisor del archivo"),
    Field("fecha_val",     33, 41, "date", "Fecha de valoración"),
    Field("n_registros",   41, 48, "num",  "Registros de detalle declarados"),
    Field("suma_sucio",    48, 69, "num",  "Suma de control de precio sucio"),
    Field("suma_limpio",   69, 90, "num",  "Suma de control de precio limpio"),
)

# ----------------------------------------------------------------------------
# 2. Homologación de calificaciones  (hoja "Set Up", B:C)
# ----------------------------------------------------------------------------
# Réplica exacta de la hoja Set Up del libro original, por decisión de negocio.
# Cuatro calificaciones presentes en el archivo no están aquí (VrR2-, VrR1, BRC2
# y SIN_CALIFI). En el Excel el VLOOKUP fallaba y el error quedaba silenciado por
# un On Error Resume Next; aquí quedan como NO HOMOLOGADA, se cuentan en la
# sección de calidad del reporte y, al no ser AAA ni F1+, se clasifican como
# CDT HY y quedan fuera de las curvas. Es el mismo resultado que el Excel, pero
# a la vista.

RATING_MAP: dict[str, str] = {
    "NACION": "NACION",
    "MULTILATER": "MULTILATERAL",
    "AAA": "AAA",
    "AA+": "AA+", "AA": "AA", "AA-": "AA-",
    "A+": "A+", "A": "A", "A-": "A-",
    "BBB+": "BBB+", "BBB": "BBB", "BBB-": "BBB-",
    "BB+": "BB+", "BB": "BB", "BB-": "BB-",
    "B+": "B+", "B": "B", "B-": "B-",
    "CCC": "CCC",
    "BRC1+": "F1+", "BRC1": "F1",
    "F1+": "F1+", "F1": "F1", "F2": "F2",
    "VrR1+": "F1+", "VrR2": "F1",
}

# Calificaciones simples que cuentan como grado de inversión para separar CDT / CDT HY
CDT_INVESTMENT_GRADE: frozenset[str] = frozenset({"AAA", "F1+"})

# ----------------------------------------------------------------------------
# 3. Rejilla mensual de vencimientos
# ----------------------------------------------------------------------------
# Cada renglón cubre la ventana [ancla_i, ancla_{i+1}) y el paso son los días del
# mes en curso, así que los anclajes caen el mismo día de cada mes y la ventana
# cruza dos meses de calendario. Es la rejilla de la hoja TF del libro original.
#
# Cada fecha ancla su propia rejilla en su fecha de valoración. Compartir la de T
# no serviría: si T-1 es el cierre de un trimestre, la primera ventana de T caería
# en el pasado de T-1.

# Hasta qué plazo llega la escala de calificación de corto plazo. Un renglón usa
# la escala corta si su ventana termina dentro del primer año.
LONG_TERM_THRESHOLD_DAYS = 366

# Par de calificaciones que define la curva de referencia, equivalente al par
# "AAA/F1+" de Main!B10.
RATING_CORTO = "F1+"
RATING_LARGO = "AAA"

# ----------------------------------------------------------------------------
# 4. Emisores de CDT marcados High Yield por criterio propio (hoja "Set Up", I)
# ----------------------------------------------------------------------------

CDT_HIGH_YIELD_PREFIXES: frozenset[str] = frozenset({
    "CDTCFC", "CDTBOO", "CDTFSL", "CDTCAC", "CDTHIP", "CDTTYA", "CDTLBX",
    "CDTGMA", "CDTFAN", "CDTBMM", "CDTWWB", "CDTMIA", "CDTDIA", "CDTRCI",
    "CDTBSC", "CDTBCD", "CDTCMI", "CDTSFN", "CDTBTG",
})

# ----------------------------------------------------------------------------
# 5. Exclusiones del universo  (los cuatro filtros del VBA original)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Exclusion:
    id: str
    label: str
    # condiciones unidas por AND. Un valor en tupla significa "está en la lista".
    where: tuple[tuple[str, str | tuple[str, ...]], ...]


EXCLUSIONS: tuple[Exclusion, ...] = (
    Exclusion("tidis", "TIDIS (títulos de devolución de impuestos)",
              (("nemotecnico", "TIDISDVL"),)),
    Exclusion("nacion_indexada", "Nación indexada: bonos pensionales y TES UVR indexados",
              (("calificacion", "NACION"), ("tipo", "3"))),
    Exclusion("indices_fuera_de_alcance", "Indicadores DTF, DTE e IB3",
              (("indicador", ("DTF", "DTE", "IB3")),)),
    Exclusion("sin_calificacion", "Registros sin calificación",
              (("calificacion", ""),)),
)

# ----------------------------------------------------------------------------
# 6. Clasificación de familia (columna "CDT/BONO" del Excel)
# ----------------------------------------------------------------------------
# El Excel clasificaba TITULA por prefijo de una sola letra ("T"), lo que atrapa
# cualquier bono corporativo cuyo nemotécnico empiece por T. Aquí se exige un
# prefijo de al menos dos caracteres.

TITULARIZACION_PREFIXES: tuple[str, ...] = ("TIP", "TIS", "TIN", "INST", "ST")

# ----------------------------------------------------------------------------
# 7. Bloques de curva a construir (equivalente a los bloques de la hoja "Main")
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockSpec:
    id: str
    label: str
    indicador: str                    # FS / IPC / IB1 ...
    periodicidad: str | None          # TV / MV / None = sin filtro
    familias: tuple[str, ...] = ("CDT", "CDT HY", "BONO")
    # Filtro de moneda. Desactivado por decisión de negocio: el Excel lo aplicaba
    # solo en algunos bloques. Poner "COP" aquí lo reactiva por bloque.
    moneda: str | None = None
    # Aclaración que el reporte imprime bajo el título del bloque.
    nota: str = ""
    # Calcular el margen nominal sobre IBR por el atajo de la bvc. Necesita la
    # curva IND_IBR del mismo día y la senda histórica de IBR.
    margen_atajo: bool = False
    # Hasta dónde llega la rejilla mensual de este bloque.
    anios: int = 3

    @property
    def meses(self) -> int:
        return self.anios * 12


BLOCKS: tuple[BlockSpec, ...] = (
    BlockSpec("fs", "Tasa fija (FS)", "FS", "TV", anios=7),
    BlockSpec(
        "ipc", "Indexado a IPC", "IPC", "TV", anios=3,
        nota="La columna de tasa es la valoración efectiva anual tal como la envía el "
             "proveedor; el IPC de pantalla no la mueve. El margen real, al lado, es "
             "(1 + tasa) / (1 + IPC) − 1 con el IPC de cada fecha que esté puesto en "
             "la barra de arriba, así que sus dos Δ solo coinciden si las dos fechas "
             "comparten IPC. El cupón de este bloque es el spread facial sobre "
             "inflación, no una tasa nominal."),
    BlockSpec(
        "ibr", "Indexado a IBR (IB1)", "IB1", "MV", margen_atajo=True, anios=3,
        nota="La columna de tasa es la valoración efectiva anual tal como la envía el "
             "proveedor, sin convertir. El margen se calcula aparte, por el atajo de la "
             "Calculadora IBR de la bvc: se supone que el nodo vence al final de su ventana, que paga cupón mensual hasta esa fecha y que la tasa está "
             "«Previa», así que el índice de cada cupón se lee un mes antes de su pago, "
             "conservando el número del día. Lo que cae en o antes de la valoración sale "
             "de la senda histórica; lo posterior, de la curva IND_IBR del día hábil "
             "anterior."),
)

# Índices que entran a la base sin transformar la tasa: su columna de tasa es la
# valoración tal como la envía el proveedor.
INDICES_SIN_CONVERSION: frozenset[str] = frozenset({"IB1"})

# ----------------------------------------------------------------------------
# 8. Universo TES (se deriva de los datos, no de una lista fija)
# ----------------------------------------------------------------------------

TES_COP_PREFIXES: tuple[str, ...] = ("TFIT", "TCO", "TFVT", "TFIC", "TFIP")
TES_UVR_PREFIXES: tuple[str, ...] = ("TUVT",)

# Nemotécnicos de Nación que no son referencias negociables y quedan fuera de la
# tabla de TES. CINAS (123 registros) y TDS (2) llegan con tasa y duración en cero.
# CERTS (2) tiene la misma firma de relleno; agregarlo aquí es una línea.
TES_NEMOTECNICOS_EXCLUIDOS: tuple[str, ...] = ("CINAS", "TDS")

# Archivo de sendas de proyección, buscado dentro de la carpeta de curvas si no se
# indica una ruta. Alimenta la pestaña de rentabilidades esperadas.
NOMBRE_ESCENARIOS = "Escenarios_IPC-IBR_VC.xlsx"

# ----------------------------------------------------------------------------
# 9. Parámetros de mercado del día
# ----------------------------------------------------------------------------


# Claves que existieron en versiones anteriores del archivo de parámetros. Se
# aceptan para no romper los JSON ya escritos, pero se reportan.
CLAVES_OBSOLETAS: dict[str, str] = {
    "ipc_t": "ipc_referencia",
    "ipc_t1": None,          # el IPC por fecha ahora va en ipc_por_fecha
    "ibr_t": None, "ibr_t1": None, "ibr3_t": None, "ibr3_t1": None,
    "dtf_t": None, "dtf_t1": None,
    "horizonte_dias": None,  # ya no hay carry ni slide
}


@dataclass
class MarketParams:
    """Parámetros de mercado.

    `ipc_referencia` es el único IPC que interviene en el procesamiento, y solo
    para calcular la duración al vencimiento de los títulos indexados. Se usa uno
    solo para toda la serie porque la duración es muy poco sensible a él: mover el
    IPC de 6,14 % a 7 % cambia la duración de un bono a tres años en menos de 0,02
    años. Eso también mantiene el caché estable cuando se publica un IPC nuevo.

    `ipc_por_fecha` es opcional y no entra en ningún cálculo: solo precarga los
    campos de IPC de la pantalla cuando se elige una fecha. Los márgenes se
    calculan siempre con lo que esté puesto en pantalla.
    """
    ipc_referencia: float
    tasa_br: float = 0.0
    ipc_por_fecha: dict[str, float] = field(default_factory=dict)
    nominal_dv01: float = 1_000_000_000.0   # nominal de referencia para el DV01
    fuente: str = ""
    capturado_por: str = ""
    avisos: list[str] = field(default_factory=list)

    def ipc_de(self, fecha) -> float:
        """IPC con el que se precarga la pantalla para una fecha."""
        if fecha is None:
            return self.ipc_referencia
        clave = fecha if isinstance(fecha, str) else fecha.isoformat()
        return float(self.ipc_por_fecha.get(clave, self.ipc_referencia))

    def to_dict(self) -> dict:
        return {"ipc_referencia": self.ipc_referencia, "tasa_br": self.tasa_br,
                "ipc_por_fecha": dict(self.ipc_por_fecha),
                "nominal_dv01": self.nominal_dv01, "fuente": self.fuente,
                "capturado_por": self.capturado_por}

    @classmethod
    def from_dict(cls, d: dict) -> "MarketParams":
        d = dict(d)
        avisos: list[str] = []
        for vieja, nueva in CLAVES_OBSOLETAS.items():
            if vieja not in d:
                continue
            valor = d.pop(vieja)
            if nueva and nueva not in d:
                d[nueva] = valor
                avisos.append(f"«{vieja}» ya no existe; su valor se tomó como «{nueva}».")
            else:
                avisos.append(f"«{vieja}» ya no se usa y se ignoró.")

        conocidas = set(cls.__dataclass_fields__) - {"avisos"}
        desconocidas = set(d) - conocidas
        if desconocidas:
            raise ValueError(
                f"Parámetros desconocidos en el JSON: {sorted(desconocidas)}. "
                f"Se esperan: {sorted(conocidas)}")
        if "ipc_referencia" not in d:
            raise ValueError("Falta «ipc_referencia» en el archivo de parámetros.")
        p = cls(**d)
        p.avisos = avisos
        return p


# ----------------------------------------------------------------------------
# 10. Duración
# ----------------------------------------------------------------------------
# "proveedor"  usa siempre la duración del archivo. Reproduce el Excel, pero en
#              los indexados esa duración es al próximo corte de cupón.
# "calculada"  calcula la duración de Macaulay al vencimiento para todo.
# "mixta"      usa la del proveedor en tasa fija, donde ya es al vencimiento y es
#              la cifra autoritativa, y la calculada en los indexados.
DURACION_FUENTE = "mixta"

# Diferencia mediana aceptable, en años, entre la duración calculada y la del
# proveedor sobre los títulos de tasa fija. Por encima de esto el reporte avisa
# de que la calculadora dejó de reproducir al proveedor.
DURACION_TOLERANCIA_ANIOS = 0.01

# ----------------------------------------------------------------------------
# 10. Tolerancias de validación
# ----------------------------------------------------------------------------

CHECKSUM_TOLERANCE = 0.005        # sobre las sumas de precio del registro de control
MIN_TITULOS_POR_NODO = 3          # por debajo de esto el nodo se marca como frágil
