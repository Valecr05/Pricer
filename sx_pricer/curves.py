"""
Capa 3: motor de curvas.

Replica la mecánica de las hojas Main / TF / IPC / TES:

  - Para cada bucket de plazo se toma el título de mayor plazo (`MAXIFS` sobre
    DIAS) y se promedian duración y tasa de los que empatan en ese plazo
    (`AVERAGEIFS`). Se añade el conteo de observaciones de cada nodo.
  - La curva TES se interpola linealmente entre los dos nodos que rodean cada
    duración. **No se extrapola**: fuera del rango observado el spread queda
    vacío en lugar de inventar un número.
  - La sección TES es descriptiva: valoración, diferencia de valoración,
    condiciones faciales y duración. Sin ajustes de curva, sin spreads y sin
    inflación implícita.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import calendar

import numpy as np
import pandas as pd

from . import config as cfg

BPS = 10_000.0


# ----------------------------------------------------------------------------
# Interpolación
# ----------------------------------------------------------------------------

@dataclass
class Curve:
    """Curva discreta (x = duración en años, y = tasa efectiva anual)."""
    x: np.ndarray
    y: np.ndarray
    nombre: str = ""

    @classmethod
    def from_points(cls, x, y, nombre: str = "") -> "Curve":
        x = np.asarray(x, dtype="float64")
        y = np.asarray(y, dtype="float64")
        ok = np.isfinite(x) & np.isfinite(y) & (x > 0)
        x, y = x[ok], y[ok]
        orden = np.argsort(x)
        x, y = x[orden], y[orden]
        if len(x):
            ux, inv = np.unique(x, return_inverse=True)
            uy = np.bincount(inv, weights=y) / np.bincount(inv)
            x, y = ux, uy
        return cls(x, y, nombre)

    def __len__(self) -> int:
        return len(self.x)

    @property
    def rango(self) -> tuple[float, float]:
        if not len(self.x):
            return (float("nan"), float("nan"))
        return (float(self.x[0]), float(self.x[-1]))

    def eval(self, xs) -> np.ndarray:
        """Interpola linealmente por tramos. Devuelve NaN fuera del rango
        observado: no se extrapola."""
        xs = np.asarray(xs, dtype="float64")
        out = np.full(xs.shape, np.nan)
        if len(self.x) < 2:
            return out
        idx = np.clip(np.searchsorted(self.x, xs) - 1, 0, len(self.x) - 2)
        x0, x1 = self.x[idx], self.x[idx + 1]
        y0, y1 = self.y[idx], self.y[idx + 1]
        with np.errstate(invalid="ignore", divide="ignore"):
            out = y0 + (xs - x0) * (y1 - y0) / (x1 - x0)
        dentro = np.isfinite(xs) & (xs >= self.x[0]) & (xs <= self.x[-1])
        out[~dentro] = np.nan
        return out


# ----------------------------------------------------------------------------
# Nodos por bucket de plazo (equivalente a la hoja Main)
# ----------------------------------------------------------------------------

def _seleccion(df: pd.DataFrame, spec: cfg.BlockSpec, familia: str) -> pd.DataFrame:
    m = (df["familia"] == familia) & (df["indicador"] == spec.indicador)
    if spec.periodicidad:
        m &= df["periodicidad"] == spec.periodicidad
    if spec.moneda:
        m &= df["moneda"] == spec.moneda
    return df[m]


def anclas_mensuales(fecha_val, meses: int) -> list[pd.Timestamp]:
    """Anclajes de la rejilla: `meses + 1` fechas desde la de valoración.

    Cada paso suma los días del mes en curso, de modo que los anclajes caen el
    mismo día de cada mes. Es la rejilla de la hoja TF del libro original
    (`B11 = B10 + DAYS(EOMONTH(B10,0), EOMONTH(B10,-1))`).
    """
    f = pd.Timestamp(fecha_val).normalize()
    fuera = [f]
    for _ in range(meses):
        f = f + pd.Timedelta(days=calendar.monthrange(f.year, f.month)[1])
        fuera.append(f)
    return fuera


def nodos_por_ventana(df: pd.DataFrame, spec: cfg.BlockSpec, familia: str, fecha_val, *,
                      rating_corto: str = cfg.RATING_CORTO,
                      rating_largo: str = cfg.RATING_LARGO) -> pd.DataFrame:
    """Un nodo por ventana mensual de vencimiento.

    A diferencia del `MAXIFS` de la hoja `Main`, que se quedaba solo con los
    títulos empatados en el plazo máximo del bucket, aquí se promedian **todos**
    los que vencen dentro de la ventana. Con eso el primer nodo de tasa fija pasa
    de un puñado de papeles a cerca de mil.

    La escala de calificación es la de corto plazo mientras la ventana termine
    dentro del primer año.
    """
    sub = _seleccion(df, spec, familia)
    sub = sub[sub["margen"].notna() & (sub["duracion"] > 0)]
    anclas = anclas_mensuales(fecha_val, spec.meses)
    inicio = pd.Timestamp(fecha_val).normalize()

    filas = []
    for i in range(len(anclas) - 1):
        desde, hasta = anclas[i], anclas[i + 1]
        dia = (desde - inicio).days
        dia_fin = (hasta - inicio).days
        rating = (rating_corto if dia_fin <= cfg.LONG_TERM_THRESHOLD_DAYS - 1
                  else rating_largo)
        b = sub[(sub["vencimiento"] >= desde) & (sub["vencimiento"] < hasta)
                & (sub["calificacion_simple"] == rating)]
        filas.append({
            "i": i,
            "desde": desde, "hasta": hasta,
            "dia": dia, "dia_fin": dia_fin,
            "dias_mes": dia_fin - dia,
            "duracion": float(b["duracion"].mean()) if len(b) else np.nan,
            "cupon": float(b["cupon"].mean()) if len(b) else np.nan,
            "tasa": float(b["margen"].mean()) if len(b) else np.nan,
            "tasa_bruta": float(b["tasa_bruta"].mean()) if len(b) else np.nan,
            "n": int(len(b)),
        })
    out = pd.DataFrame(filas)
    out["fragil"] = out["n"].between(1, cfg.MIN_TITULOS_POR_NODO - 1)
    return out


# ----------------------------------------------------------------------------
# Comparativo T vs T-1 de un bloque
# ----------------------------------------------------------------------------

@dataclass
class BlockResult:
    spec: cfg.BlockSpec
    familia: str
    tabla: pd.DataFrame
    curva_t: Curve
    curva_t1: Curve

    @property
    def es_indexado(self) -> bool:
        return self.spec.indicador in ("IPC", "ICP", "IP4")


def comparar_bloque(v_t1: pd.DataFrame, v_t: pd.DataFrame, spec: cfg.BlockSpec,
                    familia: str, *, fecha_t, fecha_t1,
                    rating_corto: str = cfg.RATING_CORTO,
                    rating_largo: str = cfg.RATING_LARGO) -> BlockResult:
    """Compara los nodos de un bloque entre las dos fechas.

    Cada fecha ancla su propia rejilla en su fecha de valoración, así que los
    renglones comparan el mismo tramo de plazo y no el mismo mes de calendario.
    """
    kw = {"rating_corto": rating_corto, "rating_largo": rating_largo}
    n0 = nodos_por_ventana(v_t, spec, familia, fecha_t, **kw)
    n1 = nodos_por_ventana(v_t1, spec, familia, fecha_t1, **kw)

    t = pd.DataFrame(index=n0.index)
    t["desde_t"], t["hasta_t"] = n0["desde"], n0["hasta"]
    t["desde_t1"], t["hasta_t1"] = n1["desde"], n1["hasta"]
    t["dias_mes_t"] = n0["dias_mes"]
    t["dia_t"], t["dia_t1"] = n0["dia"], n1["dia"]
    t["dur_t"], t["dur_t1"] = n0["duracion"], n1["duracion"]
    t["cupon_t"] = n0["cupon"]
    t["tasa_t"], t["tasa_t1"] = n0["tasa"], n1["tasa"]
    t["bruta_t"], t["bruta_t1"] = n0["tasa_bruta"], n1["tasa_bruta"]
    t["n_t"], t["n_t1"] = n0["n"], n1["n"]
    t["fragil"] = n0["fragil"] | n1["fragil"]
    t["d_tasa"] = (t["tasa_t"] - t["tasa_t1"]) * BPS
    # la tasa sin convertir tambien se compara entre fechas: en los bloques indexados
    # a IPC va en su propia columna, al lado del margen real
    t["d_bruta"] = (t["bruta_t"] - t["bruta_t1"]) * BPS

    return BlockResult(
        spec=spec, familia=familia, tabla=t.reset_index(drop=True),
        curva_t=Curve.from_points(t["dur_t"], t["tasa_t"], f"{spec.label} · {familia} · T"),
        curva_t1=Curve.from_points(t["dur_t1"], t["tasa_t1"], f"{spec.label} · {familia} · T-1"),
    )


# ----------------------------------------------------------------------------
# TES título a título (equivalente a la hoja TES)
# ----------------------------------------------------------------------------

def universo_tes(df: pd.DataFrame) -> pd.DataFrame:
    """Referencias de Nación a tasa fija, sin los nemotécnicos de relleno."""
    m = (df["familia"] == "TES") & (df["indicador"] == "FS")
    if cfg.TES_NEMOTECNICOS_EXCLUIDOS:
        m &= ~df["nemotecnico"].str.startswith(tuple(cfg.TES_NEMOTECNICOS_EXCLUIDOS))
    return df[m]


def _grupo_tes(nemo: pd.Series) -> pd.Series:
    uvr = nemo.str.startswith(tuple(cfg.TES_UVR_PREFIXES))
    cop = nemo.str.startswith(tuple(cfg.TES_COP_PREFIXES))
    return pd.Series(np.where(uvr, "UVR", np.where(cop, "COP", "OTRO")),
                     index=nemo.index, dtype=object)


@dataclass
class TESResult:
    tabla: pd.DataFrame
    curva_cop_t: Curve = field(default_factory=lambda: Curve(np.array([]), np.array([])))
    curva_cop_t1: Curve = field(default_factory=lambda: Curve(np.array([]), np.array([])))
    curva_uvr_t: Curve = field(default_factory=lambda: Curve(np.array([]), np.array([])))
    curva_uvr_t1: Curve = field(default_factory=lambda: Curve(np.array([]), np.array([])))


def analizar_tes(v_t1: pd.DataFrame, v_t: pd.DataFrame, *,
                 nominal_dv01: float = 1_000_000_000.0) -> TESResult:
    """Tabla descriptiva de los TES: condiciones faciales, duración, valoración y
    su diferencia entre fechas. La única medida derivada es el DV01."""
    a = universo_tes(v_t).set_index("isin")
    b = universo_tes(v_t1).set_index("isin")
    a = a[~a.index.duplicated()]
    b = b[~b.index.duplicated()]
    comunes = a.index.intersection(b.index)

    t = pd.DataFrame(index=comunes)
    t["nemotecnico"] = a.loc[comunes, "nemotecnico"]
    t["grupo"] = _grupo_tes(t["nemotecnico"])
    t["moneda"] = a.loc[comunes, "moneda"]
    t["periodicidad"] = a.loc[comunes, "periodicidad"]
    t["emision"] = a.loc[comunes, "emision"]
    t["vencimiento"] = a.loc[comunes, "vencimiento"]
    t["cupon"] = a.loc[comunes, "cupon"]
    t["dias"] = a.loc[comunes, "dias"]
    t["anios"] = t["dias"] / 365.0
    t["dur_t1"] = b.loc[comunes, "duracion"]
    t["dur_t"] = a.loc[comunes, "duracion"]
    t["dm_t"] = a.loc[comunes, "dm"]
    t["precio_t1"] = b.loc[comunes, "precio_sucio"]
    t["precio_t"] = a.loc[comunes, "precio_sucio"]
    t["tasa_t1"] = b.loc[comunes, "margen"]
    t["tasa_t"] = a.loc[comunes, "margen"]
    t["d_tasa"] = (t["tasa_t"] - t["tasa_t1"]) * BPS

    # DV01: sensibilidad en pesos a 1 pb de tasa sobre el nominal de referencia.
    t["dv01"] = -(t["dm_t"] * t["precio_t"]) * 1e-4 * nominal_dv01 * 0.01

    # No se incluye carry: la tabla es descriptiva. Tampoco el "slide" del Excel,
    # que tomaba la diferencia de tasa contra otro título de la lista dividida por
    # la diferencia de días y daba valores de miles de puntos base.
    t = t.sort_values(["grupo", "dias"])

    return TESResult(
        tabla=t.reset_index(),
        curva_cop_t=Curve.from_points(t.loc[t.grupo == "COP", "dur_t"],
                                      t.loc[t.grupo == "COP", "tasa_t"], "TES COP T"),
        curva_cop_t1=Curve.from_points(t.loc[t.grupo == "COP", "dur_t1"],
                                       t.loc[t.grupo == "COP", "tasa_t1"], "TES COP T-1"),
        curva_uvr_t=Curve.from_points(t.loc[t.grupo == "UVR", "dur_t"],
                                      t.loc[t.grupo == "UVR", "tasa_t"], "TES UVR T"),
        curva_uvr_t1=Curve.from_points(t.loc[t.grupo == "UVR", "dur_t1"],
                                       t.loc[t.grupo == "UVR", "tasa_t1"], "TES UVR T-1"),
    )
