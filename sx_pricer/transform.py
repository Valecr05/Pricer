"""
Capa 2: depuración del universo y columnas derivadas.

Equivale al VBA `Organizar_Datos`. Diferencias, todas deliberadas:

  - Los índices fuera de alcance (DTF, DTE, IB3) se excluyen del universo.
  - Los títulos indexados a IBR entran sin ninguna conversión: su columna de tasa
    es la valoración tal como la envía el proveedor.
  - La homologación de calificaciones es la de la hoja Set Up, sin agregados. Lo
    que no está en el mapa queda marcado como NO HOMOLOGADA y se reporta, en
    lugar de desaparecer dentro de un error silenciado.
  - En los indexados la duración se calcula al vencimiento, porque la que envía
    el proveedor es al próximo corte de cupón.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as cfg
from .bonds import MESES_POR_CUPON, duracion_al_vencimiento


@dataclass
class ExclusionResult:
    id: str
    label: str
    filas: int


@dataclass
class QualityIssue:
    severidad: str          # "error" | "aviso" | "info"
    codigo: str
    mensaje: str
    filas: int = 0
    muestra: list[str] = field(default_factory=list)


@dataclass
class Valuation:
    """Universo depurado y enriquecido de una fecha."""
    etiqueta: str                       # "T" | "T-1"
    fecha: object
    data: pd.DataFrame
    n_origen: int
    exclusiones: list[ExclusionResult] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def n_final(self) -> int:
        return len(self.data)


# ----------------------------------------------------------------------------


def _homologar_calificacion(calif: pd.Series) -> tuple[pd.Series, set[str]]:
    simple = calif.map(cfg.RATING_MAP)
    faltantes = set(calif[simple.isna()].dropna().unique()) - {""}
    return simple.fillna("NO HOMOLOGADA"), faltantes


def _margen(df: pd.DataFrame, ipc: float) -> pd.Series:
    """Medida comparable de cada índice.

      FS         -> tasa efectiva anual, tal cual
      IPC/ICP    -> margen real sobre inflación:  (1+tasa)/(1+IPC) - 1
      IB1        -> la valoración sin conversión (decisión de negocio)
    """
    tasa = df["tasa_val"] / 100.0
    out = tasa.copy()                                   # FS y los sin conversión
    es_ipc = df["indicador"].isin(("IPC", "ICP", "IP4"))
    out[es_ipc] = (1.0 + tasa[es_ipc]) / (1.0 + ipc) - 1.0
    return out


def _familia(df: pd.DataFrame) -> pd.Series:
    nemo = df["nemotecnico"].fillna("")
    calif = df["calificacion_simple"]

    es_cdt = nemo.str.startswith("CDT")
    hy_lista = nemo.str[:6].isin(cfg.CDT_HIGH_YIELD_PREFIXES)
    grado_inv = calif.isin(cfg.CDT_INVESTMENT_GRADE)
    es_titula = nemo.str.startswith(tuple(cfg.TITULARIZACION_PREFIXES))
    es_nacion = calif == "NACION"

    out = pd.Series("BONO", index=df.index, dtype=object)
    out[es_titula] = "TITULA"
    out[es_nacion] = "TES"
    out[es_cdt] = np.where(hy_lista[es_cdt] | ~grado_inv[es_cdt], "CDT HY", "CDT")
    return out


def _duracion(df: pd.DataFrame, ipc: float) -> tuple[pd.Series, pd.Series, dict]:
    """Devuelve (duración a usar, duración calculada al vencimiento, diagnóstico)."""
    calc = duracion_al_vencimiento(df, ipc=ipc)
    proveedor = df["duracion"]

    fuente = cfg.DURACION_FUENTE
    if fuente == "proveedor":
        usada = proveedor
    elif fuente == "calculada":
        usada = calc
    elif fuente == "mixta":
        usada = calc.where(df["indicador"] != "FS", proveedor)
    else:
        raise ValueError(f"DURACION_FUENTE invalida: {fuente!r}")

    # La calculadora se contrasta contra el proveedor donde este si reporta la
    # duracion al vencimiento: los titulos de tasa fija con cupon.
    con_cupon = df["periodicidad"].isin(tuple(MESES_POR_CUPON))
    ref = df[(df["indicador"] == "FS") & con_cupon & (proveedor > 0)]
    dif = (calc.loc[ref.index] - ref["duracion"]).abs()
    diag = {
        "n": int(len(ref)),
        "p50": float(dif.median()) if len(dif) else float("nan"),
        "p95": float(dif.quantile(0.95)) if len(dif) else float("nan"),
    }
    return usada, calc, diag


# ----------------------------------------------------------------------------


def build_valuation(df: pd.DataFrame, *, fecha, ipc: float,
                    etiqueta: str = "T") -> Valuation:
    """Depura el universo y agrega las columnas derivadas.

    `ipc` solo interviene en dos lugares: el margen real de los indexados, que el
    reporte recalcula después en pantalla, y la duración al vencimiento de esos
    mismos títulos, que es muy poco sensible a él.
    """
    n_origen = len(df)
    issues: list[QualityIssue] = []
    exclusiones: list[ExclusionResult] = []

    # --- exclusiones declarativas -------------------------------------------
    vivo = pd.Series(True, index=df.index)
    for ex in cfg.EXCLUSIONS:
        cond = pd.Series(True, index=df.index)
        for col, val in ex.where:
            serie = df[col].astype(object).fillna("")
            cond &= serie.isin(val) if isinstance(val, tuple) else (serie == val)
        exclusiones.append(ExclusionResult(ex.id, ex.label, int((cond & vivo).sum())))
        vivo &= ~cond

    out = df[vivo].copy()

    # --- columnas derivadas -------------------------------------------------
    out["anios"] = out["dias"] / 365.0
    out["calificacion_simple"], faltantes = _homologar_calificacion(out["calificacion"])
    out["tasa_bruta"] = out["tasa_val"] / 100.0
    out["margen"] = _margen(out, ipc)
    out["familia"] = _familia(out)
    out["duracion_proveedor"] = out["duracion"]
    out["duracion"], out["duracion_calculada"], diag_dur = _duracion(out, ipc)

    # --- calidad ------------------------------------------------------------
    if faltantes:
        n = int(out["calificacion"].isin(faltantes).sum())
        issues.append(QualityIssue(
            "aviso", "calificacion_no_homologada",
            "Calificaciones que no estan en la tabla de homologacion de la hoja "
            "Set Up. Al no quedar como AAA ni F1+ se clasifican como CDT HY y no "
            "entran a las curvas. Es el mismo resultado que el Excel, donde el "
            "VLOOKUP fallaba en silencio. Para incorporarlas, agregalas a "
            "RATING_MAP en config.py.",
            n, sorted(faltantes)))

    sin_conversion = out["indicador"].isin(cfg.INDICES_SIN_CONVERSION)
    if sin_conversion.any():
        issues.append(QualityIssue(
            "info", "indices_sin_conversion",
            "Titulos indexados a IBR cargados sin ninguna conversion: su columna de "
            "tasa es la valoracion tal como la envia el proveedor. No se les "
            "construye curva ni se les calcula margen. Aparecen en la exportacion a "
            "CSV.",
            int(sin_conversion.sum()),
            sorted(out.loc[sin_conversion, "indicador"].unique())))

    dur_mala = ~(out["duracion"] > 0)
    if dur_mala.any():
        issues.append(QualityIssue(
            "aviso", "duracion_no_calculable",
            "Titulos sin duracion positiva: quedan fuera de las curvas y de la "
            "interpolacion.",
            int(dur_mala.sum()),
            out.loc[dur_mala, "nemotecnico"].drop_duplicates().head(8).tolist()))

    if np.isfinite(diag_dur["p50"]):
        severidad = ("info" if diag_dur["p50"] <= cfg.DURACION_TOLERANCIA_ANIOS
                     else "aviso")
        n_ref = f"{diag_dur['n']:,}".replace(",", ".")
        issues.append(QualityIssue(
            severidad, "validacion_duracion",
            f"La duracion calculada al vencimiento se contrasto contra la del "
            f"proveedor en los {n_ref} titulos de tasa fija con cupon, donde el "
            f"proveedor tambien la mide al vencimiento: diferencia mediana de "
            f"{diag_dur['p50']:.4f} anios y {diag_dur['p95']:.4f} en el percentil 95. "
            f"Eso valida la calculadora que se aplica a los indexados, donde el "
            f"proveedor la mide al proximo corte de cupon.",
            diag_dur["n"]))

    indexados = out["indicador"].isin(("IPC", "ICP", "IP4")) & (out["anios"] > 2)
    if int(indexados.sum()) >= 20:
        sub = out[indexados]
        r_prov = float((sub["duracion_proveedor"] / sub["anios"]).median())
        r_calc = float((sub["duracion_calculada"] / sub["anios"]).median())
        issues.append(QualityIssue(
            "info", "duracion_indexados_recalculada",
            f"En los {len(sub)} titulos indexados con mas de 2 anios al vencimiento, "
            f"el proveedor envia una duracion del {r_prov * 100:.1f} % del plazo: mide "
            f"hasta el proximo corte de cupon. La duracion calculada al vencimiento es "
            f"el {r_calc * 100:.1f} % del plazo, comparable con la de tasa fija. El "
            f"reporte usa la calculada.",
            int(len(sub))))

    cupon_neg = out["cupon"] < 0
    if cupon_neg.any():
        issues.append(QualityIssue(
            "aviso", "cupon_facial_negativo",
            "Títulos cuyo cupón facial viene negativo en el archivo. Aparecen en la "
            "columna de cupón del bloque y arrastran su promedio, sobre todo en nodos "
            "de muestra corta. No afectan a ninguna otra cifra: la duración de los "
            "indexados a tasa de corto plazo se proyecta con la tasa de valoración, "
            "no con el cupón. Vale la pena confirmar la convención con el proveedor.",
            int(cupon_neg.sum()),
            out.loc[cupon_neg, "nemotecnico"].drop_duplicates().head(8).tolist()))

    dup = out.duplicated(subset=["isin"], keep=False)
    if dup.any():
        issues.append(QualityIssue(
            "aviso", "isin_duplicado",
            "ISIN repetido: los cruces titulo a titulo toman la primera coincidencia.",
            int(dup.sum()),
            out.loc[dup, "isin"].drop_duplicates().head(8).tolist()))

    return Valuation(etiqueta=etiqueta, fecha=fecha, data=out,
                     n_origen=n_origen, exclusiones=exclusiones, issues=issues)
