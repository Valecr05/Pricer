"""
Lectura del archivo plano SX.

El archivo es de longitud de registro fija (270 bytes + terminador), lo que
permite leerlo de una sola pasada y cortar las columnas de forma vectorizada.
Eso lo hace ~2-3 segundos para 300.000 registros en lugar de minutos.

También valida los tres controles que el proveedor entrega en el registro de
cabecera y que el proceso de Excel descartaba.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CONTROL_LAYOUT, DETAIL_LAYOUT, CHECKSUM_TOLERANCE, Field

ENCODING = "cp1252"


class SXFormatError(Exception):
    """El archivo no tiene la forma esperada de un plano SX."""


@dataclass
class Check:
    nombre: str
    esperado: object
    obtenido: object
    ok: bool

    @property
    def detalle(self) -> str:
        if self.ok:
            return "coincide"
        return f"declarado {self.esperado} vs calculado {self.obtenido}"


@dataclass
class SXFile:
    path: Path
    fecha_val: dt.date
    n_registros: int
    checks: list[Check] = field(default_factory=list)
    data: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_primer_registro: str = ""
    lectura_segundos: float = 0.0

    @property
    def integridad_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _raw(body: np.ndarray, f: Field) -> np.ndarray:
    """Corta una columna del bloque de bytes sin convertirla."""
    return body[:, f.start:f.end].copy().view(f"S{f.width}").ravel()


def _to_float(chunk: np.ndarray) -> np.ndarray:
    """Convierte un vector de bytes a float64 con precisión completa.

    No usar pandas.to_numeric aquí: su parser cuenta los ceros de relleno del
    plano como dígitos significativos y corta en 17, de modo que un campo de 19
    caracteres como '000000000000095.651' se convierte en 95.65. Eso desplazaba
    las sumas de control del archivo en más de mil pesos por fecha.

    numpy.astype usa strtod del sistema (exacto) y además es más rápido, pero
    levanta ValueError si hay un valor no numérico. En ese caso se cae a un
    recorrido elemento por elemento que deja NaN donde no se pudo leer.
    """
    try:
        return chunk.astype(np.float64)
    except ValueError:
        out = np.full(len(chunk), np.nan, dtype=np.float64)
        for i, v in enumerate(chunk):
            try:
                out[i] = float(v)
            except ValueError:
                pass
        return out


def _parse(chunk: np.ndarray, f: Field) -> pd.Series:
    if f.kind == "txt":
        return pd.Series(chunk).str.decode(ENCODING).str.strip()
    if f.kind == "num":
        return pd.Series(_to_float(chunk))
    if f.kind == "date":
        return pd.to_datetime(pd.Series(chunk).str.decode(ENCODING),
                              format="%Y%m%d", errors="coerce")
    raise ValueError(f.kind)


def _parse_control(line: str) -> dict:
    out: dict = {}
    for f in CONTROL_LAYOUT:
        if f.kind == "skip":
            continue
        txt = line[f.start:f.end]
        if f.kind == "num":
            out[f.name] = float(txt)
        elif f.kind == "date":
            out[f.name] = dt.datetime.strptime(txt, "%Y%m%d").date()
        else:
            out[f.name] = txt.strip()
    return out


def read_sx(path: str | Path, *, fecha_esperada: dt.date | None = None) -> SXFile:
    """Lee un archivo SX completo, valida su integridad y devuelve un SXFile.

    Levanta SXFormatError si el archivo no es un plano SX de registro fijo.
    Las discrepancias de checksum no levantan excepción: quedan registradas en
    `checks` para que el reporte las muestre y el operador decida.
    """
    import time
    t0 = time.perf_counter()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo de precios: {path}")

    blob = path.read_bytes()
    if not blob:
        raise SXFormatError(f"{path.name} está vacío")

    nl = blob.find(b"\n")
    if nl < 0:
        raise SXFormatError(f"{path.name} no tiene saltos de línea")
    hdr_len = nl + 1

    nl2 = blob.find(b"\n", hdr_len)
    if nl2 < 0:
        raise SXFormatError(f"{path.name} no tiene registros de detalle")
    rec_len = nl2 + 1 - hdr_len

    resto = len(blob) - hdr_len
    if rec_len == 0 or resto % rec_len != 0:
        raise SXFormatError(
            f"{path.name}: la longitud de registro no es uniforme "
            f"(cabecera {hdr_len} B, registro {rec_len} B, cuerpo {resto} B). "
            "El archivo puede estar truncado o mezclar formatos."
        )
    n = resto // rec_len

    header_line = blob[:nl].decode(ENCODING)
    if header_line[7:8] != "C":
        raise SXFormatError(
            f"{path.name}: la primera línea no es un registro de control "
            f"(se esperaba 'C' en la posición 8, se encontró {header_line[7:8]!r})"
        )
    ctl = _parse_control(header_line)

    body = np.frombuffer(blob, dtype=np.uint8, offset=hdr_len).reshape(n, rec_len)

    tipos = pd.Series(_raw(body, DETAIL_LAYOUT[1])).str.decode(ENCODING).str.strip()
    no_detalle = int((tipos != "D").sum())

    cols: dict[str, pd.Series] = {}
    for f in DETAIL_LAYOUT:
        if f.kind == "skip":
            continue
        cols[f.name] = _parse(_raw(body, f), f)
    df = pd.DataFrame(cols)

    checks = [
        Check("Número de registros", ctl["n_registros"], float(n),
              int(ctl["n_registros"]) == n),
        Check("Suma de control · precio sucio", round(ctl["suma_sucio"], 3),
              round(float(df["precio_sucio"].sum()), 3),
              abs(ctl["suma_sucio"] - df["precio_sucio"].sum()) <= CHECKSUM_TOLERANCE),
        Check("Suma de control · precio limpio", round(ctl["suma_limpio"], 3),
              round(float(df["precio_limpio"].sum()), 3),
              abs(ctl["suma_limpio"] - df["precio_limpio"].sum()) <= CHECKSUM_TOLERANCE),
        Check("Todos los registros son de detalle", 0, no_detalle, no_detalle == 0),
    ]

    fecha_val = ctl["fecha_val"]
    fechas_distintas = df["fecha_val"].dt.date.nunique(dropna=True)
    checks.append(Check("Fecha de valoración única en el archivo", 1,
                        int(fechas_distintas), fechas_distintas == 1))
    if fechas_distintas == 1:
        fecha_detalle = df["fecha_val"].dt.date.iloc[0]
        checks.append(Check("Fecha del detalle coincide con la cabecera",
                            fecha_val.isoformat(), fecha_detalle.isoformat(),
                            fecha_detalle == fecha_val))

    if fecha_esperada is not None:
        checks.append(Check("Fecha del archivo coincide con la solicitada",
                            fecha_esperada.isoformat(), fecha_val.isoformat(),
                            fecha_val == fecha_esperada))

    return SXFile(
        path=path,
        fecha_val=fecha_val,
        n_registros=n,
        checks=checks,
        data=df,
        raw_primer_registro=blob[hdr_len:hdr_len + rec_len - 1].decode(ENCODING),
        lectura_segundos=time.perf_counter() - t0,
    )
