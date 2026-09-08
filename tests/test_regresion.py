"""
Pruebas de regresión.

Fijan los valores validados contra el libro de Excel con los planos del 28 y 27 de
julio de 2026. Si un cambio futuro mueve cualquiera de estos números, algo se rompió.

    pytest -q                       # con los planos en la ruta por defecto
    SX_T=... SX_T1=... pytest -q    # apuntando a otros archivos
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import datetime as dt
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sx_pricer import config as cfg
from sx_pricer.bonds import MESES_POR_CUPON, calendario, duracion_al_vencimiento
from sx_pricer.config import BLOCKS, MarketParams
from sx_pricer.curves import (Curve, analizar_tes, anclas_mensuales,
                              comparar_bloque, nodos_por_ventana)
from sx_pricer.loader import SXFormatError, _to_float, read_sx
from sx_pricer.transform import build_valuation

RAIZ = Path(__file__).resolve().parent.parent
P_T = Path(os.environ.get("SX_T", "/mnt/user-data/uploads/SX_T.001"))
P_T1 = Path(os.environ.get("SX_T1", "/mnt/user-data/uploads/SX_T-1.001"))
tiene_datos = pytest.mark.skipif(
    not (P_T.exists() and P_T1.exists()),
    reason="planos SX de referencia no disponibles")

PARAMS = MarketParams(ipc_referencia=0.0614, tasa_br=0.12)
F_T, F_T1 = dt.date(2026, 7, 28), dt.date(2026, 7, 27)
CURVAS = Path(os.environ.get("SX_CURVAS", "/mnt/user-data/uploads"))
hay_curva = pytest.mark.skipif(
    not (CURVAS / "IND_IBR_20260728.txt").exists() or not (CURVAS / "IB1.xlsx").exists(),
    reason="curva IND_IBR o senda IB1.xlsx no disponibles")
IPC = PARAMS.ipc_referencia
NODE = shutil.which("node")


def _hay_jsdom() -> bool:
    """jsdom es opcional: habilita las pruebas de interfaz. `npm install jsdom`."""
    if NODE is None:
        return False
    import subprocess
    return subprocess.run([NODE, "-e", "require('jsdom')"], cwd=RAIZ,
                          capture_output=True).returncode == 0


JSDOM = _hay_jsdom()


# ============================================================================
# Lectura del plano
# ============================================================================

def test_precision_campos_de_19_caracteres():
    """Los campos de precio traen 12 ceros de relleno mas 6 digitos. Un parser que
    cuente los ceros como significativos y corte en 17 devuelve 95.65 en lugar de
    95.651. Es lo que hace pandas.to_numeric."""
    chunk = np.array([b"000000000000095.651", b"000000000000101.815"], dtype="S19")
    assert _to_float(chunk).tolist() == [95.651, 101.815]


def test_valores_ilegibles_quedan_en_nan():
    chunk = np.array([b"000000000000095.651", b"                   "], dtype="S19")
    out = _to_float(chunk)
    assert out[0] == 95.651
    assert np.isnan(out[1])


def test_archivo_truncado_se_rechaza(tmp_path):
    mal = tmp_path / "malo.001"
    mal.write_bytes(b"0000001C" + b"x" * 82 + b"\n" + b"y" * 100 + b"\n" + b"y" * 40)
    with pytest.raises(SXFormatError, match="no es uniforme"):
        read_sx(mal)


def test_archivo_sin_registro_de_control(tmp_path):
    mal = tmp_path / "malo.001"
    mal.write_bytes(b"0000001D" + b"x" * 262 + b"\n" + b"0000002D" + b"x" * 262 + b"\n")
    with pytest.raises(SXFormatError, match="registro de control"):
        read_sx(mal)


@pytest.fixture(scope="module")
def archivos():
    return read_sx(P_T), read_sx(P_T1)


@tiene_datos
def test_checksums_del_proveedor_cuadran(archivos):
    for f in archivos:
        fallidos = [c.nombre for c in f.checks if not c.ok]
        assert not fallidos, f"{f.path.name}: {fallidos}"


@tiene_datos
def test_conteo_de_registros(archivos):
    f_t, f_t1 = archivos
    assert (f_t.n_registros, str(f_t.fecha_val)) == (304_541, "2026-07-28")
    assert (f_t1.n_registros, str(f_t1.fecha_val)) == (303_404, "2026-07-27")


@tiene_datos
def test_indicadores_del_archivo(archivos):
    conteo = archivos[0].data["indicador"].value_counts().to_dict()
    assert conteo["FS"] == 291_673
    assert conteo["ICP"] == 10_166
    assert conteo["IB1"] == 1_589
    assert conteo["IPC"] == 995
    assert conteo["IB3"] == 84
    assert conteo["DTE"] == 26
    assert conteo["DTF"] == 6


# ============================================================================
# Duración al vencimiento
# ============================================================================

def test_calendario_se_ancla_al_vencimiento():
    """Restar el plazo de un cupón repetidamente arrastra el día del mes: un
    vencimiento el 31 de agosto pasa por un 28 de febrero y queda en 28 para
    siempre. El calendario se cuenta en múltiplos exactos de meses desde el
    vencimiento."""
    t = calendario(pd.Timestamp("2029-08-31"), pd.Timestamp("2026-07-28"), 3)
    fechas = [pd.Timestamp("2026-07-28") + pd.Timedelta(days=round(x * 365)) for x in t]
    assert t[-1] == pytest.approx((pd.Timestamp("2029-08-31") -
                                   pd.Timestamp("2026-07-28")).days / 365)
    # ningún pago cae en día 28 por arrastre; todos son fin de mes o el día 31
    assert all(f.day >= 27 for f in fechas)


def test_pago_unico_al_vencimiento():
    df = pd.DataFrame({
        "vencimiento": [pd.Timestamp("2027-07-28")],
        "fecha_val": [pd.Timestamp("2026-07-28")],
        "periodicidad": ["PV"], "cupon": [10.0], "tasa_val": [12.0],
        "indicador": ["FS"],
    })
    dur = duracion_al_vencimiento(df, ipc=0.06)
    assert dur.iloc[0] == pytest.approx(365 / 365)


def test_duracion_de_un_bono_con_cupon_es_menor_que_el_plazo():
    df = pd.DataFrame({
        "vencimiento": [pd.Timestamp("2031-07-28")],
        "fecha_val": [pd.Timestamp("2026-07-28")],
        "periodicidad": ["TV"], "cupon": [10.0], "tasa_val": [12.0],
        "indicador": ["FS"],
    })
    dur = float(duracion_al_vencimiento(df, ipc=0.06).iloc[0])
    plazo = 1826 / 365
    assert 0.7 * plazo < dur < plazo


@tiene_datos
def test_cupon_proyectado_de_los_flotantes(archivos):
    """Los indexados a una tasa de corto plazo cotizan a la par, así que su cupón se
    proyecta con la propia tasa de valoración. Proyectando solo el spread facial el
    precio teórico se iba once puntos por debajo del que envía el proveedor."""
    from sx_pricer.bonds import INDEXADOS_CORTO_PLAZO, MESES_POR_CUPON, calendario
    d = archivos[0].data
    ib = d[(d["indicador"] == "IB1") & d["periodicidad"].isin(MESES_POR_CUPON)
           & (d["dias"] > 200)]
    assert len(ib) > 500
    assert ib["precio_sucio"].between(99, 103).mean() > 0.95      # cotizan a la par
    assert "IB1" in INDEXADOS_CORTO_PLAZO

    def precio(fila, cupon_anual):
        m = MESES_POR_CUPON[fila.periodicidad]
        t = calendario(fila.vencimiento, fila.fecha_val, m)
        disc = (1 + fila.tasa_val / 100) ** (-t)
        vp = 100 * (cupon_anual * m / 12) * disc
        vp[-1] += 100 * disc[-1]
        return float(vp.sum())

    muestra = ib.sample(120, random_state=0)
    con_tasa = np.median([abs(precio(r, r.tasa_val / 100) - r.precio_sucio)
                          for r in muestra.itertuples()])
    con_facial = np.median([abs(precio(r, r.cupon / 100) - r.precio_sucio)
                            for r in muestra.itertuples()])
    assert con_tasa < 1.0
    assert con_facial > 5 * con_tasa


@tiene_datos
def test_calculadora_reproduce_al_proveedor_en_tasa_fija(archivos):
    """El proveedor sí mide la duración al vencimiento en los títulos de tasa
    fija. Ahí la calculadora tiene que coincidir, y eso es lo que autoriza a
    aplicarla a los indexados."""
    d = archivos[0].data
    dur = duracion_al_vencimiento(d, ipc=IPC)
    fs = d[(d["indicador"] == "FS") & d["periodicidad"].isin(MESES_POR_CUPON)
           & (d["duracion"] > 0)]
    dif = (dur.loc[fs.index] - fs["duracion"]).abs()
    assert len(fs) > 40_000
    assert dif.median() < 1e-4
    assert dif.quantile(0.99) < 0.01

    pv = d[(d["periodicidad"] == "PV") & (d["duracion"] > 0)]
    assert (dur.loc[pv.index] - pv["duracion"]).abs().median() < 1e-4


# ============================================================================
# Depuración del universo
# ============================================================================

@pytest.fixture(scope="module")
def valoraciones(archivos):
    f_t, f_t1 = archivos
    return (build_valuation(f_t.data, fecha=f_t.fecha_val, ipc=IPC, etiqueta="T"),
            build_valuation(f_t1.data, fecha=f_t1.fecha_val, ipc=IPC, etiqueta="T-1"))


@tiene_datos
def test_universo_y_exclusiones(valoraciones):
    v_t, _ = valoraciones
    assert {e.id: e.filas for e in v_t.exclusiones} == {
        "tidis": 214,
        "nacion_indexada": 10_176,
        "indices_fuera_de_alcance": 116,      # DTE 26 + DTF 6 + IB3 84
        "sin_calificacion": 1,
    }
    assert v_t.n_final == 294_034


@tiene_datos
def test_bloque_de_ibr_se_muestra_como_tasa_fija(valoraciones):
    """IB1 tiene su propio bloque de curvas, con la tasa sin convertir: se lee igual
    que la de tasa fija y no reacciona al IPC de la pantalla."""
    v_t, _ = valoraciones
    spec = next(s for s in BLOCKS if s.id == "ibr")
    assert (spec.indicador, spec.periodicidad) == ("IB1", "MV")
    assert spec.indicador not in ("IPC", "ICP", "IP4")     # se pinta como FS
    assert spec.nota                                        # aclara que no es un spread

    nodos = nodos_por_ventana(v_t.data, spec, "CDT", F_T)
    con_dato = nodos[nodos["n"] > 0]
    assert len(con_dato) >= 24
    # la tasa del nodo es la valoración cruda, sin conversión alguna
    assert np.allclose(con_dato["tasa"], con_dato["tasa_bruta"])
    assert con_dato["tasa"].between(0.10, 0.16).all()


@tiene_datos
def test_indices_fuera_de_alcance_no_quedan_en_la_base(valoraciones):
    v_t, _ = valoraciones
    assert not v_t.data["indicador"].isin(("DTF", "DTE", "IB3")).any()


@tiene_datos
def test_familias(valoraciones):
    v_t, _ = valoraciones
    f = v_t.data["familia"].value_counts().to_dict()
    assert f["TES"] == 172          # 386 Nación tasa fija − 214 TIDIS


@tiene_datos
def test_homologacion_es_la_del_excel(valoraciones):
    """La hoja Set Up no contiene VrR2-, VrR1, BRC2 ni SIN_CALIFI. Se deja igual
    por decisión de negocio: esos títulos quedan sin calificación simple, se
    clasifican como CDT HY y no entran a las curvas. La diferencia con el Excel es
    que aquí se cuentan y se muestran."""
    v_t, _ = valoraciones
    sin = v_t.data["calificacion_simple"] == "NO HOMOLOGADA"
    assert int(sin.sum()) == 9_750
    issue = next(i for i in v_t.issues if i.codigo == "calificacion_no_homologada")
    assert set(issue.muestra) == {"VrR2-", "VrR1", "BRC2", "SIN_CALIFI"}
    assert v_t.data.loc[sin, "familia"].isin(("CDT HY", "BONO", "TITULA")).all()


@tiene_datos
def test_ibr_entra_sin_ninguna_conversion(valoraciones):
    v_t, _ = valoraciones
    ib1 = v_t.data[v_t.data["indicador"] == "IB1"]
    assert len(ib1) == 1_589
    assert (ib1["margen"] == ib1["tasa_val"] / 100).all()
    assert any(i.codigo == "indices_sin_conversion" for i in v_t.issues)


@tiene_datos
def test_margen_por_indice(valoraciones):
    v_t, _ = valoraciones
    d = v_t.data
    fs = d[d["indicador"] == "FS"].iloc[0]
    assert fs["margen"] == pytest.approx(fs["tasa_val"] / 100)
    ipc = d[d["indicador"] == "IPC"].iloc[0]
    assert ipc["margen"] == pytest.approx(
        (1 + ipc["tasa_val"] / 100) / (1 + IPC) - 1)


@tiene_datos
def test_duracion_de_los_indexados_pasa_a_ser_al_vencimiento(valoraciones):
    v_t, _ = valoraciones
    d = v_t.data
    largos = d["anios"] > 2
    ipc = d[largos & (d["indicador"] == "IPC")]
    # el proveedor la mide al próximo corte de cupón
    assert (ipc["duracion_proveedor"] / ipc["anios"]).median() < 0.05
    # la que usa el reporte es al vencimiento, comparable con la de tasa fija
    assert 0.5 < (ipc["duracion"] / ipc["anios"]).median() < 1.0
    fs = d[largos & (d["indicador"] == "FS")]
    assert (fs["duracion"] / fs["anios"]).median() > 0.8


# ============================================================================
# Margen sobre IBR por el atajo de la bvc
# ============================================================================

def test_convenciones_de_conteo_de_dias():
    from sx_pricer.ibr import cronograma, dias_360, dias_act365
    # 30/360 US: el día 31 pasa a 30 en ambos extremos
    assert dias_360(dt.date(2026, 7, 28), dt.date(2026, 8, 28)) == 30
    assert dias_360(dt.date(2026, 1, 31), dt.date(2026, 3, 31)) == 60
    assert dias_360(dt.date(2026, 1, 30), dt.date(2026, 3, 31)) == 60
    # ACT/365 fijo: el 29 de febrero no cuenta
    assert dias_act365(dt.date(2028, 2, 1), dt.date(2028, 3, 1)) == 28
    assert dias_act365(dt.date(2026, 2, 1), dt.date(2026, 3, 1)) == 28
    assert dias_act365(dt.date(2026, 7, 28), dt.date(2026, 8, 28)) == 31


def test_cronograma_no_arrastra_el_dia_del_mes():
    """Restar un período cada vez llevaría un vencimiento de fin de mes a caer en
    febrero y quedarse en día 28 para siempre."""
    from sx_pricer.ibr import cronograma
    f = cronograma(dt.date(2027, 1, 31), dt.date(2026, 10, 15))
    assert f == [dt.date(2026, 10, 31), dt.date(2026, 11, 30),
                 dt.date(2026, 12, 31), dt.date(2027, 1, 31)]
    assert cronograma(dt.date(2026, 7, 28), dt.date(2026, 7, 28)) == []


@hay_curva
def test_lectura_de_la_curva_y_de_la_senda():
    from sx_pricer.ibr import leer_curva, leer_historico
    curva = leer_curva(CURVAS / "IND_IBR_20260728.txt")
    assert len(curva) == 5000
    assert min(curva) == dt.date(2026, 7, 29)      # empieza en D+1, no en D
    assert curva[dt.date(2026, 7, 29)] == pytest.approx(0.1152077853)

    serie, avisos = leer_historico(CURVAS / "IB1.xlsx")
    assert serie[dt.date(2026, 7, 28)] == pytest.approx(0.11526)
    assert serie[dt.date(2026, 7, 27)] == pytest.approx(0.11505)
    assert any("#NAME?" in a for a in avisos)      # la fila rota de Bloomberg


@hay_curva
def test_margen_atajo_reproduce_el_ejemplo_validado():
    """Nodo «1 a 1.5 Años» del bloque IBR·CDT del 28-jul-2026: plazo 549 días,
    TIR 13,521 %, 18 flujos mensuales. Verificado contra la Calculadora IBR.

    Los 18 cupones del caso principal caen el día 28, así que sus lecturas de índice
    coinciden con las de la convención anterior y el 1,15 % no se mueve.

    Los otros ocho plazos, en cambio, vencen a D + N días y sus cupones caen en días
    del mes distintos del 28: el índice del primer período se lee ahora en la senda,
    el día en que ese período empezó, y no en la fecha de valoración. Si alguno de
    esos valores se mueve al correr esta prueba, hay que re-validarlo contra la
    Calculadora IBR antes de fijar el nuevo número — no darlo por bueno.
    """
    from sx_pricer.ibr import FuenteIBR, cronograma, leer_curva, margen_atajo
    # se lee el archivo directo: lo que se valida aquí es el método, no de qué día
    # se toma la curva
    curva = leer_curva(CURVAS / "IND_IBR_20260728.txt")
    historico = FuenteIBR.cargar(CURVAS).historico
    D = dt.date(2026, 7, 28)
    # los 18 cupones caen el día 28, así que el índice del primero se lee el 28 del
    # mes anterior a su pago, que es la propia fecha de valoración
    assert historico[D] == pytest.approx(0.11526)

    venc = D + dt.timedelta(days=549)
    assert venc == dt.date(2028, 1, 28)
    assert len(cronograma(venc, D)) == 18
    m = margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13521,
                     historico=historico, curva=curva)
    assert m == 0.0115                              # 1,15 %

    # el resto de los nodos del mismo bloque, para fijar la curva completa
    esperados = {30: 0.0043, 61: 0.0035, 92: 0.0011, 184: 0.0023, 273: 0.0048,
                 364: 0.0068, 726: 0.0130, 1091: 0.0177}
    tires = {30: 0.12364, 61: 0.12399, 92: 0.12365, 184: 0.12567, 273: 0.12987,
             364: 0.13237, 726: 0.13393, 1091: 0.13341}
    for dias, esperado in esperados.items():
        assert margen_atajo(fecha_val=D, vencimiento=D + dt.timedelta(days=dias),
                            tir=tires[dias], historico=historico,
                            curva=curva) == esperado, dias


def test_el_indice_se_lee_un_mes_antes_del_pago():
    """«Previa»: la tasa del período se fijó al empezarlo, un mes antes del cupón.

    Se conserva el número del día, y si ese día no existe en el mes destino se
    recorta al último.
    """
    from sx_pricer.ibr import fecha_del_indice

    assert fecha_del_indice(dt.date(2026, 7, 15)) == dt.date(2026, 6, 15)
    assert fecha_del_indice(dt.date(2026, 12, 31)) == dt.date(2026, 11, 30)
    assert fecha_del_indice(dt.date(2027, 3, 29)) == dt.date(2027, 2, 28)
    assert fecha_del_indice(dt.date(2028, 3, 29)) == dt.date(2028, 2, 29)
    assert fecha_del_indice(dt.date(2026, 5, 31)) == dt.date(2026, 4, 30)


def test_el_nodo_vence_el_ultimo_dia_de_su_ventana():
    """El CDT sintético del margen vence el último día del rango, no en el anclaje.

    La ventana es semiabierta, así que un rango que va del 28 de agosto al 27 de
    septiembre vence el 27 de septiembre. Es la misma fecha que usa la pestaña de
    rentabilidades esperadas, así que el margen y el HPR de un rango hablan del
    mismo instrumento.
    """
    from sx_pricer.store import vencimiento_del_nodo

    D = dt.date(2026, 7, 28)
    anclas = [a.date() for a in anclas_mensuales(D, 4)]
    assert anclas[1] == dt.date(2026, 8, 28) and anclas[2] == dt.date(2026, 9, 28)

    assert vencimiento_del_nodo(D, (anclas[1] - D).days) == dt.date(2026, 8, 27)
    assert vencimiento_del_nodo(D, (anclas[2] - D).days) == dt.date(2026, 9, 27)
    for i in range(3):
        assert (vencimiento_del_nodo(D, (anclas[i + 1] - D).days)
                == anclas[i + 1] - dt.timedelta(days=1))


def test_el_primer_cupon_lee_la_senda_y_los_demas_la_curva():
    """Hoy 28-sep-2026, vencimiento 30-oct-2026, cupón mensual.

    Los cupones caen los días 30. El del 30-sep —que paga en dos días— tomó su tasa
    el 30-ago, antes de valorar, así que sale de la senda histórica. El del 30-oct la
    toma el 30-sep, después de valorar, así que sale de la curva.
    """
    from sx_pricer.ibr import cronograma, margen_atajo

    D, venc = dt.date(2026, 9, 28), dt.date(2026, 10, 30)
    assert cronograma(venc, D) == [dt.date(2026, 9, 30), dt.date(2026, 10, 30)]

    senda = {dt.date(2026, 8, 30): 0.11}
    curva = {dt.date(2026, 9, 30): 0.12}
    assert margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13,
                        historico=senda, curva=curva) is not None

    # sin el 30-ago no hay margen: la fecha se busca exacta y no se sustituye
    assert margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13,
                        historico={dt.date(2026, 9, 28): 0.11}, curva=curva) is None
    # ni sin el 30-sep en la curva
    assert margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13,
                        historico=senda, curva={dt.date(2026, 9, 28): 0.12}) is None


def test_el_margen_no_toma_el_ibr_del_dia_de_valoracion():
    """El primer cupón usa el IBR del inicio de su período, no el de hoy.

    Con la senda plana salvo en la fecha de valoración, mover ese día no cambia nada:
    lo que manda es el 30 del mes anterior al pago.
    """
    from sx_pricer.ibr import margen_atajo

    D, venc = dt.date(2026, 9, 28), dt.date(2026, 10, 30)
    curva = {dt.date(2026, 9, 30): 0.12}
    base = margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13,
                        historico={dt.date(2026, 8, 30): 0.11}, curva=curva)
    movido = margen_atajo(fecha_val=D, vencimiento=venc, tir=0.13,
                          historico={dt.date(2026, 8, 30): 0.11, D: 0.30}, curva=curva)
    assert base is not None and base == movido


@hay_curva
def test_margen_usa_la_curva_del_dia_habil_anterior(tmp_path):
    """El margen de una fecha se calcula con el archivo publicado ANTES de ella —el
    más reciente disponible, que salta fines de semana y festivos— porque es la curva
    con la que se contaba al valorar. El IBR previo sí es del propio día."""
    import shutil
    from sx_pricer.ibr import FuenteIBR

    carpeta = tmp_path / "curvas"
    carpeta.mkdir()
    shutil.copy(CURVAS / "IB1.xlsx", carpeta)
    for nombre in ("IND_IBR_20260724.txt", "IND_IBR_20260728.txt"):
        shutil.copy(CURVAS / "IND_IBR_20260728.txt", carpeta / nombre)
    f = FuenteIBR.cargar(carpeta)
    assert f.fechas_curva == [dt.date(2026, 7, 24), dt.date(2026, 7, 28)]

    # el lunes 27 toma la del viernes 24, no la del día calendario anterior
    assert f.fecha_curva_usada(dt.date(2026, 7, 27)) == dt.date(2026, 7, 24)
    # el 28 toma la del 24, porque la del 28 no es anterior a sí misma
    assert f.fecha_curva_usada(dt.date(2026, 7, 28)) == dt.date(2026, 7, 24)
    assert f.fecha_curva_usada(dt.date(2026, 7, 29)) == dt.date(2026, 7, 28)

    # sin ninguna curva anterior no hay margen, y se explica por qué
    assert f.fecha_curva_usada(dt.date(2026, 7, 24)) is None
    assert f.para_fecha(dt.date(2026, 7, 24)) is None
    assert "no hay ninguna curva anterior" in f.motivo_faltante(dt.date(2026, 7, 24))

    # la senda histórica no se desplaza con la curva: va entera, y de ella sale el
    # índice de los períodos que ya habían empezado al valorar
    curva, historico = f.para_fecha(dt.date(2026, 7, 28))
    assert historico is f.historico
    assert previo == pytest.approx(f.historico[dt.date(2026, 7, 28)])
    assert previo == pytest.approx(0.11526)
    # y la huella del caché apunta al archivo que de verdad se usa
    assert "IND_IBR_20260724.txt" in f.huella(dt.date(2026, 7, 28))

    # sin carpeta de curvas tampoco se inventa nada
    vacia = FuenteIBR.cargar(None)
    assert not vacia.activa and vacia.para_fecha(dt.date(2026, 7, 28)) is None


@hay_curva
@tiene_datos
def test_el_resumen_guarda_el_margen_y_el_cache_lo_vigila(tmp_path, curvas_listas):
    """El margen se calcula al procesar, con la curva del propio día, y la huella
    de esos insumos entra en la clave del caché."""
    from sx_pricer import store
    from sx_pricer.ibr import FuenteIBR
    fuente = FuenteIBR.cargar(curvas_listas)

    r = store.resumir(P_T, params=PARAMS, fuente_ibr=fuente)
    assert r["ibr"]["previo"] == pytest.approx(0.11526)
    assert r["ibr"]["motivo"] is None
    # el resumen deja constancia de con qué curva se calculó, y es anterior a T
    assert r["ibr"]["curva_usada"] == "2026-07-24"
    margenes = r["nodos"]["ibr|CDT"]["margen"]
    conteos = r["nodos"]["ibr|CDT"]["n"]
    assert len(margenes) == next(b for b in BLOCKS if b.id == "ibr").meses
    # hay margen en toda ventana con títulos; sin títulos no hay TIR que convertir
    assert all((m is None) == (c == 0) for m, c in zip(margenes, conteos))

    # el vencimiento supuesto es el último día de la ventana, y el margen guardado
    # reproduce el que sale de calcularlo aparte con esa misma fecha
    from sx_pricer.ibr import margen_atajo
    from sx_pricer.store import vencimiento_del_nodo
    curva, historico = fuente.para_fecha(F_T)
    brutas = r["nodos"]["ibr|CDT"]["bruta"]
    anclas = anclas_mensuales(F_T, next(b for b in BLOCKS if b.id == "ibr").meses)
    for i, (m, bruta) in enumerate(zip(margenes, brutas)):
        if bruta is None:
            continue
        venc = vencimiento_del_nodo(F_T, (anclas[i + 1].date() - F_T).days)
        assert venc == anclas[i + 1].date() - dt.timedelta(days=1), i
        assert m == margen_atajo(fecha_val=F_T, vencimiento=venc, tir=bruta,
                                 historico=historico, curva=curva), i
    # los bloques sin margen atajo no llevan la columna
    assert "margen" not in r["nodos"]["fs|CDT"]

    sin = store.resumir(P_T, params=PARAMS, fuente_ibr=FuenteIBR.cargar(None))
    assert all(x is None for x in sin["nodos"]["ibr|CDT"]["margen"])
    assert sin["ibr"]["motivo"] == "no se indicó carpeta de curvas"

    # el caché de una corrida sin curvas no se reutiliza cuando ya hay curvas
    cache = tmp_path / "c"
    a = store.procesar([P_T], params=PARAMS, cache=cache, fuente_ibr=FuenteIBR.cargar(None))
    assert a.nuevos == 1
    b = store.procesar([P_T], params=PARAMS, cache=cache, fuente_ibr=fuente)
    assert (b.nuevos, b.reutilizados) == (1, 0)
    c = store.procesar([P_T], params=PARAMS, cache=cache, fuente_ibr=fuente)
    assert (c.nuevos, c.reutilizados) == (0, 1)


# ============================================================================
# Nodos de curva contra los valores cacheados del Excel
# ============================================================================

# La comparación nodo a nodo contra la hoja Main del Excel se retiró al cambiar la
# vista de buckets de plazo a rejilla mensual de vencimientos: son cortes distintos
# y el nodo ya no se arma con MAXIFS sino promediando toda la ventana. La
# equivalencia con el libro sigue verificada donde el corte no cambió: universo,
# exclusiones, familias, duración y la tabla de TES título a título.

@tiene_datos
def test_rejilla_mensual_reproduce_la_hoja_tf(valoraciones):
    """Cada paso suma los días del mes en curso, así que los anclajes caen el mismo
    día de cada mes. Es la rejilla de la hoja TF: 31, 30, 31, 30, 31, 31, 28…"""
    a = anclas_mensuales(dt.date(2026, 8, 21), 12)
    assert [x.date().isoformat() for x in a[:4]] == [
        "2026-08-21", "2026-09-21", "2026-10-21", "2026-11-21"]
    pasos = [(a[i + 1] - a[i]).days for i in range(12)]
    assert pasos == [31, 30, 31, 30, 31, 31, 28, 31, 30, 31, 30, 31]
    acumulado = [(x - a[0]).days for x in a]
    assert acumulado == [0, 31, 61, 92, 122, 153, 184, 212, 243, 273, 304, 334, 365]


@tiene_datos
def test_nodos_promedian_toda_la_ventana(valoraciones):
    """El nodo ya no toma solo los títulos empatados en el plazo máximo: promedia
    todos los que vencen en la ventana. El primer nodo de tasa fija pasa de un
    puñado de papeles a cerca de mil, y desaparecen los nodos frágiles."""
    v_t, _ = valoraciones
    fecha = dt.date(2026, 7, 28)
    spec = next(s for s in BLOCKS if s.id == "fs")
    nodos = nodos_por_ventana(v_t.data, spec, "CDT", fecha)

    assert len(nodos) == spec.meses == 84
    assert nodos.loc[0, "n"] > 900
    assert nodos.loc[0, "dia"] == 0 and nodos.loc[0, "dia_fin"] == 31
    assert not nodos.loc[:23, "fragil"].any()

    # el promedio del nodo es el de los títulos de la ventana, sin más
    d = v_t.data
    sel = d[(d["familia"] == "CDT") & (d["indicador"] == "FS")
            & (d["periodicidad"] == "TV") & (d["duracion"] > 0)
            & (d["calificacion_simple"] == cfg.RATING_CORTO)
            & (d["vencimiento"] >= nodos.loc[0, "desde"])
            & (d["vencimiento"] < nodos.loc[0, "hasta"])]
    assert len(sel) == nodos.loc[0, "n"]
    assert nodos.loc[0, "tasa"] == pytest.approx(float(sel["margen"].mean()))
    assert nodos.loc[0, "cupon"] == pytest.approx(float(sel["cupon"].mean()))


@tiene_datos
def test_cada_bloque_tiene_su_horizonte(valoraciones):
    v_t, _ = valoraciones
    horizontes = {b.id: b.anios for b in BLOCKS}
    assert horizontes == {"fs": 7, "ipc": 3, "ibr": 3}
    for spec in BLOCKS:
        n = nodos_por_ventana(v_t.data, spec, "CDT", dt.date(2026, 7, 28))
        assert len(n) == spec.anios * 12


@tiene_datos
def test_escala_de_calificacion_por_ventana(valoraciones):
    """Corto plazo mientras la ventana termine dentro del primer año."""
    v_t, _ = valoraciones
    spec = next(s for s in BLOCKS if s.id == "fs")
    n = nodos_por_ventana(v_t.data, spec, "CDT", dt.date(2026, 7, 28))
    assert n.loc[11, "dia_fin"] == 365      # última ventana de escala corta
    assert n.loc[12, "dia_fin"] == 396


# ============================================================================
# TES
# ============================================================================

TES_EXCEL_T = {
    "COL17CT04092": (28,   0.0767,  0.06459, -7175.5),
    "COL17CT02625": (29,   0.0795,  0.05732, -8037.6),
    "COL17CT03995": (1120, 2.4975,  0.12593, -235896.7),
    "COL17CT03722": (8850, 8.6204,  0.12024, -524889.6),
    "COL17CT04043": (9999, 14.7241, 0.06075, -1516321.8),
}


@tiene_datos
def test_tes_titulo_a_titulo(valoraciones):
    v_t, v_t1 = valoraciones
    t = analizar_tes(v_t1.data, v_t.data, nominal_dv01=PARAMS.nominal_dv01).tabla.set_index("isin")
    assert len(t) == 47
    for isin, (dias, dur, tasa, dv01) in TES_EXCEL_T.items():
        r = t.loc[isin]
        assert r["dias"] == dias, isin
        assert r["dur_t"] == pytest.approx(dur, abs=5e-5), isin
        assert r["tasa_t"] == pytest.approx(tasa, abs=1e-9), isin
        assert r["dv01"] == pytest.approx(dv01, abs=0.5), isin


@tiene_datos
def test_tes_excluye_los_nemotecnicos_de_relleno(valoraciones):
    """CINAS (123 registros) y TDS (2) llegan con tasa y duración en cero."""
    v_t, v_t1 = valoraciones
    t = analizar_tes(v_t1.data, v_t.data, nominal_dv01=PARAMS.nominal_dv01).tabla
    assert not t["nemotecnico"].str.startswith(("CINAS", "TDS")).any()
    # siguen en la base de valoración, solo salen de la tabla de TES
    assert v_t.data["nemotecnico"].str.startswith("CINAS").sum() == 123


@tiene_datos
def test_tes_es_descriptivo(valoraciones):
    """Sin ajustes de curva, sin spreads, sin implícita y sin carry: la única
    medida derivada es el DV01."""
    v_t, v_t1 = valoraciones
    t = analizar_tes(v_t1.data, v_t.data, nominal_dv01=PARAMS.nominal_dv01).tabla
    prohibidas = {"spread_t", "spread_t1", "d_spread", "curva_t", "curva_t1",
                  "implicita_t", "implicita_t1", "slide", "neto", "carry"}
    assert not (prohibidas & set(t.columns))
    for col in ("cupon", "periodicidad", "emision", "vencimiento", "dias",
                "dur_t", "dur_t1", "precio_t", "tasa_t", "tasa_t1", "d_tasa", "dv01"):
        assert col in t.columns


# ============================================================================
# Interpolación
# ============================================================================

def test_interpolacion_lineal_por_tramos():
    c = Curve.from_points([1.0, 2.0, 4.0], [0.10, 0.12, 0.16])
    assert c.eval([1.0, 1.5, 3.0, 4.0]) == pytest.approx([0.10, 0.11, 0.14, 0.16])


def test_no_se_extrapola():
    c = Curve.from_points([1.0, 2.0], [0.10, 0.12])
    assert np.isnan(c.eval([0.99, 2.01, 5.0])).all()


def test_curva_promedia_duplicados_en_x():
    c = Curve.from_points([1.0, 1.0, 2.0], [0.10, 0.20, 0.30])
    assert c.x.tolist() == [1.0, 2.0]
    assert c.y.tolist() == pytest.approx([0.15, 0.30])


def test_curva_ignora_duraciones_no_positivas():
    c = Curve.from_points([0.0, -1.0, 2.0, np.nan], [0.1, 0.2, 0.3, 0.4])
    assert c.x.tolist() == [2.0]


@tiene_datos
def test_bloques_privados_son_autonomos(valoraciones):
    """La deuda privada se reporta por sí misma: plazo, duración, cupón, tasa y
    muestra. Sin curva TES de referencia, sin spread y sin inflación implícita."""
    v_t, v_t1 = valoraciones
    prohibidas = {"tes_t", "tes_t1", "d_tes", "spread_t", "spread_t1", "d_spread",
                  "implicita_t", "implicita_t1", "d_implicita", "ipc_bruta_t"}
    for spec in BLOCKS:
        res = comparar_bloque(v_t1.data, v_t.data, spec, "CDT",
                              fecha_t=F_T, fecha_t1=F_T1)
        assert not (prohibidas & set(res.tabla.columns)), spec.id
        for col in ("desde_t", "hasta_t", "dia_t", "dur_t", "cupon_t", "tasa_t",
                    "d_tasa", "n_t", "fragil"):
            assert col in res.tabla.columns, (spec.id, col)


# ============================================================================
# Parámetros y reporte
# ============================================================================

def test_parametros_rechazan_claves_desconocidas():
    with pytest.raises(ValueError, match="desconocidos"):
        MarketParams.from_dict({"ipc_referencia": .06, "tasa_br": .12, "pepito": 1})


def test_parametros_exigen_ipc_de_referencia():
    with pytest.raises(ValueError, match="ipc_referencia"):
        MarketParams.from_dict({"tasa_br": .12})


def test_parametros_aceptan_el_esquema_viejo_y_lo_reportan():
    """Los params.json escritos para la versión de dos archivos siguen sirviendo."""
    p = MarketParams.from_dict({"ipc_t": 0.0614, "ipc_t1": 0.0610,
                                "tasa_br": 0.12, "horizonte_dias": 30})
    assert p.ipc_referencia == 0.0614
    assert len(p.avisos) == 3
    assert any("ipc_t" in a for a in p.avisos)


def test_ipc_por_fecha_precarga_la_pantalla():
    p = MarketParams.from_dict({"ipc_referencia": 0.0614, "tasa_br": 0.12,
                                "ipc_por_fecha": {"2026-06-30": 0.0621}})
    assert p.ipc_de("2026-06-30") == 0.0621
    assert p.ipc_de("2026-01-15") == 0.0614      # cae al de referencia
    assert p.ipc_de(None) == 0.0614


# --- serie de fechas, caché y verificación contra el navegador ----------------

@tiene_datos
def test_cache_evita_reprocesar(tmp_path):
    from sx_pricer import store
    cache = tmp_path / "cache"
    p1 = store.procesar([P_T, P_T1], params=PARAMS, cache=cache)
    assert (p1.nuevos, p1.reutilizados) == (2, 0)
    assert len(list(cache.glob("*.json"))) == 2

    p2 = store.procesar([P_T, P_T1], params=PARAMS, cache=cache)
    assert (p2.nuevos, p2.reutilizados) == (0, 2)
    assert p2.segundos < 2.0

    p3 = store.procesar([P_T, P_T1], params=PARAMS, cache=cache, rehacer=True)
    assert (p3.nuevos, p3.reutilizados) == (2, 0)


@tiene_datos
def test_resumen_conserva_lo_necesario(tmp_path):
    from sx_pricer import store
    r = store.resumir(P_T, params=PARAMS)
    assert r["fecha"] == "2026-07-28"
    assert r["n_universo"] == 294_034
    assert r["integridad_ok"]
    assert len(r["nodos"]) == sum(len(b.familias) for b in BLOCKS)
    for clave, n in r["nodos"].items():
        spec_n = next(b for b in BLOCKS if b.id == clave.split("|")[0])
        assert len(n["bruta"]) == spec_n.meses, clave
        esperadas = {"dur", "cupon", "bruta", "n"}
        spec = next(b for b in BLOCKS if b.id == clave.split("|")[0])
        if spec.margen_atajo:
            esperadas.add("margen")
        assert set(n) == esperadas, clave
    assert len(r["tes"]["isin"]) == 47
    assert len(r["catalogo"]) == 47
    # ningún NaN ni infinito: JSON no los admite
    json.dumps(r, allow_nan=False)


def test_serie_resuelve_la_seleccion():
    from sx_pricer.store import Serie
    serie = Serie([{"fecha": f} for f in ("2026-01-30", "2026-02-27", "2026-03-31")])
    assert serie.resolver(None, posicion=0) == "2026-03-31"
    assert serie.resolver(None, posicion=1) == "2026-02-27"
    assert serie.resolver("2026-01-30", posicion=0) == "2026-01-30"
    with pytest.raises(ValueError, match="no está procesada"):
        serie.resolver("2026-01-31", posicion=0)


def test_payload_deduplica_los_textos():
    from sx_pricer.store import Serie
    base = {"catalogo": {"X": {"nemotecnico": "A"}},
            "issues": [{"severidad": "aviso", "codigo": "c1", "mensaje": "texto largo",
                        "filas": 3, "muestra": []}],
            "exclusiones": [{"id": "e1", "label": "etiqueta larga", "filas": 7}]}
    serie = Serie([dict(base, fecha="2026-01-02"), dict(base, fecha="2026-01-03")])
    payload = serie.para_json()
    assert payload["mensajes"] == {"c1": "texto largo"}
    assert payload["etiquetas"] == {"e1": "etiqueta larga"}
    for fecha in payload["porFecha"].values():
        assert "catalogo" not in fecha
        assert fecha["issues"][0] == {"sev": "aviso", "cod": "c1", "filas": 3, "muestra": []}
        assert fecha["exclusiones"][0] == {"id": "e1", "filas": 7}
    assert payload["catalogo"] == {"X": {"nemotecnico": "A"}}


@pytest.fixture(scope="module")
def reporte(tmp_path_factory):
    """Genera un reporte con las dos fechas reales."""
    if not (P_T.exists() and P_T1.exists()):
        pytest.skip("planos SX de referencia no disponibles")
    from sx_pricer.cli import main
    carpeta = tmp_path_factory.mktemp("reporte")
    pj = carpeta / "p.json"
    pj.write_text(json.dumps({"ipc_referencia": 0.0614, "tasa_br": 0.12}))
    salida = carpeta / "r.html"
    codigo = main(["--archivos", str(P_T), str(P_T1), "--params", str(pj),
                   "--cache", str(carpeta / "cache"), "-o", str(salida), "--silencioso"])
    assert codigo == 0
    return salida


@pytest.fixture(scope="module")
def curvas_listas(tmp_path_factory):
    """Carpeta de curvas con un archivo fechado ANTES de T.

    El margen se calcula con la curva del día hábil anterior, así que con solo el
    `IND_IBR` del 28 de julio ninguna fecha tendría margen. Se copia ese mismo
    archivo con fecha del 24 para que el 27 y el 28 sí tengan una curva anterior:
    lo que se ejercita es la regla de selección, no el contenido de la curva.
    """
    if not (CURVAS / "IND_IBR_20260728.txt").exists():
        pytest.skip("curva IND_IBR no disponible")
    import shutil
    carpeta = tmp_path_factory.mktemp("curvas")
    shutil.copy(CURVAS / "IND_IBR_20260728.txt", carpeta / "IND_IBR_20260724.txt")
    shutil.copy(CURVAS / "IND_IBR_20260728.txt", carpeta)
    for extra in ("IB1.xlsx", "Escenarios_IPC-IBR_VC.xlsx"):
        if (CURVAS / extra).exists():
            shutil.copy(CURVAS / extra, carpeta)
    return carpeta


def _reporte(carpeta, extra):
    from sx_pricer.cli import main
    pj = carpeta / "p.json"
    pj.write_text(json.dumps({"ipc_referencia": 0.0614, "tasa_br": 0.12}))
    salida = carpeta / "r.html"
    assert main(["--archivos", str(P_T), str(P_T1), "--params", str(pj),
                 "--cache", str(carpeta / "cache"), "-o", str(salida),
                 "--silencioso"] + extra) == 0
    return salida


@pytest.fixture(scope="module")
def reporte_con_curvas(tmp_path_factory, curvas_listas):
    """Reporte de las dos fechas reales, con curvas de IBR."""
    if not (P_T.exists() and P_T1.exists()):
        pytest.skip("planos SX de referencia no disponibles")
    return _reporte(tmp_path_factory.mktemp("con_curvas"),
                    ["--curvas", str(curvas_listas)])


@pytest.fixture(scope="module")
def reporte_completo(tmp_path_factory, curvas_listas):
    """Con curvas y con las sendas de proyección: habilita rentabilidades esperadas."""
    if not (P_T.exists() and P_T1.exists()):
        pytest.skip("planos SX de referencia no disponibles")
    if not ESCENARIOS_XLSX.exists():
        pytest.skip("archivo de escenarios no disponible")
    return _reporte(tmp_path_factory.mktemp("completo"),
                    ["--curvas", str(curvas_listas),
                     "--escenarios", str(ESCENARIOS_XLSX)])


@tiene_datos
def test_reporte_lleva_toda_la_serie(reporte):
    doc = reporte.read_text("utf-8")
    assert doc.startswith("<!DOCTYPE html>") and doc.rstrip().endswith("</html>")
    for id_script in ("sx-datos", "sx-calc", "sx-ui"):
        assert f'id="{id_script}"' in doc
    for control in ("sel-t", "sel-t1", "ipc-t", "ipc-t1", "br"):
        assert f'id="{control}"' in doc
    # el título va centrado y solo, sin las fechas al lado, y sin botones de atajo
    assert "cabecera-fechas" not in doc
    assert "flex-direction:column;align-items:center" in doc
    for retirado in ("Fecha anterior", "Cierre mes anterior", "Cierre trim. anterior",
                     "Cierre año anterior", "Volver a los del archivo", "presets",
                     "cierreAnterior", "fechaAnterior"):
        assert retirado not in doc, retirado

    crudo = re.search(r'<script id="sx-datos"[^>]*>(.*?)</script>', doc, re.S).group(1)
    datos = json.loads(crudo.replace("<\\/", "</"))
    assert datos["fechas"] == ["2026-07-27", "2026-07-28"]
    assert datos["seleccion"] == {"t": "2026-07-28", "t1": "2026-07-27"}
    assert len(datos["porFecha"]["2026-07-28"]["anclas"]) == 85
    assert len(datos["catalogo"]) == 47
    # el payload no debe poder cerrar el <script> que lo contiene
    assert "</script" not in crudo


@tiene_datos
def test_reporte_tiene_tres_pestanas(reporte):
    """Curvas por rango de plazo, rentabilidades esperadas, y comparación y control."""
    doc = reporte.read_text("utf-8")

    tabs = re.findall(
        r'<button type="button" class="tab" id="(\S+?)"[^>]*?'
        r'aria-controls="(\S+?)"[^>]*?aria-selected="(\S+?)"[^>]*?>([^<]+)</button>', doc)
    assert [(t[0], t[1], t[2]) for t in tabs] == [
        ("tab-curvas", "panel-curvas", "true"),
        ("tab-hpr", "panel-hpr", "false"),
        ("tab-datos", "panel-datos", "false"),
    ]
    assert tabs[0][3] == "Curvas por rango de plazo"

    assert doc.count('role="tablist"') == 1
    assert doc.count('role="tabpanel"') == 3
    assert "<nav>" not in doc                       # las anclas ya no aplican
    assert 'aria-labelledby="tab-datos" hidden' in doc

    def contenido(pid, hasta):
        trozo = doc[doc.index(f'id="{pid}"'):]
        return trozo[:trozo.index(hasta)]

    curvas = contenido("panel-curvas", 'id="panel-hpr"')
    datos = contenido("panel-datos", "<footer")
    assert re.findall(r'<div id="(\S+?)"', curvas) == ["bloques"]
    assert re.findall(r'<section id="(\S+?)"', datos) == [
        "resumen", "cinta", "universo", "tes", "calidad"]
    hpr = contenido("panel-hpr", 'id="panel-datos"')
    assert re.findall(r'<section id="(\S+?)"', hpr) == ["rentabilidades"]
    assert '<section id="' not in curvas             # los bloques los arma el JS

    # al imprimir salen las dos, y las gráficas se trazan al mostrar el panel
    assert ".panel[hidden]{display:block}" in doc
    assert "beforeprint" in doc and "TABS[i].dibujar();" in doc
    assert "ArrowRight" in doc and "ArrowLeft" in doc


@pytest.mark.skipif(NODE is None, reason="node no disponible")
@tiene_datos
def test_el_navegador_calcula_lo_mismo_que_python(reporte, valoraciones):
    """Ejecuta con node la capa de cálculo que corre en el navegador y compara sus
    tablas contra las de Python, celda por celda.

    Las tasas de los bloques indexados pueden diferir en el último bit: el navegador
    aplica el margen al promedio de las tasas del nodo y Python promedia el margen de
    cada título. Es la misma cuenta en aritmética real, pero no en punto flotante.
    """
    import subprocess
    v_t, v_t1 = valoraciones
    guion = Path(__file__).parent / "verificar_js.js"
    salida = subprocess.run(
        [NODE, str(guion), str(reporte), "2026-07-28", "2026-07-27", str(IPC), str(IPC)],
        capture_output=True, text=True, check=True)
    js = json.loads(salida.stdout)

    assert js["formato"] == {
        "miles": "1.234.567,89", "pct": "11,660 %", "bpsNeg": "-4,3", "bpsPos": "+7,9",
        "vacio": "\u00b7", "claseNeg": "baja", "claseCero": "neutro", "claseNula": "",
    }

    def igual(py, jsv, tol):
        py = None if py is None or (isinstance(py, float) and math.isnan(py)) else py
        if py is None or jsv is None:
            return py is None and jsv is None
        return abs(float(py) - float(jsv)) <= tol

    campos = [("dia_t", "diaT", 0), ("dia_t1", "diaT1", 0),
              ("dias_mes_t", "diasMesT", 0),
              ("dur_t", "durT", 1e-6), ("dur_t1", "durT1", 1e-6),
              ("cupon_t", "cuponT", 1e-6), ("tasa_t", "tasaT", 1e-12),
              ("tasa_t1", "tasaT1", 1e-12), ("d_tasa", "dTasa", 1e-8),
              ("bruta_t", "brutaT", 0), ("bruta_t1", "brutaT1", 0),
              ("d_bruta", "dBruta", 1e-8),
              ("n_t", "nT", 0), ("n_t1", "nT1", 0)]
    comparadas = 0
    for spec in BLOCKS:
        for familia in spec.familias:
            py = comparar_bloque(v_t1.data, v_t.data, spec, familia,
                                 fecha_t=F_T, fecha_t1=F_T1).tabla
            filas = js["bloques"][f"{spec.id}|{familia}"]
            assert len(filas) == len(py)
            for i, r in py.iterrows():
                assert filas[i]["desdeT"] == r["desde_t"].date().isoformat()
                assert filas[i]["hastaT"] == r["hasta_t"].date().isoformat()
                assert bool(filas[i]["fragil"]) == bool(r["fragil"])
                # el plazo del eje X es el final de la ventana, y cada fecha lo
                # mide contra su propia rejilla
                assert igual((r["dia_t"] + r["dias_mes_t"]) / 365,
                             filas[i]["plazoT"], 1e-12), (spec.id, familia, "plazoT")
                assert igual((r["dia_t1"] + (r["hasta_t1"] - r["desde_t1"]).days) / 365,
                             filas[i]["plazoT1"], 1e-12), (spec.id, familia, "plazoT1")
                for cpy, cjs, tol in campos:
                    assert igual(r[cpy], filas[i][cjs], tol), (spec.id, familia,
                                                               r["desde_t"], cpy)
                    comparadas += 1
    assert comparadas > 1000

    pyt = analizar_tes(v_t1.data, v_t.data,
                       nominal_dv01=PARAMS.nominal_dv01).tabla.set_index("isin")
    jst = {r["isin"]: r for r in js["tes"]}
    assert set(jst) == set(pyt.index)
    for isin, r in pyt.iterrows():
        k = jst[isin]
        assert k["nemotecnico"] == r["nemotecnico"] and k["grupo"] == r["grupo"]
        for cpy, cjs, tol in [("dias", "dias", 0), ("dur_t", "durT", 1e-6),
                              ("dur_t1", "durT1", 1e-6), ("dm_t", "dm", 1e-6),
                              ("precio_t", "precioT", 1e-6), ("tasa_t", "tasaT", 0),
                              ("tasa_t1", "tasaT1", 0), ("d_tasa", "dTasa", 1e-9),
                              ("dv01", "dv01", 0.02), ("cupon", "cupon", 1e-6)]:
            assert igual(r[cpy], k[cjs], tol), (isin, cpy)


def test_los_bloques_indexados_llevan_tasa_y_margen():
    """En IPC la tasa del proveedor va en su propio grupo, antes del margen real.

    Es la misma disposición del bloque de IBR: dos medidas del mismo nodo, cada una
    con sus tres columnas. La tasa no depende del IPC de pantalla y el margen real
    sí, así que sus dos Δ pb no tienen por qué coincidir.
    """
    from sx_pricer.report import JS

    # el grupo nuevo solo aparece en los indexados, y antes del margen real
    assert ("(indexado ? '<th class=\"grupo\" colspan=\"3\">Tasa</th>' : '') +\n"
            "    '<th class=\"grupo\" colspan=\"3\">' + (indexado ? 'Margen real' : 'Tasa')") in JS
    # y lo alimenta la tasa sin convertir, con su propia diferencia
    assert "pct(r.brutaT1)" in JS and "pct(r.brutaT)" in JS and "clase(r.dBruta)" in JS
    # el conmutador de la gráfica se extiende al bloque indexado a IPC
    assert "var conmuta = b.margenAtajo || b.indexado;" in JS
    assert "b.indexado ? 'Tasa' : 'TIR'" in JS
    # cada bloque abre en su propia serie: IPC en el margen real, IBR en la tasa
    assert "function serieDeBloque(b){ return b.indexado ? 'margen' : 'tir'; }" in JS


def test_la_tasa_del_nodo_no_depende_del_ipc():
    """La tasa sin convertir es la del proveedor: el IPC de pantalla no la mueve.

    El margen real sí, y por eso van en columnas distintas.
    """
    import subprocess
    if NODE is None:
        pytest.skip("node no disponible")
    from sx_pricer.report import JS_CALC
    fuente = JS_CALC + """
var D = { bloques: [{ id: 'ipc', indexado: true, meses: 1 }], config: { minTitulos: 3 } };
var r = { anclas: ['2026-07-28', '2026-08-28'],
          nodos: { 'ipc|CDT': { dur: [1], cupon: [3], bruta: [0.11], n: [5] } } };
var a = SX.nodos(D, r, r, 'ipc', 'CDT', 0.0614, 0.0614)[0];
var b = SX.nodos(D, r, r, 'ipc', 'CDT', 0.09, 0.09)[0];
process.stdout.write(JSON.stringify([a.brutaT, a.tasaT, b.brutaT, b.tasaT, a.dBruta]));
"""
    salida = subprocess.run([NODE, "-e", fuente], capture_output=True, text=True,
                            check=True).stdout
    bruta_a, margen_a, bruta_b, margen_b, d_bruta = json.loads(salida)
    assert bruta_a == bruta_b == 0.11              # el IPC no toca la tasa
    assert margen_a != margen_b                    # pero sí el margen real
    assert margen_a == pytest.approx(1.11 / 1.0614 - 1, abs=1e-12)
    assert margen_b == pytest.approx(1.11 / 1.09 - 1, abs=1e-12)
    assert d_bruta == 0                            # misma fecha contra sí misma


def test_las_graficas_usan_el_plazo_en_el_eje_x():
    """Las nueve gráficas de bloque y la de TES llevan el plazo en el eje X.

    En los bloques el nodo no es un título sino una ventana mensual, y su plazo es
    el final de esa ventana: la misma convención con la que ya se le calcula el
    margen sobre IBR y su rentabilidad esperada. En TES es el plazo del propio
    título. La duración sigue estando en las tablas.
    """
    from sx_pricer.report import JS

    assert JS.count("xlabel: 'Plazo (años)'") == 2      # bloques y TES
    assert "xlabel: 'Duración (años)'" not in JS
    # la duración no desaparece: sigue siendo un par de columnas de la tabla
    assert '<th class="grupo" colspan="2">Duración (años)</th>' in JS
    assert "points: pts('plazoT', campoT)" in JS
    assert "points: pts('plazoT1', campoT1)" in JS
    assert "[r.plazoT, r[campoD]]" in JS                # las barras se anclan igual
    assert "puntosTes(filas, 'COP', 'anios', 'tasaT')" in JS
    assert "puntosTes(filas, 'COP', 'aniosT1', 'tasaT1')" in JS


@pytest.mark.skipif(NODE is None, reason="node no disponible")
@tiene_datos
def test_nota_de_muestra_al_pie_de_la_tabla(reporte, valoraciones):
    """Los nodos de muestra corta se anotan al pie de la tabla y no fila por fila.
    La nota enumera la más corta de las dos listas, porque en los bloques indexados
    casi todos los nodos son de un solo título y listar veintitrés rangos no informa."""
    import subprocess
    doc = reporte.read_text("utf-8")
    assert 'class="flag"' not in doc          # ya no se marca fila por fila
    assert doc.count("nota-tabla") >= 4

    v_t, v_t1 = valoraciones
    guion = Path(__file__).parent / "verificar_js.js"
    js = json.loads(subprocess.run(
        [NODE, str(guion), str(reporte), "2026-07-28", "2026-07-27", str(IPC), str(IPC)],
        capture_output=True, text=True, check=True).stdout)

    for spec in BLOCKS:
        for familia in spec.familias:
            py = comparar_bloque(v_t1.data, v_t.data, spec, familia,
                                 fecha_t=F_T, fecha_t1=F_T1).tabla
            con_dato = py[(py["n_t"] > 0) | (py["n_t1"] > 0)]
            m = js["muestra"][f"{spec.id}|{familia}"]
            assert m["minimo"] == cfg.MIN_TITULOS_POR_NODO
            assert m["total"] == len(con_dato)
            assert len(m["rangos"]) == int(con_dato["fragil"].sum())
            assert len(m["rangosOk"]) == int((~con_dato["fragil"]).sum())
            assert len(m["rangos"]) + len(m["rangosOk"]) == m["total"]

    # en este par de fechas hay de los dos casos: bloques con lista corta y bloques
    # donde ningún nodo alcanza el mínimo
    # promediando toda la ventana los nodos dejan de ser frágiles en los tramos
    # con profundidad; el bloque de tasa fija no debería tener ninguno en el primer año
    fs_cdt = js["muestra"]["fs|CDT"]
    assert fs_cdt["total"] >= 24
    assert len(fs_cdt["rangosOk"]) > len(fs_cdt["rangos"])


# ============================================================================
# Rentabilidades esperadas
# ============================================================================

ESCENARIOS_XLSX = CURVAS / "Escenarios_IPC-IBR_VC.xlsx"
hay_escenarios = pytest.mark.skipif(not ESCENARIOS_XLSX.exists(),
                                    reason="archivo de escenarios no disponible")


@hay_escenarios
def test_lectura_de_las_sendas():
    from sx_pricer.escenarios import ESCENARIOS, Escenarios
    e = Escenarios.cargar(ESCENARIOS_XLSX)
    assert set(e.sendas) == {"IPC", "IBR"}
    ipc, ibr = e.senda("IPC"), e.senda("IBR")
    assert ipc.ultima == dt.date(2028, 1, 6)
    assert ibr.ultima == dt.date(2027, 12, 31)
    assert ipc.fechas == sorted(ipc.fechas)

    # los tres escenarios coinciden en el pasado y divergen hacia adelante
    assert ipc.vigente(dt.date(2026, 7, 28), "Alcista")[0] == pytest.approx(0.0614)
    assert ipc.vigente(dt.date(2026, 7, 28), "Bajista")[0] == pytest.approx(0.0614)
    assert ipc.vigente(dt.date(2027, 6, 1), "Alcista")[0] > \
           ipc.vigente(dt.date(2027, 6, 1), "Bajista")[0]

    # más allá del último registro se arrastra el último dato y se marca
    v, extra = ipc.vigente(dt.date(2029, 1, 1), "Base")
    assert extra and v == pytest.approx(ipc.valores["Base"][-1])
    assert not ipc.vigente(dt.date(2027, 1, 1), "Base")[1]


def test_calendario_de_cupones_hacia_atras():
    """Anclado en el vencimiento, sin arrastrar el día del mes."""
    from sx_pricer.hpr import calendario_cupones, menos_meses
    f = calendario_cupones(dt.date(2028, 8, 27), dt.date(2026, 7, 28), 4)
    assert f[0] == dt.date(2026, 8, 27) and f[-1] == dt.date(2028, 8, 27)
    assert len(f) == 9
    assert all((f[i + 1] - f[i]).days in range(89, 93) for i in range(len(f) - 1))
    # el día del mes no se arrastra al pasar por febrero
    assert menos_meses(dt.date(2027, 3, 31), 1) == dt.date(2027, 2, 28)
    assert menos_meses(dt.date(2027, 3, 31), 2) == dt.date(2027, 1, 31)


def test_xirr_resuelve_un_caso_conocido():
    from sx_pricer.hpr import xirr
    # un solo flujo a un año al 12 %
    assert xirr([(0.0, -100.0), (365.0, 112.0)]) == pytest.approx(0.12, abs=1e-9)
    assert xirr([(0.0, -100.0), (182.0, 5.0), (365.0, 107.0)]) is not None


@hay_escenarios
@tiene_datos
def test_hpr_controles_de_consistencia(valoraciones):
    """Tres invariantes que tienen que cumplirse por construcción."""
    import copy
    from sx_pricer.escenarios import Escenarios
    from sx_pricer.curves import anclas_mensuales, nodos_por_ventana
    from sx_pricer import hpr as H

    v_t, _ = valoraciones
    esc = Escenarios.cargar(ESCENARIOS_XLSX)
    anclas = anclas_mensuales(F_T, 84)
    fs = next(b for b in BLOCKS if b.id == "fs")
    nodos = nodos_por_ventana(v_t.data, fs, "CDT", F_T)

    def venc(i):
        return anclas[i + 1].date() - dt.timedelta(days=1)

    # 1) tasa fija al vencimiento con delta 0 devuelve su propia TIR
    for i in (0, 5, 11, 23):
        r = H.calcular(tipo="fs", fecha_val=F_T, vencimiento=venc(i),
                       tir=nodos.loc[i, "tasa"], cupon_facial=nodos.loc[i, "cupon"] / 100,
                       margen=0.0, escenarios=esc)
        assert r[-1].hpr == pytest.approx(nodos.loc[i, "tasa"], abs=1e-9), i

    # 2) el escenario no mueve nada en tasa fija
    base = [x.hpr for x in H.calcular(tipo="fs", fecha_val=F_T, vencimiento=venc(11),
                                      tir=nodos.loc[11, "tasa"],
                                      cupon_facial=nodos.loc[11, "cupon"] / 100,
                                      margen=0.0, escenarios=esc, escenario="Base")]
    for e in ("Alcista", "Bajista"):
        otro = [x.hpr for x in H.calcular(tipo="fs", fecha_val=F_T, vencimiento=venc(11),
                                          tir=nodos.loc[11, "tasa"],
                                          cupon_facial=nodos.loc[11, "cupon"] / 100,
                                          margen=0.0, escenarios=esc, escenario=e)]
        assert otro == base, e

    # 3) con la senda plana y delta 0, el HPR devuelve la tasa de entrada
    plana = copy.deepcopy(esc)
    for sd in plana.sendas.values():
        hoy = sd.vigente(F_T, "Base")[0]
        sd.valores = {k: [hoy] * len(sd.fechas) for k in sd.valores}
    for tipo, block_id in (("ipc", "ipc"), ("ibr", "ibr")):
        spec = next(b for b in BLOCKS if b.id == block_id)
        nn = nodos_por_ventana(v_t.data, spec, "CDT", F_T)
        for i in (6, 11):
            tir = nn.loc[i, "tasa"]
            idx = plana.senda(H.INDICE_DE[tipo]).vigente(F_T, "Base")[0]
            m = ((1 + tir) / (1 + idx) - 1 if tipo == "ipc"
                 else 12 * ((1 + tir) ** (1 / 12) - 1) - idx)
            r = H.calcular(tipo=tipo, fecha_val=F_T, vencimiento=venc(i), tir=tir,
                           cupon_facial=nn.loc[i, "cupon"] / 100, margen=m,
                           escenarios=plana)
            for x in r:
                assert x.hpr == pytest.approx(x.tasa_entrada, abs=1e-9), (tipo, i)


def test_v0_no_depende_del_escenario_en_ningun_bloque_indexado():
    """El precio de entrada es el del proveedor: la senda no interviene en V₀.

    En IPC porque los cupones posteriores al primero usan el índice de hoy «pegado»;
    en IBR porque usan la curva forward IND_IBR. En los dos, el primer cupón usa el
    índice que ya se le fijó. La salida sí proyecta con la senda, y de ahí sale toda
    la diferencia entre escenarios.
    """
    import datetime as dtm
    from sx_pricer.escenarios import ESCENARIOS, Escenarios, Senda
    from sx_pricer import hpr as H

    T, venc = dtm.date(2026, 7, 28), dtm.date(2027, 7, 27)
    fechas = [dtm.date(2026, 4, 30) + dtm.timedelta(days=30 * k) for k in range(24)]

    def senda(base, paso):      # las tres coinciden hasta T y divergen después
        return [base if f <= T else base + paso * ((f - T).days / 30) for f in fechas]

    pasos = {"Alcista": 0.0010, "Base": 0.0, "Bajista": -0.0010}
    esc = Escenarios(sendas={
        "IPC": Senda("IPC", fechas, {e: senda(0.0614, p) for e, p in pasos.items()}),
        "IBR": Senda("IBR", fechas, {e: senda(0.1150, p) for e, p in pasos.items()})})
    curva = {T + dtm.timedelta(days=k): 0.1150 for k in range(1, 1200)}

    def calcular(tipo, escenario, escenarios=esc):
        kw = dict(tipo=tipo, fecha_val=T, vencimiento=venc, escenarios=escenarios,
                  escenario=escenario)
        if tipo == "ipc":
            return H.calcular(tir=0.1107, cupon_facial=0.03, indice_entrada=0.0614,
                              margen=(1 + 0.1107) / 1.0614 - 1, **kw)
        return H.calcular(tir=0.1280, cupon_facial=0.0130, margen=0.0130,
                          curva=curva, **kw)

    for tipo in ("ipc", "ibr"):
        v0 = {e: calcular(tipo, e)[0].v0 for e in ESCENARIOS}
        assert len({round(v, 9) for v in v0.values()}) == 1, tipo
        # y el alcista rinde más: la subida no encarece la entrada y sí levanta los
        # cupones que se cobran y la venta
        h = {e: calcular(tipo, e)[0].hpr for e in ESCENARIOS}
        assert h["Alcista"] > h["Base"] > h["Bajista"], tipo

    # Con la senda plana, el HPR devuelve la tasa de entrada en IPC, en los tres
    # horizontes: entrada y salida usan la misma construcción.
    #
    # En IBR la igualdad al vencimiento es lo único que se puede pedir en este fixture.
    plana = Escenarios(sendas={k: Senda(k, fechas, {e: [b] * len(fechas)
                                                    for e in ESCENARIOS})
                               for k, b in (("IPC", 0.0614), ("IBR", 0.1150))})
    for r in (calcular("ipc", e, plana) for e in ESCENARIOS):
        for x in r:
            assert x.hpr == pytest.approx(x.tasa_entrada, abs=1e-9)
    # Aquí la TIR del fixture (12,80 %) no es la que implica un margen de 1,30 %, así
    # que a 90 y 180 días la diferencia entre las dos es rentabilidad legítima y no un
    # residuo del método. La igualdad con margen coherente la fija
    # test_el_hpr_de_ibr_se_acerca_a_la_tasa_de_entrada.
    for r in (calcular("ibr", e, plana) for e in ESCENARIOS):
        assert r[-1].hpr == pytest.approx(r[-1].tasa_entrada, abs=1e-4)


def test_v0_de_ipc_usa_la_convencion_del_proveedor():
    """Solo el primer cupón mira el índice que se le fijó; los demás, el de hoy.

    Es como valoran los proveedores de precios: el precio de hoy lleva el IPC de hoy
    «pegado» de ahí en adelante. Como consecuencia, mover el IPC de la barra sí mueve
    V₀ —entra en los cupones—, aunque la tasa de entrada siga siendo la TIR del nodo.
    """
    import datetime as dtm
    from sx_pricer.escenarios import Escenarios, Senda
    from sx_pricer import hpr as H

    T, venc = dtm.date(2026, 7, 28), dtm.date(2027, 7, 27)
    tir, facial = 0.1107, 0.03
    fechas = [dtm.date(2026, 4, 30) + dtm.timedelta(days=30 * k) for k in range(24)]
    # senda que sube 100 pb al mes: si entrara en V₀, se notaría muchísimo
    valores = [0.0614 if f <= T else 0.0614 + 0.01 * ((f - T).days / 30) for f in fechas]
    esc = Escenarios(sendas={"IPC": Senda("IPC", fechas, {"Base": valores})})

    cupones = H.calendario_cupones(venc, T, 4)
    assert H.fecha_del_indice(cupones[0], 3) <= T          # el primero ya se fijó
    assert all(H.fecha_del_indice(f, 3) > T for f in cupones[1:])

    def v0(ipc_barra):
        return H.calcular(tipo="ipc", fecha_val=T, vencimiento=venc, tir=tir,
                          cupon_facial=facial, margen=(1 + tir) / (1 + ipc_barra) - 1,
                          escenarios=esc, escenario="Base",
                          indice_entrada=ipc_barra)[0]

    # V₀ reconstruido a mano con la convención: primero el índice fijado, resto el de hoy
    ipc_barra = 0.0614
    fijado = esc.senda("IPC").vigente(H.fecha_del_indice(cupones[0], 3), "Base")[0]
    esperado = 0.0
    for i, f in enumerate(cupones):
        indice = fijado if i == 0 else ipc_barra
        flujo = H._cupon("ipc", facial, indice, 4) + (1.0 if f == venc else 0.0)
        esperado += flujo * (1 + tir) ** (-((f - T).days) / 365)
    assert v0(ipc_barra).v0 == pytest.approx(100 * esperado, abs=1e-12)

    # el IPC de la barra entra en los cupones, así que mueve el precio...
    assert v0(0.0550).v0 < v0(0.0614).v0 < v0(0.0700).v0
    # ...pero la tasa de entrada sigue siendo la TIR del nodo
    for ipc in (0.0550, 0.0614, 0.0700):
        assert v0(ipc).tasa_entrada == pytest.approx(tir, abs=1e-12)


def test_v0_de_ibr_usa_la_curva_forward_y_descuenta_a_la_tasa_del_rango():
    """El primer cupón sale de IB1; los demás, de la curva IND_IBR.

    Y todo se descuenta a la «Tasa (T)» del rango, tal cual: ya viene efectiva anual
    del proveedor, así que la tasa de entrada **es** la TIR del nodo.
    """
    import datetime as dtm
    from sx_pricer.escenarios import Escenarios, Senda
    from sx_pricer import hpr as H

    T, venc = dtm.date(2026, 7, 28), dtm.date(2026, 11, 27)
    tir, cupon = 0.1280, 0.0130
    fechas = [dtm.date(2026, 4, 30) + dtm.timedelta(days=30 * k) for k in range(24)]
    # la senda y la curva dicen cosas MUY distintas, para que se vea cuál se usó
    esc = Escenarios(sendas={"IBR": Senda("IBR", fechas,
                             {"Base": [0.1150] * len(fechas)})})
    curva = {T + dtm.timedelta(days=k): 0.2000 for k in range(1, 400)}
    publicada = {H.fecha_del_indice(H.calendario_cupones(venc, T, 12)[0], 1): 0.1153}

    r = H.calcular(tipo="ibr", fecha_val=T, vencimiento=venc, tir=tir,
                   cupon_facial=cupon, margen=0.0130, escenarios=esc,
                   escenario="Base", historico=publicada, curva=curva)[0]

    # reconstruido a mano: primer cupón de IB1, los demás de la curva, descuento al TIR
    cupones = H.calendario_cupones(venc, T, 12)
    esperado = 0.0
    for i, f in enumerate(cupones):
        indice = publicada[H.fecha_del_indice(f, 1)] if i == 0 else curva[H.fecha_del_indice(f, 1)]
        flujo = (indice + cupon) / 12 + (1.0 if f == venc else 0.0)
        esperado += flujo * (1 + tir) ** (-((f - T).days) / 365)
    assert r.v0 == pytest.approx(100 * esperado, abs=1e-12)
    assert r.tasa_entrada == pytest.approx(tir, abs=1e-12)

    # sin curva, los cupones caerían en la senda y el precio sería otro
    sin = H.calcular(tipo="ibr", fecha_val=T, vencimiento=venc, tir=tir,
                     cupon_facial=cupon, margen=0.0130, escenarios=esc,
                     escenario="Base", historico=publicada)[0]
    assert sin.v0 != pytest.approx(r.v0)


def test_ibr_no_tiene_una_tasa_de_descuento_unica():  # noqa: D401
    """V₀ usa la «Tasa (T)» tal cual y V₁ descuenta período a período.

    Fabricar una tasa única para IBR —recomponerla desde el margen con la conversión
    365/30— fue lo que abrió una brecha de hasta 211 pb entre la entrada y la salida.
    Que la función se niegue evita que alguien vuelva a intentarlo por descuido.
    """
    from sx_pricer import hpr as H

    assert H.tasa_descuento("fs", 0.13, 0.0, 0.0) == pytest.approx(0.13)
    assert H.tasa_descuento("ipc", 0.13, 0.04, 0.06) == pytest.approx(1.04 * 1.06 - 1)
    with pytest.raises(ValueError):
        H.tasa_descuento("ibr", 0.13, 0.0130, 0.1150)
    assert not hasattr(H, "PERIODOS_ANIO_IBR")


def _mundo_ibr(T, nivel=0.1150, pendiente=0.0, dias=1700):
    """Senda, histórico y curva coherentes: `pendiente` en pb por mes desde `nivel`."""
    from sx_pricer.escenarios import ESCENARIOS, Escenarios, Senda

    fechas = [T + dt.timedelta(days=k) for k in range(dias)]
    valores = [nivel + pendiente / 10000 * (k / 30) for k in range(dias)]
    esc = Escenarios(sendas={
        "IBR": Senda("IBR", fechas, {e: list(valores) for e in ESCENARIOS}),
        "IPC": Senda("IPC", fechas, {e: [0.0614] * dias for e in ESCENARIOS})})
    historico = {T - dt.timedelta(days=k): nivel for k in range(400)}
    curva = {f: v for f, v in zip(fechas[1:], valores[1:])}
    return esc, historico, curva


def test_v1_de_ibr_descuenta_periodo_a_periodo_con_el_indice_de_cada_cupon():
    """Cada período usa el índice que fijó su propio cupón, no uno solo para todos.

    La prueba que lo fija es la de par: un flotante cuyo margen iguala al cupón facial
    vale exactamente par —capital más el cupón corrido—, cualquiera que sea el nivel
    del índice y la pendiente de la senda. Es la propiedad que define a un flotante, y
    solo sale si la tasa que arma el cupón es la misma que lo descuenta.
    """
    from sx_pricer import hpr as H
    from sx_pricer.ibr import dias_360

    T, venc, cupon = dt.date(2026, 7, 28), dt.date(2027, 7, 27), 0.0130
    for pendiente in (0, 50, -50, 150):
        esc, historico, curva = _mundo_ibr(T, pendiente=pendiente)
        senda = esc.senda("IBR")
        fechas = H.calendario_cupones(venc, T, 12)
        flujos, _ = H._flujos("ibr", fechas, venc, T, cupon, esc, "Base", historico)
        salida = T + dt.timedelta(days=90)
        resto = [x for x in flujos if x[0] > salida]

        # el par sucio: 100 más lo corrido desde que empezó el período en curso
        primero = resto[0][0]
        inicio = H.fecha_del_indice(primero, 1)
        n1 = senda.vigente(inicio, "Base")[0]
        par = 100 + (n1 + cupon) * dias_360(inicio, salida) / 360 * 100

        v1 = 100 * H._valor_presente_previa(resto, salida, cupon)
        assert v1 == pytest.approx(par, abs=0.001), pendiente


def test_el_caso_dorado_de_la_metodologia_de_la_bvc():
    """El precio de referencia de la metodología, reproducido por el motor.

    Es el caso con el que se validó el método contra la Calculadora IBR: título emitido
    el 4-nov-2025 y con vencimiento el 4-nov-2026, spread 0,75 %, valorado el 27-jun-2026
    con un margen de 0,83 % y cuatro puntos de curva. El precio sucio esperado es
    100,69480315.

    Comprueba de paso que la senda de escenarios **no interviene**: se le pasa una senda
    absurda (99 %) y el precio no cambia, porque todas las lecturas salen del histórico
    y de la curva.
    """
    from sx_pricer.escenarios import ESCENARIOS, Escenarios, Senda
    from sx_pricer import hpr as H

    t0, venc = dt.date(2026, 6, 27), dt.date(2026, 11, 4)
    curva = {dt.date(2026, 7, 4): 0.1109784302, dt.date(2026, 8, 4): 0.1139034397,
             dt.date(2026, 9, 4): 0.1167108834, dt.date(2026, 10, 4): 0.1152857920}
    historico = {dt.date(2026, 6, 4): 0.10568}
    fechas = [t0 + dt.timedelta(days=k) for k in range(0, 400, 7)]
    esc = Escenarios(sendas={
        "IBR": Senda("IBR", fechas, {e: [0.99] * len(fechas) for e in ESCENARIOS}),
        "IPC": Senda("IPC", fechas, {e: [0.06] * len(fechas) for e in ESCENARIOS})})

    cal = H.calendario_cupones(venc, t0, 12)
    assert [f.isoformat() for f in cal] == ["2026-07-04", "2026-08-04", "2026-09-04",
                                            "2026-10-04", "2026-11-04"]
    flujos, _ = H._flujos("ibr", cal, venc, t0, 0.0075, esc, "Base", historico,
                          curva=curva)
    # el primer cupón lee el histórico —su período ya había empezado— y los demás la curva
    assert [round(n, 10) for _, _, n in flujos] == [
        0.10568, 0.1109784302, 0.1139034397, 0.1167108834, 0.1152857920]

    precio = 100 * H._valor_presente_previa(flujos, t0, 0.0083)
    assert precio == pytest.approx(100.69480315, abs=1e-7)


def test_el_primer_periodo_de_v1_se_descuenta_solo_por_lo_que_le_falta():
    """El exponente `L/K` va únicamente en el primer período, medido en 30/360.

    Aplicarlo a todos, o medirlo en días reales, es el error clásico. Aquí el flujo
    cae un día después de la salida y su tasa ya estaba fijada desde un mes antes:
    modalidad previa. Se descuenta 1/30 de período, no 1/365 de año ni un período.
    """
    from sx_pricer import hpr as H
    from sx_pricer.ibr import dias_360

    T, venc = dt.date(2026, 7, 28), dt.date(2027, 7, 27)
    esc, historico, _ = _mundo_ibr(T)
    fechas = H.calendario_cupones(venc, T, 12)
    flujos, _ = H._flujos("ibr", fechas, venc, T, 0.0130, esc, "Base", historico)
    salida = T + dt.timedelta(days=90)                       # 26-oct-2026
    resto = [x for x in flujos if x[0] > salida]
    assert resto[0][0] == dt.date(2026, 10, 27)
    assert dias_360(salida, resto[0][0]) == 1

    solo_uno = H._valor_presente_previa(resto[:1], salida, 0.0130)
    fecha, flujo, indice = resto[0]
    assert solo_uno == pytest.approx(flujo * (1 + (indice + 0.0130) / 12) ** (-1 / 30))


def test_el_hpr_de_ibr_se_acerca_a_la_tasa_de_entrada():
    """Con todo plano y δ = 0 el HPR ya no queda 200 pb por debajo de la «Tasa (T)».

    La referencia tiene que ser la TIR **coherente con el margen**: la que hace que el
    atajo de la bvc devuelva ese mismo margen. Es el par que el reporte alimenta, y
    contra cualquier otra TIR la diferencia es rentabilidad legítima, no residuo.

    Recomponer una tasa única de salida desde el margen dejaba entre −58 y −211 pb a 90
    días, creciendo con el plazo. Descontando V₁ período a período el residuo cae a 14
    pb o menos. Lo que queda es el choque entre el 30/360 con que se arma el precio y el
    ACT/365 con que el XIRR mide, y se cerrará cuando V₀ también se arme así.
    """
    from sx_pricer import hpr as H
    from sx_pricer.ibr import margen_atajo

    T = dt.date(2026, 7, 27)
    esc, historico, curva = _mundo_ibr(T)

    def tir_coherente(venc, margen):
        lo, hi = 0.02, 0.60
        for _ in range(200):
            mid = (lo + hi) / 2
            m = margen_atajo(fecha_val=T, vencimiento=venc, tir=mid,
                             historico=historico, curva=curva)
            if m < margen:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    for meses in (12, 24, 36):
        venc = H.menos_meses(T, -meses)
        for cupon, margen in ((0.0075, 0.0100), (0.0130, 0.0130), (0.0050, 0.0250)):
            tir = tir_coherente(venc, margen)
            r = H.calcular(tipo="ibr", fecha_val=T, vencimiento=venc, tir=tir,
                           cupon_facial=cupon, margen=margen, escenarios=esc,
                           escenario="Base", historico=historico, curva=curva)
            for x in r:
                assert abs(x.hpr - tir) < 0.0020, (meses, cupon, margen, x.dias)
            assert r[-1].hpr == pytest.approx(tir, abs=1e-5)   # al vencimiento, exacto
            assert all(x.tasa_salida is None for x in r)


def test_mover_el_margen_mueve_el_hpr_de_ibr():
    """Es para lo que existe el delta: si se mueve el margen, se mueve el HPR.

    La sensibilidad crece con el plazo —más duración— y se apaga al vencimiento,
    donde V₁ es el flujo final descontado un solo día.
    """
    from sx_pricer import hpr as H

    T, tir = dt.date(2026, 6, 27), 0.1324
    esc, historico, curva = _mundo_ibr(T)
    esperado = {12: -3.2, 24: -7.1, 36: -10.5}          # pb de HPR por pb de margen
    for meses, pendiente in esperado.items():
        venc = H.menos_meses(T, -meses)

        def hpr(delta_pb):
            return H.calcular(tipo="ibr", fecha_val=T, vencimiento=venc, tir=tir,
                              cupon_facial=0.0075, margen=0.0100, escenarios=esc,
                              escenario="Base", delta_pb=delta_pb,
                              historico=historico, curva=curva)

        arriba, abajo = hpr(1), hpr(-1)
        a_90 = (arriba[0].hpr - abajo[0].hpr) / 2 * 10000
        assert a_90 == pytest.approx(pendiente, abs=0.2), meses
        # a 180 días pesa la mitad, y al vencimiento casi nada
        assert abs((arriba[1].hpr - abajo[1].hpr) / 2 * 10000) < abs(a_90)
        assert abs(arriba[2].hpr - abajo[2].hpr) < 1e-5


def test_lo_pasado_sale_de_la_senda_publicada():
    """Las lecturas anteriores a la valoración salen de IB1.xlsx, no de escenarios.

    Es la misma fuente contra la que se calcula el margen del atajo. Solo el primer
    cupón cae de ese lado, así que es él quien cambia; si al histórico le falta ese
    día, se cae a la senda de proyección en vez de dejar el rango sin cifra.
    """
    import datetime as dtm
    from sx_pricer.escenarios import Escenarios, Senda
    from sx_pricer import hpr as H

    T, venc = dtm.date(2026, 7, 28), dtm.date(2027, 7, 27)
    fechas = [dtm.date(2026, 4, 30) + dtm.timedelta(days=30 * k) for k in range(24)]
    esc = Escenarios(sendas={"IBR": Senda("IBR", fechas,
                             {e: [0.1150] * len(fechas)
                              for e in ("Alcista", "Base", "Bajista")})})
    kw = dict(tipo="ibr", fecha_val=T, vencimiento=venc, tir=0.1280,
              cupon_facial=0.0130, margen=0.0130, escenarios=esc)

    # el primer cupón se paga el 27 de agosto y lee el 27 de julio
    primero = H.calendario_cupones(venc, T, 12)[0]
    leido = H.fecha_del_indice(primero, 1)
    assert (primero, leido) == (dtm.date(2026, 8, 27), dtm.date(2026, 7, 27))
    assert leido <= T

    sin = H.calcular(**kw)[0].v0
    con = H.calcular(**kw, historico={leido: 0.1150 + 0.02})[0].v0
    assert con > sin                       # un IBR publicado más alto sube ese cupón

    # una fecha que no es la del primer cupón no cambia nada
    otra = H.calcular(**kw, historico={dtm.date(2026, 7, 1): 0.90})[0].v0
    assert otra == pytest.approx(sin)


def test_el_margen_del_hpr_es_el_de_la_tabla_de_curvas():
    """El margen de IPC sale de la pestaña de curvas, con el IPC de la barra.

    Ese mismo IPC recompone la tasa de entrada, así que los dos se cancelan y V₀
    descuenta a la TIR del nodo, escriba lo que escriba el usuario arriba. Lo que sí
    se mueve con la barra es la tasa de venta, porque el margen entra en ella.
    """
    import datetime as dtm
    from sx_pricer.escenarios import ESCENARIOS, Escenarios, Senda
    from sx_pricer import hpr as H

    T, venc = dtm.date(2026, 7, 28), dtm.date(2027, 7, 27)
    fechas = [dtm.date(2026, 1, 1) + dtm.timedelta(days=30 * k) for k in range(30)]
    # la senda trae 6,21 % en T, distinto de lo que se escriba en la barra
    esc = Escenarios(sendas={"IPC": Senda("IPC", fechas,
                             {e: [0.0621] * len(fechas) for e in ESCENARIOS})})
    tir = 0.1107

    salidas = {}
    for ipc_barra in (0.0550, 0.0614, 0.0700):
        margen = (1 + tir) / (1 + ipc_barra) - 1        # el de la tabla de curvas
        r = H.calcular(tipo="ipc", fecha_val=T, vencimiento=venc, tir=tir,
                       cupon_facial=0.03, margen=margen, escenarios=esc,
                       indice_entrada=ipc_barra)
        # la entrada es la TIR del nodo, venga el IPC de donde venga
        assert r[0].tasa_entrada == pytest.approx(tir, abs=1e-12), ipc_barra
        assert r[0].v0 == pytest.approx(r[1].v0) == pytest.approx(r[2].v0)
        salidas[ipc_barra] = r[0].tasa_salida

    # un IPC de barra más bajo deja un margen más alto, y con él una venta más cara
    assert salidas[0.0550] > salidas[0.0614] > salidas[0.0700]

    # sin indicar el índice de entrada se cae al de la senda, como antes
    margen_senda = (1 + tir) / 1.0621 - 1
    r = H.calcular(tipo="ipc", fecha_val=T, vencimiento=venc, tir=tir,
                   cupon_facial=0.03, margen=margen_senda, escenarios=esc)
    assert r[0].tasa_entrada == pytest.approx(tir, abs=1e-12)


@hay_escenarios
@tiene_datos
def test_hpr_cupon_y_marcas(valoraciones):
    from sx_pricer.escenarios import Escenarios
    from sx_pricer.curves import anclas_mensuales, nodos_por_ventana
    from sx_pricer import hpr as H

    v_t, _ = valoraciones
    esc = Escenarios.cargar(ESCENARIOS_XLSX)
    ipc_hoy = esc.senda("IPC").vigente(F_T, "Base")[0]

    # el cupón de IPC compone con el exponente fijo 1/4
    from sx_pricer.hpr import _cupon, fecha_del_indice, menos_meses
    assert _cupon("ipc", 0.05474, ipc_hoy, 4) == pytest.approx(
        ((1 + ipc_hoy) * (1 + 0.05474)) ** 0.25 - 1)
    assert _cupon("ibr", 0.0128, 0.11387, 12) == pytest.approx((0.11387 + 0.0128) / 12)
    assert _cupon("fs", 0.09844, 0.0, 4) == pytest.approx(0.09844 / 4)

    # el índice de la tasa cupón se lee al inicio del período, un paso antes del pago,
    # en los dos índices: el cupón trimestral del 25 de agosto de 2026 usa el IPC de
    # mayo de 2026, y el mensual del 27 de agosto usa el IBR del 27 de julio
    assert fecha_del_indice(dt.date(2026, 8, 25), 3) == dt.date(2026, 5, 25)
    assert fecha_del_indice(dt.date(2026, 8, 27), 1) == dt.date(2026, 7, 27)
    registro = [f for f in esc.senda("IPC").fechas if f <= dt.date(2026, 5, 25)][-1]
    assert (registro.year, registro.month) == (2026, 5)

    # el inicio del período del primer cupón siempre cae en o antes de la valoración,
    # así que ahí el índice es un dato publicado y no una proyección
    for pagos, meses in ((4, 84), (12, 36)):
        primera = H.calendario_cupones(anclas_mensuales(F_T, meses)[meses].date(),
                                       F_T, pagos)[0]
        assert fecha_del_indice(primera, 12 // pagos) <= F_T < primera

    assert menos_meses(dt.date(2027, 3, 31), 1) == dt.date(2027, 2, 28)

    anclas = anclas_mensuales(F_T, 84)
    fs = next(b for b in BLOCKS if b.id == "fs")
    nodos = nodos_por_ventana(v_t.data, fs, "CDT", F_T)

    # la primera ventana vence a los 30 días: en 90 y 180 se marca «al vencimiento»,
    # pero en la tabla del vencimiento no, porque ahí es lo esperado
    corta = H.calcular(tipo="fs", fecha_val=F_T,
                       vencimiento=anclas[1].date() - dt.timedelta(days=1),
                       tir=nodos.loc[0, "tasa"], cupon_facial=nodos.loc[0, "cupon"] / 100,
                       margen=0.0, escenarios=esc)
    assert [x.al_vencimiento for x in corta] == [True, True, False]
    assert len({x.hpr for x in corta}) == 1        # los tres son el mismo número

    larga = H.calcular(tipo="fs", fecha_val=F_T,
                       vencimiento=anclas[24].date() - dt.timedelta(days=1),
                       tir=nodos.loc[23, "tasa"], cupon_facial=nodos.loc[23, "cupon"] / 100,
                       margen=0.0, escenarios=esc)
    assert [x.al_vencimiento for x in larga] == [False, False, False]

    # el delta solo mueve la salida, y al vencimiento su efecto es casi nulo
    ipc_spec = next(b for b in BLOCKS if b.id == "ipc")
    nn = nodos_por_ventana(v_t.data, ipc_spec, "CDT", F_T)
    tir = nn.loc[12, "tasa"]
    m = (1 + tir) / (1 + ipc_hoy) - 1
    sin_d = H.calcular(tipo="ipc", fecha_val=F_T,
                       vencimiento=anclas[13].date() - dt.timedelta(days=1), tir=tir,
                       cupon_facial=nn.loc[12, "cupon"] / 100, margen=m, escenarios=esc)
    con_d = H.calcular(tipo="ipc", fecha_val=F_T,
                       vencimiento=anclas[13].date() - dt.timedelta(days=1), tir=tir,
                       cupon_facial=nn.loc[12, "cupon"] / 100, margen=m, escenarios=esc,
                       delta_pb=100)
    assert con_d[0].v0 == pytest.approx(sin_d[0].v0)          # la entrada no se mueve
    assert con_d[0].tasa_salida > sin_d[0].tasa_salida
    assert con_d[0].hpr < sin_d[0].hpr - 0.005                # a 90 días sí pesa
    assert abs(con_d[2].hpr - sin_d[2].hpr) < 1e-4            # al vencimiento, casi nada


@pytest.mark.skipif(NODE is None, reason="node no disponible")
@hay_escenarios
@tiene_datos
def test_el_navegador_calcula_el_mismo_hpr(reporte_completo, valoraciones):
    """Corre la capa de cálculo del reporte para los tres tipos, los tres escenarios
    y tres deltas, y la compara contra hpr.py valor por valor."""
    import subprocess
    from sx_pricer.escenarios import Escenarios
    from sx_pricer import hpr as H

    guion = Path(__file__).parent / "verificar_hpr.js"
    js = json.loads(subprocess.run([NODE, str(guion), str(reporte_completo), "2026-07-28"],
                                   cwd=RAIZ, capture_output=True, text=True,
                                   check=True).stdout)
    esc = Escenarios.cargar(ESCENARIOS_XLSX)
    doc = reporte_completo.read_text("utf-8")
    datos = json.loads(re.search(r'<script id="sx-datos"[^>]*>(.*?)</script>',
                                 doc, re.S).group(1).replace("<\\/", "</"))
    r = datos["porFecha"]["2026-07-28"]

    comparadas = 0
    for tipo in ("fs", "ipc", "ibr"):
        n = r["nodos"][f"{tipo}|CDT"]
        senda = None if tipo == "fs" else esc.senda(H.INDICE_DE[tipo])
        for escenario in ("Alcista", "Base", "Bajista"):
            idx = 0.0 if senda is None else senda.vigente(F_T, escenario)[0]
            for delta in (0, 50, -75):
                for i, jr in enumerate(js[f"{tipo},{escenario},{delta}"]):
                    if jr is None:
                        continue
                    tir = n["bruta"][i]
                    m = (0.0 if tipo == "fs" else
                         (1 + tir) / (1 + idx) - 1 if tipo == "ipc" else n["margen"][i])
                    venc = (dt.date.fromisoformat(r["anclas"][i + 1])
                            - dt.timedelta(days=1))
                    assert jr["venc"] == venc.isoformat()
                    py = H.calcular(tipo=tipo, fecha_val=F_T, vencimiento=venc, tir=tir,
                                    cupon_facial=n["cupon"][i] / 100, margen=m,
                                    escenarios=esc, escenario=escenario, delta_pb=delta)
                    assert len(py) == len(jr["res"])
                    for a, b in zip(py, jr["res"]):
                        assert a.hpr == pytest.approx(b["hpr"], abs=5e-10)
                        assert a.v0 == pytest.approx(b["v0"], abs=5e-8)
                        assert a.v1 == pytest.approx(b["v1"], abs=5e-8)
                        assert a.tasa_entrada == pytest.approx(b["te"], abs=1e-12)
                        if tipo == "ibr":       # no hay una sola tasa de salida
                            assert a.tasa_salida is None and b["ts"] is None
                        else:
                            assert a.tasa_salida == pytest.approx(b["ts"], abs=1e-12)
                        assert (a.dias, a.cupones) == (b["dias"], b["cup"])
                        assert (a.al_vencimiento, a.extrapolado) == (b["av"], b["ex"])
                        comparadas += 6
    assert comparadas > 10_000


@pytest.mark.skipif(not JSDOM, reason="jsdom no instalado (npm install jsdom)")
@hay_escenarios
@tiene_datos
def test_la_pestana_de_rentabilidades_funciona(reporte_completo):
    import subprocess
    guion = Path(__file__).parent / "verificar_dom.js"
    d = json.loads(subprocess.run([NODE, str(guion), str(reporte_completo)], cwd=RAIZ,
                                  capture_output=True, text=True, check=True).stdout)
    assert d["errores"] == []

    tf = d["hprTF"]
    assert tf["panel"] and tf["tablas"] == 3
    assert tf["titulos"] == ["Horizonte 90 días", "Horizonte 180 días", "Al vencimiento"]
    assert tf["tipoActivo"] == ["fs"] and tf["escenarioActivo"] == ["Base"]
    assert tf["escDeshabilitados"] == 3        # la tasa fija no usa escenario
    assert tf["filas"] % 3 == 0 and tf["filas"] // 3 > 40
    assert tf["notas"] == 3

    # barras de diferencia en el eje derecho, en los tres bloques y pegadas
    for gid, g in d["barras"].items():
        assert g["barras"] > 0, gid
        assert g["huecosEntreBarras"] == 0, gid       # sin espacio entre barras
        assert g["rotuloDelta"], gid
        assert "0" in g["ejeDelta"], gid              # la escala pasa por cero
        assert g["ejeDelta"] == sorted(g["ejeDelta"], key=float), gid
        # simétrica alrededor de cero, para que el signo se lea de inmediato
        extremos = [float(g["ejeDelta"][0]), float(g["ejeDelta"][-1])]
        assert extremos[0] == -extremos[1], gid
        # una barra por punto de la curva de T
        assert g["barras"] * 2 == g["puntos"], gid
    assert d["barrasTes"] == 0                        # en TES no se pidieron

    # un boton de Excel por tabla, en la esquina de su tarjeta y con nombre propio
    for clave, e in d["excel"].items():
        if clave == "nombres":
            continue
        assert e["tablas"] > 0, clave
        assert e["botones"] == e["tablas"], clave
        assert e["bienColocados"] == e["botones"], clave
    assert len(set(d["excel"]["nombres"])) == len(d["excel"]["nombres"])

    # el escenario no mueve la tasa fija; sí mueve IPC
    assert d["hprTFAlcista"] == tf["hpr90"]
    assert d["hprIPCBajista"] != d["hprIPCBase"]["hpr90"]
    # el delta mueve el resultado
    assert d["hprIPCDelta"] != d["hprIPCBase"]["hpr90"]
    # los rangos cortos se marcan y los largos no
    assert "(al venc.)" in tf["hpr90"][0] and "(al venc.)" not in tf["hpr90"][3]
    # IBR necesita la senda más allá de su último dato en los plazos largos
    assert d["hprIBR"]["extrap"] > 0


# --- interfaz: el reporte se ejecuta de verdad en un DOM ----------------------

@pytest.mark.skipif(not JSDOM, reason="jsdom no instalado (npm install jsdom)")
@tiene_datos
def test_la_interfaz_se_renderiza_y_reacciona(reporte):
    """Carga el reporte en un DOM real, cambia de pestaña, mueve el IPC y cambia la
    fecha de comparación.

    Cubre lo que una prueba de datos no ve. La primera versión de las pestañas
    actualizaba el ancla de la dirección antes de trazar la gráfica; abierto con
    doble clic el protocolo es file://, cuyo origen es «null», y ahí replaceState
    lanza SecurityError, cortaba la función y la gráfica de TES quedaba vacía.
    """
    import subprocess
    guion = Path(__file__).parent / "verificar_dom.js"
    r = subprocess.run([NODE, str(guion), str(reporte)], cwd=RAIZ,
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)

    assert d["errores"] == []

    inicial = d["alCargar"]
    assert inicial["panelVisible"] == ["panel-curvas"]
    assert inicial["pestanaActiva"] == ["tab-curvas"]
    assert len(inicial["graficasBloque"]) == sum(len(b.familias) for b in BLOCKS)
    assert all(g["svg"] == 1 and g["series"] == 2 for g in inicial["graficasBloque"])
    assert inicial["tablasBloque"] == len(inicial["graficasBloque"])
    # por tabla: una nota de muestra y una de ventana; más una de curva faltante
    # en los bloques con margen sobre IBR
    con_margen = sum(len(b.familias) for b in BLOCKS if b.margen_atajo)
    assert inicial["notas"] == 2 * inicial["tablasBloque"] + con_margen
    assert inicial["tiles"] == 6
    assert inicial["camposCinta"] == len(cfg.DETAIL_LAYOUT)
    assert inicial["embudos"] == 2
    assert inicial["avisos"] >= 1
    assert inicial["fechasEnSelect"] == 2
    assert " vs " in inicial["titulo"]

    # la gráfica de TES solo se puede trazar cuando su panel es visible
    assert inicial["tes"]["svg"] == 0
    abierto = d["trasAbrirDatos"]
    assert abierto["panelVisible"] == ["panel-datos"]
    for campo, valor in (("existe", True), ("svg", 1), ("series", 4), ("puntos", 90)):
        assert abierto["tes"][campo] == valor, campo
    assert abierto["filasTes"] == 47

    # y se vuelve a trazar tras cambiar de fecha con la pestaña cerrada
    assert d["trasCambiarFechaYAbrirDatos"]["tes"]["series"] == 4

    # cada campo de IPC mueve solo su propia fecha
    antes, tras_t, tras_t1 = (d["margenAntes"], d["margenTrasIpcT"],
                              d["margenTrasIpcT1"])
    assert tras_t["t1"] == antes["t1"] and tras_t["t"] != antes["t"]
    assert tras_t1["t"] == tras_t["t"] and tras_t1["t1"] != antes["t1"]
    for m in (antes, tras_t, tras_t1):
        assert m["t"].endswith("%") and m["t1"].endswith("%")

    # un par de fechas inválido se avisa y no se compromete
    assert "anterior a T" in d["parInvalido"]["aviso"]
    assert d["parInvalido"]["t1"] < d["parInvalido"]["t"]


@pytest.mark.skipif(not JSDOM, reason="jsdom no instalado (npm install jsdom)")
@hay_curva
@tiene_datos
def test_la_interfaz_muestra_el_margen_ibr(reporte_con_curvas):
    """Columnas de margen y conmutador TIR/Margen, solo en el bloque de IBR."""
    import subprocess
    guion = Path(__file__).parent / "verificar_dom.js"
    d = json.loads(subprocess.run([NODE, str(guion), str(reporte_con_curvas)], cwd=RAIZ,
                                  capture_output=True, text=True, check=True).stdout)
    assert d["errores"] == []

    # el conmutador está en los dos bloques que tienen dos medidas del mismo nodo
    con_dos = [b for b in BLOCKS if b.margen_atajo or b.indicador in ("IPC", "ICP", "IP4")]
    assert d["conmutadores"]["botones"] == 2 * sum(len(b.familias) for b in con_dos)
    assert set(d["conmutadores"]["etiquetas"]) == {"TIR", "Tasa", "Margen"}
    # el conmutador nunca se esconde: si una fecha no tiene margen queda visible y
    # deshabilitado con el motivo en el titulo, en vez de desaparecer sin explicacion
    assert d["conmutadores"]["deshabilitados"] == d["conmutadores"]["conTitulo"]
    assert d["tablaFs"]["conmutadores"] == 0

    # el bloque de IBR abre en la tasa y conmuta al margen del atajo
    g = d["grafica"]
    assert g["id"].startswith("ch-ibr-")
    assert g["porDefectoEje"] == "Tasa" and g["otraEje"] == "Margen sobre IBR"
    assert g["otraPuntos"] == g["porDefectoPuntos"]     # ambas fechas con margen
    assert g["pressedOtra"] == "true"
    assert g["vuelvePuntos"] == g["porDefectoPuntos"]

    # tres columnas más en el bloque de IBR y ninguna en el de tasa fija
    assert d["tablaIbr"]["celdas"] == d["tablaFs"]["celdas"] + 3
    assert "Margen sobre IBR (atajo bvc)" in d["tablaIbr"]["encabezados"]
    # «sin curva» solo en la columna de la fecha sin archivo, en todos los buckets
    # las dos fechas tienen curva anterior disponible, así que no hay celdas vacías
    assert d["tablaIbr"]["sinCurva"] == 0
    assert d["tablaFs"]["sinCurva"] == 0
    assert any("curva del día hábil anterior" in n for n in d["tablaIbr"]["notas"])


@pytest.mark.skipif(not JSDOM, reason="jsdom no instalado (npm install jsdom)")
@tiene_datos
def test_la_interfaz_muestra_la_tasa_en_el_bloque_de_ipc(reporte):
    """El bloque de IPC lleva la tasa del proveedor junto al margen real.

    No necesita curvas de IBR: la tasa sale del propio plano.
    """
    import subprocess
    guion = Path(__file__).parent / "verificar_dom.js"
    d = json.loads(subprocess.run([NODE, str(guion), str(reporte)], cwd=RAIZ,
                                  capture_output=True, text=True, check=True).stdout)
    assert d["errores"] == []

    # tres columnas más que en tasa fija, y el grupo nuevo antes del margen real
    assert d["tablaIpc"]["celdas"] == d["tablaFs"]["celdas"] + 3
    grupos = d["tablaIpc"]["encabezados"][:7]
    assert grupos.index("Tasa") < grupos.index("Margen real")

    # la gráfica abre en el margen real, conmuta a la tasa y vuelve
    g = d["graficaIpc"]
    assert g["id"].startswith("ch-ipc-")
    assert g["porDefectoEje"] == "Margen real" and g["otraEje"] == "Tasa"
    assert g["otraPuntos"] == g["porDefectoPuntos"]
    assert g["pressedOtra"] == "true"
    assert g["vuelveEje"] == "Margen real"


@tiene_datos
def test_cli_rechaza_un_par_invalido(tmp_path):
    from sx_pricer.cli import main
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps({"ipc_referencia": .06, "tasa_br": .12}))
    comun = ["--archivos", str(P_T), str(P_T1), "--params", str(pj),
             "--cache", str(tmp_path / "c"), "-o", str(tmp_path / "r.html"), "--silencioso"]
    # T-1 posterior a T
    assert main(comun + ["--t", "2026-07-27", "--t1", "2026-07-28"]) == 1
    # fecha que no está en la serie
    assert main(comun + ["--t", "2026-07-15"]) == 1


def test_cli_sin_archivos_avisa(tmp_path, capsys):
    from sx_pricer.cli import main
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps({"ipc_referencia": .06, "tasa_br": .12}))
    assert main(["--archivos", str(tmp_path / "no-existe-*.001"), "--params", str(pj),
                 "--sin-cache", "-o", str(tmp_path / "r.html"), "--silencioso"]) == 1


def test_encabezado_pegajoso_se_mide_contra_su_contenedor():
    """`.tw` fija un eje del overflow, lo que lo convierte en contexto de scroll: el
    position:sticky del encabezado se mide contra ESE contenedor y no contra la
    ventana. Con `top:var(--top-h)` el encabezado quedaba empujado unos 100 px hacia
    dentro de la tabla, de forma permanente, tapando una fila de datos. Debe ir a
    `top:0`, y el contenedor necesita altura maxima para tener scroll propio.

    La fila de agrupacion (colspan) va static: si las dos fueran pegajosas al mismo
    top se superpondrian entre si.
    """
    from sx_pricer.report import CSS
    assert ".tw{overflow:auto;max-height:" in CSS
    assert "thead th:not(.grupo){position:sticky;top:0" in CSS
    assert "position:static" in CSS[CSS.index("thead th.grupo{"):
                                    CSS.index("thead th.grupo{") + 220]
    # ninguna regla de encabezado debe volver a medirse contra la ventana
    tablas = CSS[CSS.index(".tw{"):CSS.index("@media")]
    assert "--top-h" not in tablas
    # al imprimir no hay scroll: el contenedor se suelta para que la tabla pagine
    assert ".tw{overflow:visible;max-height:none}" in CSS


@pytest.mark.skipif(not JSDOM, reason="jsdom no instalado (npm install jsdom)")
def test_el_boton_de_excel_produce_un_xlsx_que_abre_sin_avisos(tmp_path):
    """El reporte escribe un .xlsx de verdad, sin librerías y sin red.

    Un CSV solo abriría bien en un Excel con la configuración regional en español,
    porque el reporte usa coma decimal y punto de miles. Dentro del xlsx los números
    van con punto decimal —lo fija el estándar, no la máquina— y Excel los muestra
    según la configuración de cada quien.

    Se comprueba sobre una tabla con todo lo que el lector tiene que saber deshacer:
    cabecera de grupos con `colspan`, porcentajes, punto de miles, negativos, el punto
    medio de «sin dato», la marca de extrapolación, el «(al venc.)» y texto con
    caracteres que hay que escapar en XML.
    """
    import subprocess
    import warnings
    import zipfile

    import openpyxl

    destino = tmp_path / "salida.xlsx"
    salida = subprocess.run([NODE, str(RAIZ / "tests" / "verificar_xls.js"), str(destino)],
                            cwd=RAIZ, capture_output=True, text=True, check=True)
    assert json.loads(salida.stdout)["nombre"] == "IPC CDT 2026-07-28.xlsx"

    with zipfile.ZipFile(destino) as z:
        assert z.testzip() is None                      # el ZIP hecho a mano es válido
        assert "xl/worksheets/sheet1.xml" in z.namelist()

    with warnings.catch_warnings():
        warnings.simplefilter("error")                  # openpyxl no debe tener nada que decir
        hoja = openpyxl.load_workbook(destino).worksheets[0]

    assert hoja.title == "IPC CDT"      # el nombre lo pone `data-xls`, no el <h3>
    filas = [[c.value for c in f] for f in hoja.iter_rows()]
    assert filas[0] == ["Ventana", None, "Tasa", None]  # el colspan deja el hueco
    assert filas[1] == ["Desde", "Hasta", "T-1", "T"]
    # los porcentajes entran como fracción y con formato de porcentaje, no como texto
    assert filas[2][2] == pytest.approx(0.11070)
    assert hoja.cell(3, 3).number_format == "0.000%"
    # «·» es una celda vacía, no la cadena «·»
    assert filas[3][2] is None
    # la marca de extrapolación y el «(al venc.)» son adorno, no dato
    assert filas[3][3] == pytest.approx(0.12800)
    assert filas[4][3] == pytest.approx(-0.00500)
    # punto de miles deshecho, delta sin su signo, y el cero que no se pierde
    assert filas[4][2] == pytest.approx(1234.567)
    assert filas[5][2] == pytest.approx(12.3)
    assert filas[4][1] == "2026-11-27"
    # lo que no es número queda como texto, con el XML bien escapado
    assert [c.value for c in hoja[6]] == ["TFIT16<240724>", '"comillas" & ampersand', 12.3, 0]
    # las dos filas de encabezado van en negrita y las de datos no
    assert hoja.cell(1, 1).font.bold and hoja.cell(2, 1).font.bold
    assert not hoja.cell(3, 1).font.bold
