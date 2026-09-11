"""
Capa 4: reporte HTML.

Un solo archivo, sin dependencias de red, con toda la serie de fechas embebida. El
usuario elige en pantalla cuál fecha es T y cuál T-1, y las tablas y gráficas se
arman en el navegador. También ajusta el IPC de cada fecha y la tasa del Banco de
la República.

Las tablas se construyen en el navegador y no en Python porque el par de fechas se
decide al momento: pre-renderizar todas las combinaciones de un año serían más de
treinta mil tablas. Lo que va embebido es el resumen de cada fecha, unos 9 KB, así
que un año de historia cabe en poco más de dos megabytes.

Que el recálculo sea exacto depende de una propiedad del margen real: es una función
afín de la tasa de valoración, así que el promedio de los márgenes de los títulos de
un nodo es igual a la fórmula aplicada al promedio de sus tasas. Por eso basta con
guardar la tasa bruta promedio de cada nodo.
"""
from __future__ import annotations

import datetime as dt
import html
import json

from . import config as cfg
from .config import DETAIL_LAYOUT, MarketParams
from .hpr import HORIZONTES, INDICE_DE, PAGOS_POR_ANIO


def e(x) -> str:
    return html.escape(str(x))


# ----------------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------------

CSS = """
/* Azul corporativo y verde sobre gris muy claro. Todas las combinaciones de texto
   usadas cumplen AA (4.5:1). Las dos series de las gráficas —azul #1A5FA8 y verde
   #0E8A4A— están validadas para daltonismo: ΔE de 21,2 en deuteranopía y de 22,3 en
   visión normal, muy por encima del umbral de 8. El color distingue la ENTIDAD (COP
   contra UVR, o el bloque) y el trazo distingue la FECHA (T-1 discontinuo, T continuo),
   así que la identidad nunca depende solo del color.
   Las cifras van en Arial, cuyos dígitos ya son de ancho uniforme,
   así que las columnas numéricas quedan alineadas sin fuente monoespaciada.
   Lo único que sigue en monoespaciada es el registro crudo de «la cinta»: ahí el
   ancho fijo no es estética, es lo que hace que los cortes de campo sean ciertos. */
:root{
  --fondo:#F2F5F8; --blanco:#FFF;
  --marca:#0B2E4F;        /* azul corporativo: cabecera y encabezados de tabla */
  --marca-media:#16456E; --tinte:#EDF3F8; --zebra:#F7FAFC;
  --regla:#D7DFE7; --regla-suave:#EAEFF4;
  --tinta:#0F2942; --tinta-media:#2C4863; --tenue:#61798F; --apagado:#9FB3C4;
  --acento:#0E8A4A;       /* verde corporativo: destacados y serie T */
  --azul:#1A5FA8;         /* la otra serie; validado contra el verde para daltonismo */
  --alza:#C0392B; --baja:#0E7C42; --alerta:#B0710A;
  --ok-fondo:#E6F4EC; --ok-borde:#A8D5BC;
  --mal-fondo:#FBEAE8; --mal-borde:#EDB6AF;
  --av-fondo:#FDF4E4; --av-borde:#E4C894;
  --top-h:96px;        /* se remide en tiempo de ejecucion: ver ajustarAlto() */
  --sans:Arial,"Helvetica Neue",Helvetica,sans-serif;
  --mono:Consolas,"SF Mono",Menlo,"DejaVu Sans Mono",monospace;
  --sombra:0 1px 3px rgba(11,41,66,.07),0 1px 2px rgba(11,41,66,.04);
  --sombra-alta:0 4px 14px rgba(11,41,66,.10),0 1px 3px rgba(11,41,66,.06);
  --radio:10px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:var(--top-h)}
body{margin:0;background:var(--fondo);color:var(--tinta);font-family:var(--sans);
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1560px;margin:0 auto;padding:0 28px 96px}

/* --- barra superior --- */
.top{position:sticky;top:0;z-index:50;color:#FFF;
  background:linear-gradient(100deg,#08233D 0%,var(--marca) 45%,#17517F 100%);
  box-shadow:0 2px 10px rgba(11,41,66,.18)}
.top-in{max-width:1560px;margin:0 auto;padding:15px 28px 0;display:flex;
  flex-direction:column;align-items:center;gap:11px}
.top h1{font-size:15px;font-weight:700;letter-spacing:.24em;text-transform:uppercase;
  margin:0;text-align:center;color:#FFF}
/* el filete verde es la firma de la marca: separa cabecera de contenido */
.top h1::after{content:"";display:block;width:46px;height:3px;border-radius:2px;
  background:var(--acento);margin:9px auto 0}

.tabs{display:flex;gap:2px;justify-content:center;flex-wrap:wrap}
.tab{appearance:none;background:transparent;border:0;border-bottom:2px solid transparent;
  color:rgba(255,255,255,.72);font-family:inherit;font-size:12px;font-weight:400;
  letter-spacing:.1em;text-transform:uppercase;padding:7px 14px 6px;cursor:pointer;
  white-space:nowrap;transition:color .12s,border-color .12s}
.tab:hover{color:#FFF}
.tab:focus-visible{outline:2px solid var(--acento);outline-offset:2px;border-radius:2px}
.tab[aria-selected="true"]{color:#FFF;font-weight:700;border-bottom-color:var(--acento)}
.panel[hidden]{display:none}
.panel>section:first-child,.panel>div:first-child>section:first-child{margin-top:34px}

/* --- barra de parámetros --- */
.barra{background:var(--blanco);border-top:1px solid rgba(255,255,255,.14);
  border-bottom:1px solid var(--regla);box-shadow:var(--sombra)}
.barra-in{max-width:1560px;margin:0 auto;padding:9px 28px;display:flex;flex-wrap:wrap;
  gap:8px 22px;align-items:center;font-size:12px}
.barra label{display:inline-flex;align-items:center;gap:7px;color:var(--tinta-media);
  letter-spacing:.12em;text-transform:uppercase;font-size:10px;font-weight:700}
.barra select,.barra input{font-family:inherit;font-size:13px;font-weight:400;
  font-variant-numeric:tabular-nums;padding:4px 8px;background:var(--blanco);
  color:var(--tinta);border:1px solid var(--regla);border-radius:3px;letter-spacing:0}
.barra input{width:72px;text-align:right}
.barra select{min-width:116px}
.barra select:focus,.barra input:focus{outline:2px solid var(--acento);outline-offset:1px;
  border-color:var(--acento)}
.barra .u{color:var(--tinta-media);font-weight:400}
.barra .aviso{color:var(--alza);font-size:11px;font-weight:700;text-transform:none;letter-spacing:0}

/* --- estructura --- */
section{margin-top:52px}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;
  color:var(--acento);margin:0 0 8px}
h2{font-size:23px;font-weight:700;letter-spacing:-.015em;margin:0 0 6px;line-height:1.2}
h3{font-size:14px;font-weight:700;letter-spacing:.01em;margin:0}
.lede{max-width:78ch;color:var(--tinta-media);margin:10px 0 22px}
.card{background:var(--blanco);border:1px solid var(--regla);border-radius:var(--radio);
  margin-bottom:20px;overflow:hidden;box-shadow:var(--sombra);
  transition:box-shadow .15s}
.card:hover{box-shadow:var(--sombra-alta)}
.card-hd{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:13px 18px;
  border-bottom:1px solid var(--regla-suave);background:var(--tinte)}
/* Un punto de color antes del titulo, como los distintivos de la referencia: da
   un ancla visual a cada tarjeta sin gastar un icono. */
.card-hd h3::before{content:"";display:inline-block;width:8px;height:8px;
  border-radius:50%;background:var(--acento);margin-right:9px;vertical-align:middle}
.card-hd .meta{margin-left:auto;font-size:11px;color:var(--tenue);letter-spacing:.02em}
/* El boton de descarga va siempre al extremo derecho de la cabecera. Si la tarjeta
   trae `.meta`, esta ya empuja con margin-left:auto y el boton queda detras; si no,
   el propio boton empuja. */
.xls{margin-left:auto;appearance:none;background:var(--blanco);border:1px solid var(--regla);
  border-radius:3px;font-family:inherit;font-size:10px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:var(--tenue);padding:4px 10px;cursor:pointer;
  transition:background .12s,color .12s,border-color .12s}
.card-hd .meta ~ .xls{margin-left:0}
.xls:hover{background:var(--tinte);color:var(--tinta);border-color:var(--marca)}
.xls:focus-visible{outline:2px solid var(--acento);outline-offset:2px}
.xls[disabled]{opacity:.45;cursor:default}
.toggle{display:inline-flex;border:1px solid var(--regla);border-radius:3px;overflow:hidden}
.tg{appearance:none;background:var(--blanco);border:0;border-left:1px solid var(--regla);
  font-family:inherit;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--tenue);padding:4px 11px;cursor:pointer;transition:background .12s,color .12s}
.tg:first-child{border-left:0}
.tg:hover{color:var(--acento)}
.tg[aria-pressed="true"]{background:var(--marca);color:var(--tinta)}
.tg:focus-visible{outline:2px solid var(--acento);outline-offset:-2px}
.tg[disabled]{opacity:.4;cursor:default}
.tg[disabled]:hover{color:var(--tenue)}
td.sincurva{color:var(--alerta);font-size:10.5px;letter-spacing:.04em}
td.alvenc{color:var(--alerta)}
td.alvenc small{font-size:9px;letter-spacing:.04em;margin-left:5px}
td .extrap{color:var(--alerta);margin-left:4px;font-weight:700}
.controles{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:center;
  background:var(--tinte);border:1px solid var(--regla);border-radius:5px;
  padding:12px 18px;margin:0 0 22px}
.controles label{display:inline-flex;align-items:center;gap:8px;font-size:10px;
  font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--tinta-media)}
.controles input{font-family:inherit;font-size:13px;font-variant-numeric:tabular-nums;
  width:80px;padding:4px 8px;text-align:right;background:var(--blanco);color:var(--tinta);
  border:1px solid var(--regla);border-radius:3px;letter-spacing:0}
.controles input:focus{outline:2px solid var(--acento);outline-offset:1px;border-color:var(--acento)}
.controles .u{font-weight:400;color:var(--tenue);letter-spacing:0;text-transform:none}
.controles .pista{font-size:11px;font-weight:400;letter-spacing:0;text-transform:none;
  color:var(--tenue);max-width:52ch;line-height:1.45}

/* --- la cinta --- */
.cinta{overflow-x:auto}
.cinta-in{display:flex;font-family:var(--mono);font-size:12px;min-width:max-content;
  padding:6px 18px 16px}
.campo{border-left:1px solid var(--regla);padding:8px 0 0 7px;margin-right:2px}
.campo:first-child{border-left:none;padding-left:0}
.campo .pos{font-family:var(--sans);font-size:9px;color:var(--apagado);letter-spacing:.06em;display:block}
.campo .nom{font-family:var(--sans);font-size:9px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--acento);display:block;white-space:nowrap}
.campo .val{white-space:pre;display:block;padding-top:4px;color:var(--tinta)}
.campo.skip .val{color:var(--apagado)}
.campo.skip .nom{color:var(--apagado)}

/* --- embudo --- */
.embudos{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
.embudo{display:grid;gap:1px;background:var(--regla-suave)}
.embudo div{background:var(--blanco);padding:10px 18px;display:flex;gap:14px;align-items:baseline}
.embudo .et{flex:1}
.embudo .n{font-variant-numeric:tabular-nums;font-weight:700}
.embudo .barrita{height:7px;background:var(--marca-media);border-radius:4px;min-width:3px}
.embudo .total{background:var(--tinte);font-weight:700}

/* --- tarjetas de resumen --- */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(216px,1fr));gap:16px}
/* Ficha con distintivo redondo a la izquierda y el dato en grande, como en la
   referencia. El distintivo lleva el tono del estado, asi que el color no es lo
   unico que lo dice: el propio numero y su subtitulo ya lo cuentan. */
.tile{background:var(--blanco);border:1px solid var(--regla);border-radius:var(--radio);
  padding:15px 17px;box-shadow:var(--sombra);display:flex;gap:13px;align-items:flex-start;
  transition:box-shadow .15s}
.tile:hover{box-shadow:var(--sombra-alta)}
.tile .ico{flex:0 0 38px;height:38px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:17px;line-height:1;background:var(--tinte);margin-top:2px}
.tile.ok .ico{background:var(--ok-fondo)} .tile.mal .ico{background:var(--mal-fondo)}
.tile.av .ico{background:var(--av-fondo)}
.tile .txt{min-width:0}
.tile .k{font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--tenue);line-height:1.35}
.tile .v{font-size:25px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:4px;
  letter-spacing:-.02em;line-height:1.15;color:var(--marca)}
.tile .s{font-size:12px;color:var(--tenue);margin-top:2px}

/* --- píldoras --- */
.pill{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;
  letter-spacing:.05em;padding:3px 10px;border-radius:3px;border:1px solid;text-transform:uppercase}
.pill.ok{color:var(--baja);border-color:var(--ok-borde);background:var(--ok-fondo)}
.pill.mal{color:var(--alza);border-color:var(--mal-borde);background:var(--mal-fondo)}
.pill.av{color:var(--alerta);border-color:var(--av-borde);background:var(--av-fondo)}
.pill.n{color:var(--tenue);border-color:var(--regla);background:var(--tinte);font-weight:400}

/* --- tablas --- */
/* Fijar un eje del overflow convierte esto en un contexto de scroll, y contra ese
   contexto se mide el position:sticky del encabezado. Por eso el desplazamiento del
   encabezado va contra ESTE contenedor (top:0) y no contra la ventana: con
   top:var(--top-h) el encabezado quedaba empujado ~100px hacia dentro de la tabla,
   tapando una fila de datos de forma permanente. El max-height le da al contenedor
   un scroll vertical propio, que es lo que hace que el encabezado se quede a la
   vista en las tablas largas (la de tasa fija tiene 84 filas). */
.tw{overflow:auto;max-height:76vh}
table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}
/* Solo la fila de nombres de columna queda fija, y contra el contenedor .tw. La de
   agrupacion se declara static a proposito: si las dos fueran pegajosas al mismo
   top:0 se superpondrian entre si. */
thead th{background:var(--marca);text-align:right;
  padding:9px 11px;font-weight:700;font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:#FFF;border-bottom:1px solid var(--marca);white-space:nowrap}
thead th:not(.grupo){position:sticky;top:0;z-index:2}
thead th:first-child,tbody td:first-child{text-align:left}
/* La fila de agrupacion va un tono mas claro para que se lea como el nivel de
   arriba y no como otra fila de columnas. */
thead th.grupo{text-align:center;background:var(--marca-media);color:rgba(255,255,255,.92);
  border-bottom:1px solid rgba(255,255,255,.18);position:static;font-weight:400}
tbody td{padding:6px 11px;text-align:right;border-bottom:1px solid var(--regla-suave);
  white-space:nowrap}
tbody tr:nth-child(even) td{background:var(--zebra)}
tbody tr:hover td{background:var(--tinte)}
tbody tr.vacia td{color:var(--apagado)}
td.alza,.v.alza{color:var(--alza);font-weight:700}
td.baja,.v.baja{color:var(--baja);font-weight:700}
td.neutro,.v.neutro{color:var(--tenue)}
td.key{font-weight:700}
td.ventana{font-variant-numeric:tabular-nums;color:var(--tinta-media)}
.sep{border-left:1px solid var(--regla)}
.nota-tabla{margin:0;padding:11px 18px 13px;border-top:1px solid var(--regla-suave);
  background:var(--tinte);font-size:11.5px;color:var(--tinta-media);line-height:1.5}
.nota-tabla b{color:var(--alerta)}

/* --- calidad --- */
.issue{background:var(--blanco);border:1px solid var(--regla);border-left:4px solid var(--tenue);
  border-radius:4px;padding:13px 18px;margin-bottom:10px;box-shadow:var(--sombra)}
.issue.error{border-left-color:var(--alza)}
.issue.aviso{border-left-color:var(--alerta)}
.issue.info{border-left-color:var(--marca)}
.issue .hd{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
.issue .cod{font-family:var(--mono);font-size:11px;color:var(--tenue)}
.issue .cnt{font-weight:700;font-variant-numeric:tabular-nums;margin-left:auto}
.issue p{margin:7px 0 0;max-width:92ch;font-size:13px;color:var(--tinta-media)}
.issue .muestra{font-family:var(--mono);font-size:11px;color:var(--tenue);margin-top:7px}

/* --- gráficas --- */
.chart{width:100%;height:308px;padding:12px 6px 6px}
.chart svg{width:100%;height:100%;display:block;overflow:visible}
.chart .sin-datos{margin:0;padding:0 12px;font-size:11px;color:var(--tenue)}
.chart .grid{stroke:var(--regla-suave);stroke-width:1}
.chart .ax{stroke:var(--regla);stroke-width:1}
.chart text{font-family:var(--sans);font-size:10px;fill:var(--tenue)}
.chart .lbl{fill:var(--acento);letter-spacing:.12em;text-transform:uppercase;font-size:9px;
  font-weight:700}
.leyenda{display:flex;flex-wrap:wrap;gap:18px;padding:0 18px 14px;font-size:11px}
.leyenda span{display:inline-flex;align-items:center;gap:7px;color:var(--tinta-media)}
.leyenda i{width:20px;height:0;border-top-width:2px;border-top-style:solid;display:inline-block}
.tip{position:fixed;pointer-events:none;background:var(--tinta);color:var(--fondo);
  font-size:11px;font-variant-numeric:tabular-nums;padding:6px 9px;border-radius:4px;opacity:0;
  transition:opacity .12s;z-index:99;white-space:pre;box-shadow:0 2px 8px rgba(58,34,48,.22)}

/* --- pie --- */
footer{margin-top:64px;border-top:2px solid var(--marca-media);padding-top:22px;font-size:11px;
  color:var(--tenue)}
footer dl{display:grid;grid-template-columns:auto 1fr;gap:3px 18px;margin:0 0 16px;max-width:900px}
footer dt{color:var(--tinta-media);font-weight:700}
footer dd{margin:0;font-variant-numeric:tabular-nums}
details.raw{margin-top:14px}
details.raw summary{cursor:pointer;font-size:11px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--acento)}
details.raw summary:focus-visible{outline:2px solid var(--acento);outline-offset:2px}
noscript p{background:var(--av-fondo);border:1px solid var(--av-borde);border-radius:4px;
  padding:13px 18px;margin:26px 0 0;font-size:13px;color:var(--tinta)}

@media (max-width:980px){
  .tab{font-size:11px;padding:7px 9px 6px;letter-spacing:.05em}
  .top-in{gap:10px}
  thead th{position:static}
  .chart{height:246px}
  .wrap{padding:0 16px 72px}
}
@media print{
  body{background:#fff} .top,.barra{position:static} .tabs{display:none}
  .panel[hidden]{display:block}          /* al imprimir salen las dos pestañas */
  .xls{display:none}                     /* un boton impreso no sirve de nada */
  .tw{overflow:visible;max-height:none}  /* sin scroll, la tabla se pagina completa */
  section,.card{break-inside:avoid} thead th{position:static}
  .card,.tile,.issue{box-shadow:none}
  /* En pantalla la cabecera y los encabezados de tabla van en azul oscuro. Al
     imprimir eso son planchas de tinta, y muchas impresoras de oficina descartan
     los fondos: el texto blanco saldria sobre blanco. Se invierten a tinta sobre
     papel, conservando la regla que marca la division. */
  .top{background:#fff;color:var(--tinta);box-shadow:none;
       border-bottom:2px solid var(--marca)}
  .top h1{color:var(--tinta)}
  thead th{background:#fff;color:var(--tinta);border-bottom:1.5px solid var(--marca)}
  thead th.grupo{background:#fff;color:var(--tinta-media);
                 border-bottom:1px solid var(--regla)}
  .tile .ico{display:none}               /* el distintivo no aporta en papel */
  tbody tr:nth-child(even) td{background:#fff}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

# ----------------------------------------------------------------------------
# Capa de cálculo del navegador. Sin DOM, para poder verificarla contra Python.
# ----------------------------------------------------------------------------

JS_CALC = r"""
var SX = (function(){
'use strict';
var VACIO = '\u00b7';

// ---------- formato: coma decimal, punto de miles ----------
function fmt(v, dec){
  if(v === null || v === undefined || !isFinite(v)) return VACIO;
  var s = Math.abs(v).toFixed(dec).split('.');
  s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (v < 0 ? '-' : '') + s.join(',');
}
function pct(v, dec){
  return (v === null || v === undefined || !isFinite(v))
    ? VACIO : fmt(v * 100, dec === undefined ? 3 : dec) + ' %';
}
function bps(v, dec){
  if(v === null || v === undefined || !isFinite(v)) return VACIO;
  return (v > 0 ? '+' : '') + fmt(v, dec === undefined ? 1 : dec);
}
function clase(v){
  if(v === null || v === undefined || !isFinite(v)) return '';
  return Math.abs(v) < 0.05 ? 'neutro' : (v > 0 ? 'alza' : 'baja');
}

// El margen real es una funcion afin de la tasa, asi que aplicarla al promedio de
// las tasas de un nodo da lo mismo que promediar los margenes de sus titulos.
function margen(bruta, ipc, indexado){
  if(bruta === null || bruta === undefined) return null;
  return indexado ? (1 + bruta) / (1 + ipc) - 1 : bruta;
}

// ---------- nodos de un bloque para un par de fechas ----------
// Cada fecha ancla su propia rejilla en su fecha de valoracion, asi que el
// renglon i compara el mismo tramo de plazo y no el mismo mes de calendario.
var MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
           'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

function dia(iso){ var p = iso.split('-'); return p[2] + '/' + p[1]; }
function etiquetaMes(iso){
  var p = iso.split('-');
  return MES[parseInt(p[1], 10) - 1] + '-' + p[0].slice(2);
}
function diasEntre(a, b){
  return Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
}
// Base 30/360 US/NASD, igual que DAYS360 de Excel con metodo FALSO. Es la base en la
// que se mide el tiempo dentro del precio de un flotante IBR.
function dias360(a, b){
  var p = a.split('-'), q = b.split('-');
  var d1 = Math.min(+p[2], 30), d2 = +q[2];
  if(d2 === 31 && d1 === 30) d2 = 30;
  return (+q[0] - +p[0]) * 360 + (+q[1] - +p[1]) * 30 + (d2 - d1);
}

function nodos(D, rt, rt1, blockId, familia, ipcT, ipcT1){
  var clave = blockId + '|' + familia;
  var bloque = D.bloques.filter(function(b){ return b.id === blockId; })[0];
  var ix = bloque.indexado, minN = D.config.minTitulos;
  var a = rt.nodos[clave], p = rt1.nodos[clave];
  var anclaT = rt.anclas, anclaT1 = rt1.anclas;
  var out = [];
  for(var i = 0; i < bloque.meses; i++){
    var bt = a && a.bruta[i] !== undefined ? a.bruta[i] : null;
    var b1 = p && p.bruta[i] !== undefined ? p.bruta[i] : null;
    var mt = margen(bt, ipcT, ix);
    var m1 = margen(b1, ipcT1, ix);
    var nT = a ? a.n[i] : 0, n1 = p ? p.n[i] : 0;
    // El margen sobre IBR se calcula al procesar, con la curva del propio dia:
    // aqui solo se lee. Si falta la curva de una fecha, viene nulo.
    var gT = (a && a.margen) ? a.margen[i] : null;
    var g1 = (p && p.margen) ? p.margen[i] : null;
    if (gT === undefined) gT = null;
    if (g1 === undefined) g1 = null;
    out.push({
      i: i,
      rango: etiquetaMes(anclaT[i]),
      desdeT: anclaT[i], hastaT: anclaT[i + 1],
      desdeT1: anclaT1[i], hastaT1: anclaT1[i + 1],
      diasMesT: diasEntre(anclaT[i], anclaT[i + 1]),
      diaT: diasEntre(anclaT[0], anclaT[i]),
      diaT1: diasEntre(anclaT1[0], anclaT1[i]),
      // Plazo del nodo, en anios: el nodo vence al final de su ventana, la misma
      // convencion que ya usan el margen sobre IBR por el atajo de la bvc y las
      // rentabilidades esperadas. Cada fecha lo mide contra su propia rejilla.
      plazoT: diasEntre(anclaT[0], anclaT[i + 1]) / 365,
      plazoT1: diasEntre(anclaT1[0], anclaT1[i + 1]) / 365,
      durT: a ? a.dur[i] : null, durT1: p ? p.dur[i] : null,
      cuponT: a ? a.cupon[i] : null,
      // la tasa de valoracion tal como la envia el proveedor, sin convertir. En
      // los bloques indexados a IPC es la que acompania al margen real; el IPC de
      // pantalla no la mueve.
      brutaT: bt, brutaT1: b1,
      dBruta: (bt === null || b1 === null) ? null : (bt - b1) * 1e4,
      tasaT: mt, tasaT1: m1,
      dTasa: (mt === null || m1 === null) ? null : (mt - m1) * 1e4,
      margenT: gT, margenT1: g1,
      dMargen: (gT === null || g1 === null) ? null : (gT - g1) * 1e4,
      nT: nT, nT1: n1,
      fragil: (nT > 0 && nT < minN) || (n1 > 0 && n1 < minN)
    });
  }
  return out;
}

// ---------- TES: solo las referencias presentes en las dos fechas ----------
function tes(D, rt, rt1){
  var nominal = D.config.nominalDv01, idx = {}, out = [];
  rt1.tes.isin.forEach(function(isin, i){ idx[isin] = i; });
  rt.tes.isin.forEach(function(isin, i){
    var j = idx[isin];
    if(j === undefined) return;
    var c = D.catalogo[isin] || {};
    var tT = rt.tes.bruta[i], t1 = rt1.tes.bruta[j];
    var dm = rt.tes.dm[i], precio = rt.tes.precio[i];
    out.push({
      isin: isin, nemotecnico: c.nemotecnico, grupo: c.grupo, moneda: c.moneda,
      emision: c.emision, vencimiento: c.vencimiento, cupon: c.cupon,
      dias: rt.tes.dias[i], anios: rt.tes.dias[i] / 365,
      // el plazo se acorta entre las dos fechas: cada serie usa el suyo
      aniosT1: rt1.tes.dias[j] === null ? null : rt1.tes.dias[j] / 365,
      durT: rt.tes.dur[i], durT1: rt1.tes.dur[j], dm: dm,
      precioT: precio, precioT1: rt1.tes.precio[j],
      tasaT: tT, tasaT1: t1,
      dTasa: (tT === null || t1 === null) ? null : (tT - t1) * 1e4,
      dv01: (dm === null || precio === null) ? null
            : -(dm * precio) * 1e-4 * nominal * 0.01
    });
  });
  out.sort(function(a, b){
    return a.grupo === b.grupo ? a.dias - b.dias : (a.grupo < b.grupo ? -1 : 1);
  });
  return out;
}

// ---------- rentabilidad esperada de un CDT sintetico por rango ----------
// Espejo de hpr.py. Cada ventana es un CDT independiente que vence al final de la
// ventana; no se promedia ni se interpola entre rangos.

function menosMeses(iso, meses){
  var p = iso.split('-').map(Number);
  var total = p[0] * 12 + (p[1] - 1) - meses;
  var anio = Math.floor(total / 12), mes = total - anio * 12;
  var ultimo = new Date(Date.UTC(anio, mes + 1, 0)).getUTCDate();
  var dia = Math.min(p[2], ultimo);
  var dd = function(x){ return (x < 10 ? '0' : '') + x; };
  return anio + '-' + dd(mes + 1) + '-' + dd(dia);
}

function calendarioCupones(vencimiento, fechaVal, pagos){
  var paso = 12 / pagos, fechas = [], k = 0;
  for(;;){
    var f = menosMeses(vencimiento, paso * k);
    if(f <= fechaVal) break;
    fechas.push(f); k++;
  }
  return fechas.reverse();
}

// Ultimo valor publicado con fecha <= la pedida, sin interpolar.
function vigente(senda, iso, escenario){
  var serie = senda.valores[escenario], i = -1;
  for(var j = 0; j < senda.fechas.length; j++){
    if(senda.fechas[j] <= iso) i = j; else break;
  }
  if(i < 0) return [serie[0], true];
  return [serie[i], iso > senda.fechas[senda.fechas.length - 1]];
}

function cuponPeriodo(tipo, facial, indice, pagos){
  if(tipo === 'fs') return facial / pagos;
  if(tipo === 'ipc') return Math.pow((1 + indice) * (1 + facial), 1 / pagos) - 1;
  return (indice + facial) / pagos;
}

// Con que fecha se lee el indice del cupon que se paga en `fechaCupon`: el del inicio
// del periodo, un paso antes del pago, en IPC y en IBR. Es la convencion del atajo de
// la bvc. En IPC rige solo la tasa cupon; en IBR rige tambien el descuento de V1, que
// usa para cada periodo el mismo indice que fijo su cupon.
function fechaDelIndice(fechaCupon, paso){
  return menosMeses(fechaCupon, paso);
}

// Tasa efectiva anual unica con la que se descuenta. Solo en tasa fija y en IPC: IBR
// no tiene una, porque su V0 usa la «Tasa (T)» tal cual y su V1 descuenta periodo a
// periodo (ver vpresPrevia).
function tasaDescuento(tipo, tir, margen, indice){
  if(tipo === 'fs') return tir;
  if(tipo === 'ipc') return (1 + margen) * (1 + indice) - 1;
  throw new Error('tasaDescuento no aplica a ' + tipo + ': no tiene una tasa unica');
}

function xirr(flujos){
  var r = 0.10;
  for(var it = 0; it < 300; it++){
    var f = 0, df = 0;
    for(var i = 0; i < flujos.length; i++){
      var t = flujos[i][0] / 365, c = flujos[i][1];
      f += c * Math.pow(1 + r, -t);
      df += -c * t * Math.pow(1 + r, -t - 1);
    }
    if(Math.abs(df) < 1e-14) return null;
    var nuevo = r - f / df;
    if(nuevo <= -0.999) nuevo = (r - 0.999) / 2;
    if(Math.abs(nuevo - r) < 1e-11) return nuevo;
    r = nuevo;
  }
  return null;
}

// Devuelve un resultado por horizonte pedido, mas el vencimiento.
function rentabilidad(D, opciones){
  var tipo = opciones.tipo, T = opciones.fechaVal, venc = opciones.vencimiento;
  var pagos = D.hpr.pagos[tipo];
  var fechas = calendarioCupones(venc, T, pagos);
  var diasVenc = diasEntre(T, venc);
  if(!fechas.length || diasVenc <= 1) return null;

  var senda = (tipo === 'fs' || !D.escenarios) ? null
              : D.escenarios.sendas[D.hpr.indice[tipo]];
  if(tipo !== 'fs' && !senda) return null;
  // el indice con el que se recompone la tasa de entrada tiene que ser el mismo con
  // el que se despejo el margen; si no, los dos dejan de cancelarse y V0 ya no
  // descuenta a la TIR del nodo
  var indiceHoy = (opciones.indiceEntrada === undefined || opciones.indiceEntrada === null)
    ? (senda ? vigente(senda, T, opciones.escenario)[0] : 0)
    : opciones.indiceEntrada;

  var extrap = false;
  var paso = 12 / pagos;
  // Los cupones se proyectan con la senda del escenario, tambien mas alla de la
  // valoracion: el precio de entrada incorpora la expectativa. Lo que cae en o antes
  // de la valoracion sale de la senda diaria publicada —la misma contra la que se
  // calcula el margen— y solo se cae a la de proyeccion si ese dia le falta.
  var publicado = opciones.historico || {};
  var curva = opciones.curva || {};
  // `pegado` y `conCurva` arman los flujos del precio de entrada con la convencion de
  // los proveedores de precios: lo posterior a la valoracion no se busca en la senda,
  // sino que toma el indice de hoy —en IPC— o se lee en la curva forward IND_IBR del
  // dia habil anterior —en IBR—. Lo anterior sigue siendo el dato que se le fijo.
  var construir = function(pegado, conCurva){
    return fechas.map(function(f){
      var idx = 0;
      if(senda){
        var ini = fechaDelIndice(f, paso);
        var dato = (ini <= T) ? publicado[ini] : undefined;
        if(dato !== undefined && dato !== null){
          idx = dato;
        } else if(pegado !== null && ini > T){
          idx = pegado;
        } else if(conCurva && ini > T && curva[ini] !== undefined && curva[ini] !== null){
          idx = curva[ini];
        } else {
          var v = vigente(senda, ini, opciones.escenario);
          idx = v[0]; extrap = extrap || v[1];
        }
      }
      var c = cuponPeriodo(tipo, opciones.cupon, idx, pagos);
      // el indice viaja con el flujo: en IBR es tambien el que descuenta ese periodo
      return [f, c + (f === venc ? 1 : 0), idx];
    });
  };
  var conEscenario = construir(null, false);

  var vpres = function(lista, desde, tasa){
    var s = 0;
    for(var i = 0; i < lista.length; i++){
      s += lista[i][1] * Math.pow(1 + tasa, -diasEntre(desde, lista[i][0]) / 365);
    }
    return s;
  };
  // Precio de un flotante IBR, periodo a periodo y en base 30/360. Cada periodo se
  // descuenta con el indice que fijo su propio cupon mas el margen —nominal mes
  // vencido, dividido entre `pagos`— y del primero solo la fraccion que falta.
  var vpresPrevia = function(lista, desde, margen){
    var acum = 1, total = 0, lPrev = 0, porPeriodo = 360 / pagos;
    for(var i = 0; i < lista.length; i++){
      var l = dias360(desde, lista[i][0]);
      acum *= Math.pow(1 + (lista[i][2] + margen) / pagos, -(l - lPrev) / porPeriodo);
      total += acum * lista[i][1];
      lPrev = l;
    }
    return total;
  };

  // el precio de entrada: convencion del proveedor, distinta en cada indice
  var flujosV0, tasaEnt;
  if(tipo === 'ipc'){
    flujosV0 = construir(indiceHoy, false);
    tasaEnt = tasaDescuento(tipo, opciones.tir, opciones.margen, indiceHoy);
  } else if(tipo === 'ibr'){
    flujosV0 = construir(null, true);
    tasaEnt = opciones.tir;            // la «Tasa (T)» del rango, ya efectiva anual
  } else {
    flujosV0 = conEscenario;
    tasaEnt = tasaDescuento(tipo, opciones.tir, opciones.margen, indiceHoy);
  }
  var V0 = 100 * vpres(flujosV0, T, tasaEnt);
  var delta = opciones.deltaPb / 10000;

  // los horizontes fijos, y al final el vencimiento. En esa ultima fila se usa
  // `diasVenc − 1` por definicion, no por quedarse corto el plazo: ahi la marca
  // «al vencimiento» no aplica.
  var pedidos = D.hpr.horizontes.map(function(h){ return [h, false]; });
  pedidos.push([diasVenc, true]);
  return pedidos.map(function(par){
    var pedido = par[0], esVenc = par[1];
    var h = Math.min(pedido, diasVenc - 1);
    var salida = sumarDias(T, h);
    var vs = senda ? vigente(senda, salida, opciones.escenario) : [0, false];
    // Un cupon que cae justo en la fecha de salida se cobra —entra en el XIRR en el
    // dia h— y no forma parte de V1.
    var cupones = conEscenario.filter(function(x){ return x[0] > T && x[0] <= salida; });
    var resto = conEscenario.filter(function(x){ return x[0] > salida; });
    var tasaSal, V1;
    if(tipo === 'ibr'){
      // V1 periodo a periodo con la senda del escenario haciendo de curva forward.
      // No queda una sola tasa de salida que reportar: hay una por periodo.
      tasaSal = null;
      V1 = 100 * vpresPrevia(resto, salida, opciones.margen + delta);
    } else {
      tasaSal = tasaDescuento(tipo, opciones.tir + delta, opciones.margen + delta, vs[0]);
      V1 = 100 * vpres(resto, salida, tasaSal);
    }

    var cf = [[0, -V0]];
    cupones.forEach(function(x){ cf.push([diasEntre(T, x[0]), 100 * x[1]]); });
    cf.push([h, V1]);

    return { horizonte: pedido, dias: h, hpr: xirr(cf), v0: V0, v1: V1,
             tasaEntrada: tasaEnt, tasaSalida: tasaSal, cupones: cupones.length,
             alVencimiento: !esVenc && h < pedido, extrapolado: extrap || vs[1] };
  });
}

function sumarDias(iso, n){
  return new Date(Date.parse(iso) + n * 86400000).toISOString().slice(0, 10);
}

// Resumen del tamano de muestra de un bloque, para la nota al pie de su tabla.
// Devuelve las dos listas: los nodos de muestra corta y los que si la alcanzan. La
// nota enumera la mas corta de las dos, porque en algunos bloques casi todos los
// nodos son de un solo titulo y listar veintitres rangos no informa nada.
function muestraCorta(filas, minTitulos){
  var conDato = filas.filter(function(r){ return r.nT > 0 || r.nT1 > 0; });
  var nombres = function(xs){ return xs.map(function(r){ return r.rango; }); };
  return {
    total: conDato.length,
    minimo: minTitulos,
    rangos: nombres(conDato.filter(function(r){ return r.fragil; })),
    rangosOk: nombres(conDato.filter(function(r){ return !r.fragil; }))
  };
}

return { VACIO: VACIO, fmt: fmt, pct: pct, bps: bps, clase: clase, margen: margen,
         nodos: nodos, tes: tes, muestraCorta: muestraCorta,
         etiquetaMes: etiquetaMes, dia: dia, diasEntre: diasEntre,
         sumarDias: sumarDias, menosMeses: menosMeses,
         calendarioCupones: calendarioCupones, vigente: vigente,
         cuponPeriodo: cuponPeriodo, fechaDelIndice: fechaDelIndice,
         tasaDescuento: tasaDescuento, xirr: xirr,
         rentabilidad: rentabilidad };
})();
if(typeof module !== 'undefined' && module.exports) module.exports = SX;
"""

# ----------------------------------------------------------------------------
# Aplicación de cliente
# ----------------------------------------------------------------------------

JS = r"""
(function(){
'use strict';
var D = JSON.parse(document.getElementById('sx-datos').textContent), CFG = D.config;
var fmt = SX.fmt, pct = SX.pct, bps = SX.bps, clase = SX.clase;
var $ = function(id){ return document.getElementById(id); };
var tip = document.createElement('div'); tip.className = 'tip'; document.body.appendChild(tip);
function esc(s){ var d = document.createElement('div'); d.textContent = (s === null || s === undefined) ? '' : s; return d.innerHTML; }

var S = { t: null, t1: null, ipcT: 0, ipcT1: 0, br: 0 };
var ultimoValido = { t: null, t1: null };
function rt(){ return D.porFecha[S.t]; }
function rt1(){ return D.porFecha[S.t1]; }
function nodos(id, fam){ return SX.nodos(D, rt(), rt1(), id, fam, S.ipcT, S.ipcT1); }
function ipcDe(f){
  var v = D.ipcPorFecha[f];
  return (v === undefined || v === null) ? D.params.ipc_referencia : v;
}

// ---------- selectores y atajos ----------
function llenarSelect(sel, seleccion){
  sel.innerHTML = '';
  for(var i = D.fechas.length - 1; i >= 0; i--){
    var o = document.createElement('option');
    o.value = D.fechas[i]; o.textContent = D.fechas[i];
    if(D.fechas[i] === seleccion) o.selected = true;
    sel.appendChild(o);
  }
}
// ---------- secciones ----------
// Iconos de trazo, dibujados a mano en SVG: el reporte tiene que abrir desde el
// disco y sin red, asi que no hay tipografia de iconos que cargar.
var ICONOS = {
  calendario: 'M3 5h14v12H3zM3 9h14M7 3v4M13 3v4',
  capas:      'M10 3l7 4-7 4-7-4zM3 11l7 4 7-4M3 14.5l7 4 7-4',
  flecha:     'M3 14l4-5 3 3 6-7M13 5h4v4',
  onda:       'M3 15l4-6 3 3 3-7 4 10',
  escudo:     'M10 3l6 2v5c0 4-3 6-6 7-3-1-6-3-6-7V5zM7 10l2 2 4-4',
  alerta:     'M10 3l7 13H3zM10 8v4M10 14.5v.01'
};
function icono(nombre){
  return '<svg viewBox="0 0 20 20" width="19" height="19" fill="none" ' +
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true"><path d="' + ICONOS[nombre] + '"/></svg>';
}
function tile(k, v, s, cls, ico, tono){
  return '<div class="tile' + (tono ? ' ' + tono : '') + '">' +
         '<div class="ico">' + (ico ? icono(ico) : '') + '</div><div class="txt">' +
         '<div class="k">' + esc(k) + '</div><div class="v' +
         (cls ? ' ' + cls : '') + '">' + v + '</div>' +
         '<div class="s">' + esc(s) + '</div></div></div>';
}
function promedio(xs){
  return xs.length ? xs.reduce(function(a, b){ return a + b; }, 0) / xs.length : null;
}
function renderResumen(){
  var movs = nodos('fs', 'CDT').filter(function(r){ return r.dTasa !== null; })
                               .map(function(r){ return Math.abs(r.dTasa); });
  var cop = SX.tes(D, rt(), rt1()).filter(function(r){ return r.grupo === 'COP' && r.dTasa !== null; });
  var medioTes = promedio(cop.map(function(r){ return r.dTasa; }));
  var fallidos = [].concat(rt().checks, rt1().checks).filter(function(c){ return !c.ok; }).length;
  var issues = mezclarIssues();
  var cuenta = function(sev){ return issues.filter(function(i){ return i.sev === sev; }).length; };
  var dias = Math.round((new Date(S.t) - new Date(S.t1)) / 86400000);
  $('resumen-tiles').innerHTML =
    tile('Ventana comparada', esc(S.t1) + ' &rarr; ' + esc(S.t), dias + ' días calendario',
         '', 'calendario') +
    tile('Universo valorado en T', fmt(rt().n_universo, 0),
         'de ' + fmt(rt().n_registros, 0) + ' registros', '', 'capas') +
    tile('Movimiento medio CDT tasa fija', fmt(promedio(movs), 1),
         'pb absolutos entre las dos fechas', '', 'flecha') +
    tile('Movimiento medio TES COP', bps(medioTes),
         'pb · ' + fmt(cop.length, 0) + ' referencias', clase(medioTes), 'onda') +
    tile('Integridad', fallidos ? fmt(fallidos, 0) : 'OK',
         fallidos ? 'controles fallidos' : 'los controles del proveedor cuadran',
         '', 'escudo', fallidos ? 'mal' : 'ok') +
    tile('Calidad de datos', cuenta('error') + ' / ' + cuenta('aviso'), 'errores / avisos',
         '', 'alerta', cuenta('error') ? 'mal' : (cuenta('aviso') ? 'av' : 'ok'));
}

function renderCinta(){
  var reg = rt().cinta || '', html = '';
  D.layout.forEach(function(f){
    var val = reg.length >= f.fin ? reg.slice(f.ini, f.fin) : '';
    html += '<div class="campo' + (f.skip ? ' skip' : '') + '" title="' + esc(f.desc) + '">' +
            '<span class="pos">' + f.ini + '</span>' +
            '<span class="nom">' + esc(f.skip ? '—' : f.nombre) + '</span>' +
            '<span class="val">' + esc(val) + '</span></div>';
  });
  $('cinta-hd').innerHTML = '<h3>' + esc(rt().archivo) + '</h3>' +
    '<span class="pill n">registro 1 de ' + fmt(rt().n_registros, 0) + '</span>' +
    '<span class="meta">fecha ' + esc(rt().fecha) + '</span>';
  $('cinta-in').innerHTML = html;
  $('checks').innerHTML = pills(rt1(), 'T-1') + pills(rt(), 'T');
}
function pills(r, etiqueta){
  return r.checks.map(function(c){
    return '<span class="pill ' + (c.ok ? 'ok' : 'mal') + '">' + esc(etiqueta) + ' · ' +
           esc(c.nombre) + (c.ok ? '' : ' · ' + esc(c.detalle)) + '</span>';
  }).join('');
}

function embudo(r){
  var html = '<div class="total"><span class="et">Registros en el archivo</span>' +
             '<span class="n">' + fmt(r.n_registros, 0) + '</span></div>';
  r.exclusiones.forEach(function(x){
    var w = r.n_registros ? Math.max(2, Math.round(x.filas / r.n_registros * 240)) : 0;
    html += '<div><span class="et">− ' + esc(D.etiquetas[x.id] || x.id) + '</span>' +
            '<span class="barrita" style="width:' + w + 'px"></span>' +
            '<span class="n">' + fmt(x.filas, 0) + '</span></div>';
  });
  html += '<div class="total"><span class="et">Universo de valoración</span>' +
          '<span class="n">' + fmt(r.n_universo, 0) + '</span></div>';
  return '<div class="card"><div class="card-hd"><h3>' + esc(r.fecha) + '</h3></div>' +
         '<div class="embudo">' + html + '</div></div>';
}

function idChart(id, fam){ return 'ch-' + id + '-' + fam.replace(/\s+/g, '_'); }

// Serie que muestra cada gráfica: 'tir' o 'margen'. La ofrecen los dos bloques que
// tienen las dos medidas —IPC, con su margen real, e IBR, con el del atajo—; el de
// tasa fija no, porque ahí la tasa es lo único que hay. Cada uno abre en la suya:
// IPC en el margen real, que es su medida comparable, e IBR en la tasa.
var serieDe = {};
function serieGrafica(id, porDefecto){ return serieDe[id] || porDefecto || 'tir'; }
function serieDeBloque(b){ return b.indexado ? 'margen' : 'tir'; }
// El conmutador nunca se esconde: si la fecha no tiene margen queda a la vista pero
// deshabilitado, con el motivo en el titulo. Ocultarlo hacia que el boton
// desapareciera sin explicacion cuando faltaba la curva del dia hábil anterior.
function conmutador(id, hayMargen, motivo, porDefecto, textoTasa){
  var v = hayMargen ? serieGrafica(id, porDefecto) : 'tir';
  var boton = function(clave, texto){
    var apagado = !hayMargen && clave === 'margen';
    return '<button type="button" class="tg" data-gr="' + id + '" data-serie="' + clave +
      '" aria-pressed="' + (v === clave) + '"' + (apagado ? ' disabled' : '') +
      (apagado ? ' title="' + esc(motivo) + '"' : '') + '>' + texto + '</button>';
  };
  return '<span class="toggle" role="group" aria-label="Serie de la gráfica">' +
         boton('tir', textoTasa) + boton('margen', 'Margen') + '</span>';
}
function cablearConmutadores(){
  [].forEach.call(document.querySelectorAll('.tg'), function(b){
    b.onclick = function(){
      serieDe[b.dataset.gr] = b.dataset.serie;
      [].forEach.call(b.parentNode.children, function(o){
        o.setAttribute('aria-pressed', String(o === b));
      });
      dibujarUnBloque(b.dataset.gr);
    };
  });
}

function renderBloques(){
  var html = '';
  D.bloques.forEach(function(b){
    var nota = b.nota ? '<p class="lede">' + esc(b.nota) + '</p>' : '';
    var filtro = 'indicador ' + b.indicador +
                 (b.periodicidad ? ' · periodicidad ' + b.periodicidad : '') +
                 (b.moneda ? ' · moneda ' + b.moneda : ' · todas las monedas');
    var cuerpo = '';
    b.familias.forEach(function(fam){
      var filas = nodos(b.id, fam);
      var conDato = filas.filter(function(r){ return r.nT > 0; }).length;
      var gid = idChart(b.id, fam);
      var conmuta = b.margenAtajo || b.indexado;
      var hayMargen = b.indexado
        ? filas.some(function(r){ return r.tasaT !== null; })
        : (b.margenAtajo && filas.some(function(r){ return r.margenT !== null; }));
      var motivoMargen = 'Sin margen para ' + S.t + ': ' +
        ((rt().ibr || {}).motivo || 'no hay nodos con margen en esta fecha');
      cuerpo += '<div class="card"><div class="card-hd"><h3>' + esc(fam) + '</h3>' +
        '<span class="pill n">' + esc(filtro) + '</span>' +
        (conmuta ? conmutador(gid, hayMargen, motivoMargen, serieDeBloque(b),
                              b.indexado ? 'Tasa' : 'TIR') : '') +
        '<span class="meta">' + conDato + ' nodos con dato</span>' +
        botonXls(b.label + ' ' + fam) + '</div>' +
        '<div class="chart" id="' + gid + '"></div>' + leyenda() +
        tablaBloque(filas, b) + '</div>';
    });
    html += '<section id="idx-' + b.id + '"><p class="eyebrow">Curvas por rango de plazo</p>' +
            '<h2>' + esc(b.label) + '</h2>' + nota + cuerpo + '</section>';
  });
  $('bloques').innerHTML = html;
  cablearConmutadores();
}

function tablaBloque(filas, bloque){
  var indexado = bloque.indexado, conMargen = bloque.margenAtajo;
  var grupos = '<tr><th class="grupo" colspan="2">Ventana de vencimientos</th>' +
    '<th class="grupo" colspan="3">Rejilla (días)</th>' +
    '<th class="grupo" colspan="2">Duración (años)</th><th class="grupo">Cupón</th>' +
    // en los indexados a IPC la tasa del proveedor va aparte del margen real, como
    // en el bloque de IBR: son dos medidas distintas del mismo nodo
    (indexado ? '<th class="grupo" colspan="3">Tasa</th>' : '') +
    '<th class="grupo" colspan="3">' + (indexado ? 'Margen real' : 'Tasa') + '</th>' +
    (conMargen ? '<th class="grupo" colspan="3">Margen sobre IBR (atajo bvc)</th>' : '') +
    '<th class="grupo" colspan="2">Muestra</th></tr>';
  var cols = ['Fechas (T)', 'Rango', 'Δ D T', 'Día T-1', 'Día T', 'T-1', 'T', 'T']
    .concat(indexado ? ['T-1', 'T', 'Δ pb'] : [])
    .concat(['T-1', 'T', 'Δ pb'])
    .concat(conMargen ? ['T-1', 'T', 'Δ pb'] : [])
    .concat(['n T-1', 'n T']);
  var cab = '<tr>' + cols.map(function(c){ return '<th>' + esc(c) + '</th>'; }).join('') + '</tr>';

  // Sin curva del propio día no hay margen, y el campo lo dice en vez de quedar
  // vacío. Si la ventana no tiene títulos, el margen falta por otra razón y ahí
  // va el punto medio, como en el resto de la fila.
  var faltaCurva = { t1: !!(rt1().ibr || {}).motivo, t: !!(rt().ibr || {}).motivo };
  var celdaMargen = function(v, fecha, sep, hayTitulos){
    var c = sep ? 'sep' : '';
    if(v !== null) return '<td class="' + c + '">' + pct(v, 2) + '</td>';
    if(faltaCurva[fecha]) return '<td class="' + c + ' sincurva">sin curva</td>';
    // La ventana tiene títulos y hay curva, así que lo que faltó fue el IBR del día
    // en que se fijó la tasa de algún período: un festivo o un fin de semana. Se
    // busca la fecha exacta y no se sustituye por la de otro día.
    if(hayTitulos) return '<td class="' + c + ' sincurva" title="No hay IBR ' +
      'publicado en el día en que se fijó la tasa de algún período de este ' +
      'rango.">sin dato</td>';
    return '<td class="' + c + ' neutro">' + SX.VACIO + '</td>';
  };

  var cuerpo = filas.map(function(r){
    var vacia = r.nT === 0 && r.nT1 === 0;
    var ventana = SX.dia(r.desdeT) + ' a ' + SX.dia(diaAntes(r.hastaT));
    var fila = '<tr' + (vacia ? ' class="vacia"' : '') + '>' +
      '<td class="key ventana" title="' + esc(r.desdeT + ' a ' + diaAntes(r.hastaT)) +
        '">' + esc(ventana) + '</td>' +
      '<td class="key">' + esc(r.rango) + '</td>' +
      '<td class="sep neutro">' + fmt(r.diasMesT, 0) + '</td>' +
      '<td>' + fmt(r.diaT1, 0) + '</td><td>' + fmt(r.diaT, 0) + '</td>' +
      '<td class="sep">' + fmt(r.durT1, 3) + '</td><td>' + fmt(r.durT, 3) + '</td>' +
      '<td class="sep">' + fmt(r.cuponT, 3) + ' %</td>' +
      (indexado
        ? '<td class="sep">' + pct(r.brutaT1) + '</td><td>' + pct(r.brutaT) + '</td>' +
          '<td class="' + clase(r.dBruta) + '">' + bps(r.dBruta) + '</td>'
        : '') +
      '<td class="sep">' + pct(r.tasaT1) + '</td><td>' + pct(r.tasaT) + '</td>' +
      '<td class="' + clase(r.dTasa) + '">' + bps(r.dTasa) + '</td>';
    if(conMargen){
      fila += celdaMargen(r.margenT1, 't1', true, r.nT1 > 0) +
        celdaMargen(r.margenT, 't', false, r.nT > 0) +
        (r.dMargen === null ? '<td class="neutro">' + SX.VACIO + '</td>'
                            : '<td class="' + clase(r.dMargen) + '">' + bps(r.dMargen) + '</td>');
    }
    return fila + '<td class="sep neutro">' + fmt(r.nT1, 0) + '</td>' +
      '<td class="neutro">' + fmt(r.nT, 0) + '</td></tr>';
  }).join('');

  return '<div class="tw"><table><thead>' + grupos + cab + '</thead><tbody>' + cuerpo +
         '</tbody></table></div>' + notaMuestra(filas) + notaVentana(filas) +
         notaCurva(bloque);
}

function diaAntes(iso){
  var d = new Date(Date.parse(iso) - 86400000);
  return d.toISOString().slice(0, 10);
}

// La ventana que se muestra es la de T. La de T-1 arranca en su propia fecha de
// valoración, así que puede caer en otros días aunque cubra el mismo tramo de plazo.
function notaVentana(filas){
  if(!filas.length) return '';
  var a = filas[0];
  if(a.desdeT === a.desdeT1) return '';
  return '<p class="nota-tabla">La columna de fechas es la ventana de T. Cada fecha ' +
    'ancla su rejilla en su propio día, así que la primera ventana de T-1 va del ' +
    esc(SX.dia(a.desdeT1)) + ' al ' + esc(SX.dia(diaAntes(a.hastaT1))) + '. Los ' +
    'renglones comparan el mismo tramo de plazo, no el mismo mes de calendario.</p>';
}

// Explica, cuando falta, por qué no hay margen para alguna de las dos fechas.
function notaCurva(bloque){
  if(!bloque.margenAtajo) return '';
  var faltan = [];
  [[S.t1, rt1()], [S.t, rt()]].forEach(function(par){
    var motivo = (par[1].ibr || {}).motivo;
    if(motivo) faltan.push(par[0] + ' (' + motivo + ')');
  });
  var usadas = [[S.t1, rt1()], [S.t, rt()]]
    .filter(function(p){ return (p[1].ibr || {}).curva_usada; })
    .map(function(p){ return p[0] + ' con la curva del ' + p[1].ibr.curva_usada; });

  if(!faltan.length){
    return usadas.length
      ? '<p class="nota-tabla">Margen calculado con la curva del día hábil anterior a ' +
        'cada fecha: ' + esc(usadas.join(' · ')) + '.</p>'
      : '';
  }
  return '<p class="nota-tabla"><b>Sin margen para ' + faltan.length +
    ' de las 2 fechas</b>: ' + esc(faltan.join(' · ')) + '. El margen de una fecha se ' +
    'calcula con la curva IND_IBR del día hábil anterior, y no se reemplaza por la de ' +
    'otro día.' + (usadas.length ? ' ' + esc(usadas.join(' · ')) + '.' : '') + '</p>';
}

// Los nodos con muestra corta se anotan al pie de la tabla en vez de marcarse fila
// por fila, para no cargar la columna de rango.
function notaMuestra(filas){
  var m = SX.muestraCorta(filas, CFG.minTitulos);
  var lista = function(xs){ return xs.map(esc).join(' · '); };
  var TOPE = 7;                         // mas alla de esto la enumeracion no informa

  if(!m.total){
    return '<p class="nota-tabla">Ningún bucket de plazo tiene títulos que cumplan los ' +
           'filtros de este bloque en las dos fechas.</p>';
  }
  if(!m.rangos.length){
    return '<p class="nota-tabla">Los ' + m.total + ' nodos con dato se construyeron con ' +
           m.minimo + ' títulos o más en las dos fechas.</p>';
  }

  var cabeza = '<b>Muestra corta en ' + m.rangos.length + ' de los ' + m.total +
    ' nodos con dato</b>, con menos de ' + m.minimo + ' títulos en alguna de las dos ' +
    'fechas: ahí la tasa es la de uno o dos papeles, no un promedio de mercado. ';
  var detalle;
  if(m.rangos.length <= TOPE){
    detalle = 'Son: ' + lista(m.rangos) + '.';
  } else if(m.rangosOk.length && m.rangosOk.length <= TOPE){
    detalle = 'Solo alcanzan los ' + m.minimo + ' títulos: ' + lista(m.rangosOk) + '.';
  } else if(!m.rangosOk.length){
    detalle = 'Ningún nodo de este bloque alcanza los ' + m.minimo + ' títulos.';
  } else {
    detalle = m.rangosOk.length + ' nodos sí los alcanzan.';
  }
  return '<p class="nota-tabla">' + cabeza + detalle + '</p>';
}

var specTes = null;
// El color distingue la ENTIDAD y el trazo la FECHA: T-1 va en el tono claro y
// discontinuo, T en el oscuro y continuo. Asi la identidad nunca depende solo del
// color, que es lo que pide la lectura con daltonismo y la impresion en gris.
//
// El azul y el verde estan validados como pareja categorica: 21,2 de separacion en
// deuteranopia y 22,3 en vision normal, contra un umbral de 8. Los dos tonos claros
// pasan de 3:1 de contraste contra el blanco, el minimo para un trazo que no es texto
// (3,39 el azul y 3,33 el verde).
//
// Las barras van en gris azulado y no en un tono de la paleta: al no competir de color
// con las lineas se pueden dejar mas opacas sin taparlas. Los numeros del eje derecho
// van en un gris mas oscuro, porque el de las barras no alcanza los 4,5:1 que necesita
// un texto.
var COLORES = {
  barra: '#8FA0B2', barraOpacidad: 0.7, deltaEje: '#5A6A78',
  bloqueT1: '#5E8FC4', bloqueT: '#1A5FA8',
  copT1: '#5E8FC4', copT: '#1A5FA8',
  uvrT1: '#3F9E6B', uvrT: '#0E8A4A'
};

function renderTes(){
  var filas = SX.tes(D, rt(), rt1());
  var grupos = '<tr><th class="grupo" colspan="7">Condiciones faciales</th>' +
    '<th class="grupo" colspan="4">Plazo y duración</th>' +
    '<th class="grupo" colspan="2">Precio sucio</th>' +
    '<th class="grupo" colspan="3">Valoración</th>' +
    '<th class="grupo">Sensibilidad</th></tr>';
  var cols = ['Nemotécnico', 'ISIN', 'Grupo', 'Moneda', 'Emisión', 'Vencimiento', 'Cupón',
              'Días', 'Años', 'Dur T-1', 'Dur T', 'T-1', 'T', 'T-1', 'T', 'Δ pb', 'DV01'];
  var cab = '<tr>' + cols.map(function(c){ return '<th>' + esc(c) + '</th>'; }).join('') + '</tr>';
  var cuerpo = filas.map(function(r){
    return '<tr><td class="key">' + esc(r.nemotecnico) + '</td><td>' + esc(r.isin) + '</td>' +
      '<td>' + esc(r.grupo) + '</td><td>' + esc(r.moneda) + '</td>' +
      '<td>' + esc(r.emision) + '</td><td>' + esc(r.vencimiento) + '</td>' +
      '<td>' + fmt(r.cupon, 2) + ' %</td>' +
      '<td class="sep">' + fmt(r.dias, 0) + '</td><td>' + fmt(r.anios, 2) + '</td>' +
      '<td>' + fmt(r.durT1, 3) + '</td><td>' + fmt(r.durT, 3) + '</td>' +
      '<td class="sep">' + fmt(r.precioT1, 3) + '</td><td>' + fmt(r.precioT, 3) + '</td>' +
      '<td class="sep">' + pct(r.tasaT1) + '</td><td>' + pct(r.tasaT) + '</td>' +
      '<td class="' + clase(r.dTasa) + '">' + bps(r.dTasa) + '</td>' +
      '<td class="sep">' + fmt(r.dv01, 0) + '</td></tr>';
  }).join('');
  var series = [
    { name: 'COP T-1', color: COLORES.copT1, dash: '4 3', points: puntosTes(filas, 'COP', 'aniosT1', 'tasaT1') },
    { name: 'COP T',   color: COLORES.copT,  points: puntosTes(filas, 'COP', 'anios', 'tasaT') },
    { name: 'UVR T-1', color: COLORES.uvrT1, dash: '4 3', points: puntosTes(filas, 'UVR', 'aniosT1', 'tasaT1') },
    { name: 'UVR T',   color: COLORES.uvrT,  points: puntosTes(filas, 'UVR', 'anios', 'tasaT') }
  ];
  $('tes-card').innerHTML =
    '<div class="card-hd"><h3>Valoración observada por plazo</h3>' +
    '<span class="meta">' + fmt(filas.length, 0) + ' referencias en las dos fechas</span>' +
    botonXls('TES por plazo') + '</div>' +
    '<div class="chart" id="ch-tes"></div>' +
    '<div class="leyenda">' + series.map(function(s){
      return '<span><i style="border-top-color:' + s.color + ';border-top-style:' +
             (s.dash ? 'dashed' : 'solid') + '"></i>' + esc(s.name) + '</span>'; }).join('') +
    '</div><div class="tw"><table><thead>' + grupos + cab + '</thead><tbody>' + cuerpo + '</tbody></table></div>';
  specTes = { xlabel: 'Plazo (años)', ylabel: 'Valoración', series: series };
}
function dibujarTes(){ if(specTes) dibujar($('ch-tes'), specTes); }
function puntosTes(filas, grupo, cx, ct){
  return filas.filter(function(r){ return r.grupo === grupo && r[cx] > 0 && r[ct] !== null; })
              .map(function(r){ return [r[cx], r[ct]]; })
              .sort(function(a, b){ return a[0] - b[0]; });
}

function mezclarIssues(){
  var vistos = {}, out = [];
  [rt(), rt1()].forEach(function(r){
    r.issues.forEach(function(i){
      if(vistos[i.cod]) return;
      vistos[i.cod] = 1; out.push(i);
    });
  });
  var orden = { error: 0, aviso: 1, info: 2 };
  out.sort(function(a, b){ return orden[a.sev] - orden[b.sev]; });
  return out;
}
function renderCalidad(){
  var issues = mezclarIssues();
  if(!issues.length){
    $('calidad').innerHTML = '<div class="issue info"><div class="hd">' +
      '<h3>Sin observaciones</h3></div><p>No hay nada por revisar en estas dos fechas.</p></div>';
    return;
  }
  var etiqueta = { error: 'Error', aviso: 'Aviso', info: 'Nota' };
  $('calidad').innerHTML = issues.map(function(i){
    return '<div class="issue ' + i.sev + '"><div class="hd"><h3>' + etiqueta[i.sev] + '</h3>' +
      '<span class="cod">' + esc(i.cod) + '</span>' +
      (i.filas ? '<span class="cnt">' + fmt(i.filas, 0) + ' títulos</span>' : '') +
      '</div><p>' + esc(D.mensajes[i.cod] || '') + '</p>' +
      (i.muestra && i.muestra.length
        ? '<div class="muestra">Valores: ' + esc(i.muestra.join(', ')) + '</div>' : '') +
      '</div>';
  }).join('');
}

function renderPie(){
  $('pie').innerHTML =
    '<dl>' +
    '<dt>Fechas en la serie</dt><dd>' + D.fechas.length + ' · de ' + esc(D.fechas[0]) +
      ' a ' + esc(D.fechas[D.fechas.length - 1]) + '</dd>' +
    '<dt>Archivo T</dt><dd>' + esc(rt().archivo) + ' · ' + fmt(rt().n_registros, 0) + ' registros</dd>' +
    '<dt>Archivo T-1</dt><dd>' + esc(rt1().archivo) + ' · ' + fmt(rt1().n_registros, 0) + ' registros</dd>' +
    '<dt>IPC en pantalla</dt><dd>T ' + pct(S.ipcT, 2) + ' · T-1 ' + pct(S.ipcT1, 2) + '</dd>' +
    '<dt>Tasa BanRep</dt><dd>' + pct(S.br, 2) + ' · no entra en ningún cálculo</dd>' +
    '<dt>IPC de la duración</dt><dd>' + pct(D.params.ipc_referencia, 2) +
      ' · el mismo para toda la serie</dd>' +
    '<dt>Nominal DV01</dt><dd>' + fmt(CFG.nominalDv01, 0) + ' COP</dd>' +
    '<dt>Umbral de fragilidad</dt><dd>' + CFG.minTitulos + ' títulos por nodo</dd>' +
    '<dt>Fuente de parámetros</dt><dd>' + esc(D.params.fuente || 'no registrada') + '</dd>' +
    '<dt>Capturado por</dt><dd>' + esc(D.params.capturado_por || 'no registrado') + '</dd>' +
    '<dt>Generado</dt><dd>' + esc(D.generado) + ' · sx-pricer ' + esc(D.version) + '</dd>' +
    '</dl><p>Reporte autocontenido: no consulta servicios externos ni requiere conexión.</p>';
}

// ---------- graficas ----------
function leyenda(){
  return '<div class="leyenda">' +
    '<span><i style="border-top-color:' + COLORES.bloqueT1 + ';border-top-style:dashed"></i>T-1 · ' + esc(S.t1) + '</span>' +
    '<span><i style="border-top-color:' + COLORES.bloqueT + ';border-top-style:solid"></i>T · ' + esc(S.t) + '</span>' +
    '<span><i class="barra" style="background:' + COLORES.barra +
    ';opacity:' + COLORES.barraOpacidad + '"></i>' +
    'Δ en pb, eje derecho</span></div>';
}
function nice(lo, hi, n){
  if(!isFinite(lo) || !isFinite(hi)) return [0, 1, 1];
  if(lo === hi){ lo -= Math.abs(lo || 1) * 0.05; hi += Math.abs(hi || 1) * 0.05; }
  var raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), norm = raw / mag;
  var paso = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  return [Math.floor(lo / paso) * paso, Math.ceil(hi / paso) * paso, paso];
}
function svgEl(t, a){
  var x = document.createElementNS('http://www.w3.org/2000/svg', t);
  for(var k in a) x.setAttribute(k, a[k]);
  return x;
}
function dibujar(host, spec){
  if(!host) return;
  var barras = (spec.barras || []).filter(function(b){
    return b[0] != null && b[1] != null && isFinite(b[1]);
  }).sort(function(a, b){ return a[0] - b[0]; });

  var W = host.clientWidth || 900, H = host.clientHeight || 300;
  // el margen superior deja aire para que el titulo del eje no choque con la
  // primera etiqueta de la escala
  var M = { t: 28, r: barras.length ? 56 : 16, b: 34, l: 58 };
  var xs = [], ys = [];
  spec.series.forEach(function(s){ s.points.forEach(function(q){ xs.push(q[0]); ys.push(q[1]); }); });
  barras.forEach(function(b){ xs.push(b[0]); });
  if(!xs.length){
    host.innerHTML = '<p class="sin-datos">Sin datos suficientes para graficar.</p>';
    return;
  }
  var xb = nice(Math.min.apply(null, xs), Math.max.apply(null, xs), 6);
  var yb = nice(Math.min.apply(null, ys), Math.max.apply(null, ys), 5);
  var sx = function(v){ return M.l + (v - xb[0]) / (xb[1] - xb[0]) * (W - M.l - M.r); };
  var sy = function(v){ return H - M.b - (v - yb[0]) / (yb[1] - yb[0]) * (H - M.t - M.b); };
  var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none' });
  for(var v = yb[0]; v <= yb[1] + 1e-12; v += yb[2]){
    svg.appendChild(svgEl('line', { 'class': 'grid', x1: M.l, x2: W - M.r, y1: sy(v), y2: sy(v) }));
    var ty = svgEl('text', { x: M.l - 8, y: sy(v) + 3, 'text-anchor': 'end' });
    ty.textContent = pct(v, 2); svg.appendChild(ty);
  }
  for(var u = xb[0]; u <= xb[1] + 1e-12; u += xb[2]){
    var tx = svgEl('text', { x: sx(u), y: H - M.b + 15, 'text-anchor': 'middle' });
    tx.textContent = fmt(u, Math.abs(xb[2]) < 1 ? 1 : 0); svg.appendChild(tx);
  }
  // Eje derecho y barras de diferencia. La escala va centrada en cero para que el
  // signo se lea de inmediato, y las barras se dibujan ANTES de las lineas para que
  // queden detras. Cada barra se ancla en el punto de T y se extiende hasta los
  // puntos medios con sus vecinas, asi quedan pegadas aunque los puntos no esten
  // repartidos de forma pareja sobre el eje.
  var delta = {};
  if(barras.length){
    var tope = Math.max.apply(null, barras.map(function(b){ return Math.abs(b[1]); }));
    var db = nice(-tope, tope, 4);
    var sd = function(v){ return H - M.b - (v - db[0]) / (db[1] - db[0]) * (H - M.t - M.b); };
    for(var w = db[0]; w <= db[1] + 1e-12; w += db[2]){
      var td = svgEl('text', { 'class': 'ejed', x: W - M.r + 8, y: sd(w) + 3,
                               'text-anchor': 'start', fill: COLORES.deltaEje });
      td.textContent = bps(w, 0); svg.appendChild(td);
    }
    var px = barras.map(function(b){ return sx(b[0]); });
    var cero = sd(0);
    barras.forEach(function(b, i){
      var izq = i > 0 ? (px[i - 1] + px[i]) / 2
                      : px[i] - (px.length > 1 ? (px[1] - px[0]) / 2 : 6);
      var der = i < px.length - 1 ? (px[i] + px[i + 1]) / 2
                                  : px[i] + (px.length > 1 ? (px[i] - px[i - 1]) / 2 : 6);
      var y = sd(b[1]);
      svg.appendChild(svgEl('rect', { x: izq.toFixed(1),
        width: Math.max(der - izq, 0.6).toFixed(1),
        y: Math.min(y, cero).toFixed(1),
        height: Math.max(Math.abs(y - cero), 0.6).toFixed(1),
        fill: COLORES.barra, opacity: COLORES.barraOpacidad }));
      delta[b[0]] = b[1];
    });
    svg.appendChild(svgEl('line', { x1: M.l, x2: W - M.r, y1: cero, y2: cero,
                                    stroke: COLORES.barra, 'stroke-width': 1.2 }));
    var dl = svgEl('text', { 'class': 'lbl', x: W - M.r + 8, y: 12, 'text-anchor': 'start' });
    dl.textContent = 'Δ pb'; svg.appendChild(dl);
  }

  svg.appendChild(svgEl('line', { 'class': 'ax', x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b }));
  var xl = svgEl('text', { 'class': 'lbl', x: W - M.r, y: H - 4, 'text-anchor': 'end' });
  xl.textContent = spec.xlabel || ''; svg.appendChild(xl);
  var yl = svgEl('text', { 'class': 'lbl', x: M.l - 8, y: 12, 'text-anchor': 'end' });
  yl.textContent = spec.ylabel || ''; svg.appendChild(yl);

  var todos = [];
  spec.series.forEach(function(s){
    if(!s.points.length) return;
    var d = s.points.map(function(q, i){
      return (i ? 'L' : 'M') + sx(q[0]).toFixed(1) + ' ' + sy(q[1]).toFixed(1); }).join(' ');
    svg.appendChild(svgEl('path', { d: d, fill: 'none', stroke: s.color, 'stroke-width': 1.8,
      'stroke-dasharray': s.dash || '', 'stroke-linejoin': 'round' }));
    s.points.forEach(function(q){
      svg.appendChild(svgEl('circle', { cx: sx(q[0]), cy: sy(q[1]), r: 2.4, fill: s.color }));
      todos.push({ x: sx(q[0]), y: sy(q[1]), s: s.name, vx: q[0], vy: q[1],
                   d: delta[q[0]] });
    });
  });
  host.innerHTML = ''; host.appendChild(svg);
  host.onmousemove = function(ev){
    var r = host.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
    var best = null, bd = 1e9;
    todos.forEach(function(q){
      var d = (q.x - mx) * (q.x - mx) + (q.y - my) * (q.y - my);
      if(d < bd){ bd = d; best = q; }
    });
    if(best && bd < 1600){
      tip.textContent = best.s + '\n' + (spec.xlabel || 'x') + ': ' + fmt(best.vx, 3) +
                        '\n' + (spec.ylabel || 'y') + ': ' + pct(best.vy, 3) +
                        (best.d === undefined ? '' : '\nΔ: ' + bps(best.d) + ' pb');
      tip.style.left = (ev.clientX + 14) + 'px';
      tip.style.top = (ev.clientY + 14) + 'px';
      tip.style.opacity = 1;
    } else tip.style.opacity = 0;
  };
  host.onmouseleave = function(){ tip.style.opacity = 0; };
}
function dibujarUnBloque(gid){
  D.bloques.forEach(function(b){
    b.familias.forEach(function(fam){
      if(idChart(b.id, fam) !== gid) return;
      var filas = nodos(b.id, fam);
      var vista = serieGrafica(gid, serieDeBloque(b));
      var hayMg = filas.some(function(r){ return r.margenT !== null; });
      // En IPC las dos series salen de la misma fila: «tasa» es la del proveedor y
      // «margen» el margen real. En IBR el margen es el del atajo, que puede faltar
      // si no hay curva, y entonces la grafica se queda en la tasa.
      var campoT, campoT1, etiqueta;
      if(b.margenAtajo && hayMg && vista === 'margen'){
        campoT = 'margenT'; campoT1 = 'margenT1'; etiqueta = 'Margen sobre IBR';
      } else if(b.indexado && vista === 'tir'){
        campoT = 'brutaT'; campoT1 = 'brutaT1'; etiqueta = 'Tasa';
      } else {
        campoT = 'tasaT'; campoT1 = 'tasaT1';
        etiqueta = b.indexado ? 'Margen real' : 'Tasa';
      }
      var esMargen = campoT === 'margenT';
      var pts = function(cx, ct){
        return filas.filter(function(r){ return r[cx] > 0 && r[ct] !== null; })
                    .map(function(r){ return [r[cx], r[ct]]; })
                    .sort(function(a, b){ return a[0] - b[0]; });
      };
      // la barra sigue la serie que muestre el conmutador y se ancla en el plazo
      // de T, que es donde cae el punto de la curva de T
      var campoD = esMargen ? 'dMargen' : (campoT === 'brutaT' ? 'dBruta' : 'dTasa');
      var barras = filas.filter(function(r){ return r.plazoT > 0 && r[campoD] !== null; })
                        .map(function(r){ return [r.plazoT, r[campoD]]; });
      dibujar($(gid), {
        xlabel: 'Plazo (años)', ylabel: etiqueta, barras: barras,
        series: [
          { name: 'T-1', color: COLORES.bloqueT1, dash: '4 3', points: pts('plazoT1', campoT1) },
          { name: 'T',   color: COLORES.bloqueT,  points: pts('plazoT', campoT) }
        ]
      });
    });
  });
}

function dibujarBloques(){
  D.bloques.forEach(function(b){
    b.familias.forEach(function(fam){ dibujarUnBloque(idChart(b.id, fam)); });
  });
}

// ---------- rentabilidades esperadas ----------
var HPR = { tipo: 'fs', escenario: 'Base', delta: 0 };

function bloquePorTipo(id){
  return D.bloques.filter(function(b){ return b.id === id; })[0];
}

// El margen sobre el que actua el delta: en IPC se despeja de la propia TIR con el
// IPC del archivo de escenarios, en IBR es el del atajo que ya trae la tabla.
// El margen de un nodo, tal como lo muestra la pestaña de curvas: en IPC es el
// margen real despejado con el IPC de la barra —el mismo numero de aquella tabla, no
// uno propio de esta pestaña— y en IBR el del atajo de la bvc.
function margenDelNodo(tipo, fila){
  if(tipo === 'fs') return 0;
  if(tipo === 'ipc') return fila.tasaT;
  return fila.margenT;
}

function filasHpr(){
  var b = bloquePorTipo(HPR.tipo);
  var filas = SX.nodos(D, rt(), rt1(), HPR.tipo, 'CDT', S.ipcT, S.ipcT1);
  // En IPC la tasa de entrada se recompone con el IPC de la barra, que es el mismo
  // con el que se despejo el margen real: los dos se cancelan y V0 descuenta a la
  // TIR del nodo. En los demas tipos manda el indice de la senda.
  var indiceEntrada = HPR.tipo === 'ipc' ? S.ipcT : null;
  // la senda diaria publicada de IBR, para las lecturas anteriores a la valoracion
  var publicada = HPR.tipo === 'ibr' ? ((rt().ibr || {}).historico || {}) : null;
  // la curva forward IND_IBR del dia habil anterior, para los cupones de V0 en IBR
  var curvaIbr = HPR.tipo === 'ibr' ? ((rt().ibr || {}).curva || {}) : null;
  var fuera = [], excluidas = [];
  filas.forEach(function(r){
    var m = margenDelNodo(HPR.tipo, r);
    if(r.brutaT === null || r.cuponT === null || m === null){
      excluidas.push(r); return;
    }
    var venc = SX.sumarDias(r.hastaT, -1);       // fin de ventana
    var res = SX.rentabilidad(D, {
      tipo: HPR.tipo, fechaVal: S.t, vencimiento: venc, tir: r.brutaT,
      cupon: r.cuponT / 100, margen: m, escenario: HPR.escenario,
      deltaPb: HPR.delta, indiceEntrada: indiceEntrada, historico: publicada,
      curva: curvaIbr
    });
    if(!res){ excluidas.push(r); return; }
    fuera.push({ fila: r, venc: venc, margen: m, res: res });
  });
  return { filas: fuera, excluidas: excluidas };
}

function renderControlesHpr(){
  var tipos = D.bloques.map(function(b){
    return '<button type="button" class="tg" data-hpr-tipo="' + b.id + '" aria-pressed="' +
      (HPR.tipo === b.id) + '">' + esc(b.label.split(' (')[0]) + '</button>';
  }).join('');
  var escs = (D.escenarios ? D.escenarios.escenarios : []).map(function(e){
    return '<button type="button" class="tg" data-hpr-esc="' + esc(e) + '" aria-pressed="' +
      (HPR.escenario === e) + '"' + (HPR.tipo === 'fs' ? ' disabled' : '') + '>' +
      esc(e) + '</button>';
  }).join('');
  $('hpr-controles').innerHTML =
    '<label>Tipo <span class="toggle">' + tipos + '</span></label>' +
    '<label>Escenario <span class="toggle">' + (escs || '<span class="u">sin sendas</span>') +
      '</span></label>' +
    '<label for="hpr-delta">Δ TIR <input id="hpr-delta" type="number" step="1" ' +
      'value="' + HPR.delta + '" inputmode="numeric" ' +
      'aria-label="Delta sobre la tasa de salida, en puntos básicos"><span class="u">pb</span></label>' +
    '<span class="pista">' + (HPR.tipo === 'fs'
      ? 'La tasa fija no usa escenario: su cupón se conoce desde la negociación.'
      : 'El delta desplaza el margen y con él la tasa de salida; la de entrada no se mueve.') +
    '</span>';

  [].forEach.call($('hpr-controles').querySelectorAll('[data-hpr-tipo]'), function(b){
    b.onclick = function(){ HPR.tipo = b.dataset.hprTipo; renderHpr(); };
  });
  [].forEach.call($('hpr-controles').querySelectorAll('[data-hpr-esc]'), function(b){
    b.onclick = function(){ HPR.escenario = b.dataset.hprEsc; renderHpr(); };
  });
  $('hpr-delta').oninput = function(){
    var v = parseFloat(String(this.value).replace(',', '.'));
    HPR.delta = isFinite(v) ? v : 0;
    renderTablasHpr();
  };
}

function tablaHpr(datos, indice, titulo, subtitulo){
  var cols = ['Fechas (T)', 'Rango', 'Vencimiento', 'Días', 'Cupón', 'Tasa (T)',
              'Margen', 'HPR'];
  var cab = '<tr>' + cols.map(function(c){ return '<th>' + esc(c) + '</th>'; }).join('') + '</tr>';
  var cuerpo = datos.filas.map(function(d){
    var r = d.res[indice], f = d.fila;
    var celda;
    if(r.hpr === null || !isFinite(r.hpr)){
      celda = '<td class="neutro">' + SX.VACIO + '</td>';
    } else if(r.alVencimiento){
      celda = '<td class="alvenc">' + pct(r.hpr) + '<small>(al venc.)</small></td>';
    } else {
      celda = '<td>' + pct(r.hpr) + '</td>';
    }
    var marca = r.extrapolado
      ? '<span class="extrap" title="La senda de proyección no llega hasta esta fecha: ' +
        'se arrastra el último dato publicado">*</span>' : '';
    return '<tr><td class="key ventana">' + esc(SX.dia(f.desdeT) + ' a ' + SX.dia(d.venc)) +
      '</td><td class="key">' + esc(f.rango) + '</td>' +
      '<td>' + esc(d.venc) + marca + '</td>' +
      '<td class="sep">' + fmt(SX.diasEntre(S.t, d.venc), 0) + '</td>' +
      '<td class="sep">' + fmt(f.cuponT, 3) + ' %</td>' +
      '<td>' + pct(f.brutaT) + '</td>' +
      '<td>' + (HPR.tipo === 'fs' ? SX.VACIO : pct(d.margen)) + '</td>' +
      celda + '</tr>';
  }).join('');
  return '<div class="card"><div class="card-hd"><h3>' + esc(titulo) + '</h3>' +
    '<span class="pill n">' + esc(subtitulo) + '</span>' +
    '<span class="meta">' + datos.filas.length + ' rangos</span>' +
    // el nombre de una hoja de Excel no pasa de 31 caracteres, asi que «Horizonte 90
    // dias» entra como «90 dias»
    botonXls('HPR ' + HPR.tipo.toUpperCase() + ' ' +
             titulo.replace('Horizonte ', '') + ' ' + HPR.escenario) + '</div>' +
    '<div class="tw"><table><thead>' + cab + '</thead><tbody>' + cuerpo +
    '</tbody></table></div>' + notaHpr(datos, indice) + '</div>';
}

function notaHpr(datos, indice){
  var alVenc = datos.filas.filter(function(d){ return d.res[indice].alVencimiento; });
  var extrap = datos.filas.filter(function(d){ return d.res[indice].extrapolado; });
  var partes = [];
  if(alVenc.length){
    partes.push('<b>' + alVenc.length + ' rango(s) vencen antes del horizonte</b>: su ' +
      'celda muestra el HPR al vencimiento, marcado «(al venc.)», no el del horizonte pedido.');
  }
  if(extrap.length){
    partes.push('<b>' + extrap.length + ' rango(s) marcados con *</b> necesitan el índice ' +
      'más allá del último dato de la senda: se arrastra el último publicado.');
  }
  if(datos.excluidas.length){
    partes.push(datos.excluidas.length + ' rango(s) quedaron fuera por no tener tasa, ' +
      'cupón o margen.');
  }
  return partes.length ? '<p class="nota-tabla">' + partes.join(' ') + '</p>' : '';
}

function renderTablasHpr(){
  if(HPR.tipo !== 'fs' && !D.escenarios){
    $('hpr-tablas').innerHTML = '<div class="issue aviso"><div class="hd">' +
      '<h3>Sin sendas de proyección</h3></div><p>Los rangos indexados necesitan el ' +
      'archivo de escenarios para proyectar cupones y precio de salida. Vuelve a correr ' +
      'la herramienta con <code>--escenarios</code>.</p></div>';
    return;
  }
  var datos = filasHpr();
  if(!datos.filas.length){
    $('hpr-tablas').innerHTML = '<div class="issue aviso"><div class="hd">' +
      '<h3>Sin rangos con datos</h3></div><p>Ningún rango de este tipo tiene tasa y ' +
      'cupón en la fecha seleccionada.</p></div>';
    return;
  }
  var sub = HPR.tipo === 'fs' ? 'sin escenario'
            : HPR.escenario + (HPR.delta ? ' · Δ ' + bps(HPR.delta, 0) + ' pb' : '');
  if(HPR.tipo === 'fs' && HPR.delta) sub += ' · Δ ' + bps(HPR.delta, 0) + ' pb';
  $('hpr-tablas').innerHTML =
    tablaHpr(datos, 0, 'Horizonte 90 días', sub) +
    tablaHpr(datos, 1, 'Horizonte 180 días', sub) +
    tablaHpr(datos, 2, 'Al vencimiento', sub);
}

function renderHpr(){
  renderControlesHpr();
  renderTablasHpr();
}

// ---------- pestanas ----------
// Un SVG dibujado dentro de un panel oculto mide cero de ancho, asi que las
// graficas se trazan cuando la pestana se hace visible y no al construir el HTML.
var TABS = [
  { boton: 'tab-curvas', panel: 'panel-curvas', hash: 'curvas', dibujar: dibujarBloques },
  { boton: 'tab-hpr',    panel: 'panel-hpr',    hash: 'hpr',    dibujar: function(){} },
  { boton: 'tab-datos',  panel: 'panel-datos',  hash: 'datos',  dibujar: dibujarTes }
];
var activa = 0;

// El ancla de la direccion se actualiza de ultimo y entre try/catch. Abierto con
// doble clic el protocolo es file://, cuyo origen es «null», y ahi replaceState
// lanza SecurityError: si eso corta la funcion antes de dibujar, la grafica de la
// pestana queda vacia. Primero se dibuja; el ancla es un lujo, no un requisito.
function fijarHash(h){
  if(location.hash.slice(1) === h) return;
  try { history.replaceState(null, '', '#' + h); }
  catch(e){
    try { location.hash = h; } catch(e2){ /* sin ancla; la pestana igual funciona */ }
  }
}

function mostrar(i, conFoco){
  activa = i;
  TABS.forEach(function(t, j){
    var b = $(t.boton);
    b.setAttribute('aria-selected', j === i ? 'true' : 'false');
    b.tabIndex = j === i ? 0 : -1;
    $(t.panel).hidden = j !== i;
  });
  TABS[i].dibujar();
  if(conFoco) $(TABS[i].boton).focus();
  window.scrollTo(0, 0);
  fijarHash(TABS[i].hash);
}

// De --top-h depende donde se pegan los encabezados de tabla al hacer scroll. La
// altura de la cabecera cambia con el ancho de la ventana (los controles se
// reacomodan en varias filas), asi que se mide en vez de fijarse a mano.
function ajustarAlto(){
  var cabecera = document.querySelector('.top');
  if(!cabecera) return;
  document.documentElement.style.setProperty('--top-h', cabecera.offsetHeight + 'px');
}

// ---------- exportar una tabla a Excel ----------
// Se escribe un .xlsx de verdad, no un CSV: el reporte usa coma decimal y punto de
// miles, asi que un CSV solo abriria bien en un Excel con configuracion regional en
// espaniol. Dentro del xlsx los numeros van con punto decimal —el formato lo fija el
// estandar, no la maquina— y Excel los muestra segun la configuracion de cada quien.
//
// Un xlsx es un ZIP con XML dentro. No hay libreria que cargar: el reporte tiene que
// seguir funcionando abierto desde el disco y sin red, asi que el ZIP se arma a mano.
// Se guarda sin comprimir (metodo 0), que evita implementar deflate y solo cuesta
// tamanio en un archivo que vive unos segundos.

var CRC_TABLA = (function(){
  var t = new Uint32Array(256);
  for(var n = 0; n < 256; n++){
    var c = n;
    for(var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(bytes){
  var c = 0xFFFFFFFF;
  for(var i = 0; i < bytes.length; i++) c = CRC_TABLA[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
function utf8(s){ return new TextEncoder().encode(s); }

// Fecha DOS fija (1-ene-2020). El estandar ZIP no admite ceros ahi, y la fecha real
// del archivo no aporta nada.
var ZIP_FECHA = 0x5021, ZIP_HORA = 0;

function zip(archivos){
  var piezas = [], central = [], desplazamiento = 0;
  archivos.forEach(function(a){
    var nombre = utf8(a.nombre), datos = a.datos, n = datos.length, crc = crc32(datos);
    var lh = new Uint8Array(30 + nombre.length), v = new DataView(lh.buffer);
    v.setUint32(0, 0x04034b50, true);
    v.setUint16(4, 20, true);          // version necesaria
    v.setUint16(6, 0x0800, true);      // bit 11: los nombres van en UTF-8
    v.setUint16(8, 0, true);           // metodo 0: almacenado
    v.setUint16(10, ZIP_HORA, true); v.setUint16(12, ZIP_FECHA, true);
    v.setUint32(14, crc, true); v.setUint32(18, n, true); v.setUint32(22, n, true);
    v.setUint16(26, nombre.length, true); v.setUint16(28, 0, true);
    lh.set(nombre, 30);

    var cd = new Uint8Array(46 + nombre.length), w = new DataView(cd.buffer);
    w.setUint32(0, 0x02014b50, true);
    w.setUint16(4, 20, true); w.setUint16(6, 20, true);
    w.setUint16(8, 0x0800, true); w.setUint16(10, 0, true);
    w.setUint16(12, ZIP_HORA, true); w.setUint16(14, ZIP_FECHA, true);
    w.setUint32(16, crc, true); w.setUint32(20, n, true); w.setUint32(24, n, true);
    w.setUint16(28, nombre.length, true);
    w.setUint32(42, desplazamiento, true);
    cd.set(nombre, 46);

    piezas.push(lh, datos); central.push(cd);
    desplazamiento += lh.length + n;
  });
  var largoCentral = central.reduce(function(a, c){ return a + c.length; }, 0);
  var fin = new Uint8Array(22), f = new DataView(fin.buffer);
  f.setUint32(0, 0x06054b50, true);
  f.setUint16(8, archivos.length, true); f.setUint16(10, archivos.length, true);
  f.setUint32(12, largoCentral, true); f.setUint32(16, desplazamiento, true);
  return new Blob(piezas.concat(central, [fin]),
                  { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}

function xmlEsc(s){
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;');
}
function columna(i){                    // 0 -> A, 25 -> Z, 26 -> AA
  var s = '';
  for(i += 1; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + (i - 1) % 26) + s;
  return s;
}

// Estilos: 0 general, 1 porcentaje con tres decimales, 2 negrita para los encabezados.
var ESTILOS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
  '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.000%"/></numFmts>' +
  '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>' +
  '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>' +
  '<fills count="2"><fill><patternFill patternType="none"/></fill>' +
  '<fill><patternFill patternType="gray125"/></fill></fills>' +
  '<borders count="1"><border/></borders>' +
  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
  '<cellXfs count="3"><xf xfId="0"/>' +
  '<xf xfId="0" numFmtId="164" applyNumberFormat="1"/>' +
  '<xf xfId="0" fontId="1" applyFont="1"/></cellXfs>' +
  '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
  '</styleSheet>';

// `filas` es una matriz de celdas; cada celda es null, una cadena, o {n: numero,
// pct: bool}. Las `cabeceras` primeras filas salen en negrita.
function libro(hoja, filas, cabeceras){
  // Ancho de columna a ojo, por el texto mas largo de cada una. Sin esto, las
  // ventanas y los nemotecnicos salen cortados y hay que ensanchar a mano.
  var anchos = [];
  filas.forEach(function(fila){
    fila.forEach(function(c, j){
      // los numeros se guardan con toda su precision pero Excel los muestra
      // formateados, asi que su ancho no depende del literal guardado
      var largo = c === null || c === undefined ? 0
                : (typeof c === 'object' ? 10 : String(c).length);
      if(!(anchos[j] > largo)) anchos[j] = largo;
    });
  });
  var cols = anchos.map(function(a, j){
    return '<col min="' + (j + 1) + '" max="' + (j + 1) + '" width="' +
           Math.min(40, Math.max(9, (a || 0) + 2)) + '" customWidth="1"/>';
  }).join('');

  var xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    (cols ? '<cols>' + cols + '</cols>' : '') + '<sheetData>';
  filas.forEach(function(fila, i){
    xml += '<row r="' + (i + 1) + '">';
    fila.forEach(function(c, j){
      if(c === null || c === undefined || c === '') return;
      var ref = columna(j) + (i + 1);
      if(typeof c === 'object'){
        xml += '<c r="' + ref + '"' + (c.pct ? ' s="1"' : '') + '><v>' + c.n + '</v></c>';
      } else {
        xml += '<c r="' + ref + '" t="inlineStr"' + (i < cabeceras ? ' s="2"' : '') +
               '><is><t xml:space="preserve">' + xmlEsc(c) + '</t></is></c>';
      }
    });
    xml += '</row>';
  });
  xml += '</sheetData></worksheet>';

  var nombreHoja = hoja.replace(/[\[\]:*?\/\\]/g, ' ').slice(0, 31) || 'Hoja1';
  return zip([
    { nombre: '[Content_Types].xml', datos: utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
      '</Types>') },
    { nombre: '_rels/.rels', datos: utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      '</Relationships>') },
    { nombre: 'xl/workbook.xml', datos: utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      '<sheets><sheet name="' + xmlEsc(nombreHoja) + '" sheetId="1" r:id="rId1"/></sheets></workbook>') },
    { nombre: 'xl/_rels/workbook.xml.rels', datos: utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
      '</Relationships>') },
    { nombre: 'xl/styles.xml', datos: utf8(ESTILOS) },
    { nombre: 'xl/worksheets/sheet1.xml', datos: utf8(xml) }
  ]);
}

// Deshace el formato del reporte: punto de miles, coma decimal, sufijo de porcentaje
// y el signo de los delta. Devuelve null si el texto no es un numero, y entonces la
// celda sale como texto —fechas, nemotecnicos, rangos—.
function comoNumero(txt){
  var s = txt.replace(/ /g, ' ').replace(/−/g, '-').trim();
  var esPct = /%$/.test(s);
  s = s.replace(/%/g, '').trim();
  if(!/^[+-]?\d+(\.\d{3})*(,\d+)?$/.test(s)) return null;
  var v = parseFloat(s.replace(/\./g, '').replace(',', '.'));
  if(!isFinite(v)) return null;
  return { n: esPct ? v / 100 : v, pct: esPct };
}

// Lee la tabla tal como esta en pantalla. Va contra el DOM y no contra el modelo de
// datos a proposito: asi lo que se descarga es exactamente lo que se ve —el par de
// fechas, el escenario, el delta y el IPC que haya puestos en ese momento— y un
// cambio en cualquier tabla no obliga a tocar el exportador.
function leerTabla(tabla){
  var filas = [], cabeceras = 0;
  Array.prototype.forEach.call(tabla.rows, function(tr){
    if(tr.parentNode.tagName === 'THEAD') cabeceras++;
    var fila = [];
    Array.prototype.forEach.call(tr.cells, function(td){
      var copia = td.cloneNode(true);
      // los adornos no son dato: la marca de extrapolacion, el «(al venc.)» y los
      // titulos de los conmutadores
      Array.prototype.forEach.call(copia.querySelectorAll('small,.extrap,button'),
        function(x){ x.remove(); });
      var txt = (copia.textContent || '').replace(/\s+/g, ' ').trim();
      var celda = txt === '' || txt === SX.VACIO ? null : (comoNumero(txt) || txt);
      fila.push(celda);
      for(var k = 1; k < (td.colSpan || 1); k++) fila.push(null);
    });
    filas.push(fila);
  });
  return { filas: filas, cabeceras: cabeceras };
}

function descargar(blob, nombre){
  var url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
}

function nombreArchivo(base){
  return (base + ' ' + (S.t || '')).replace(/[\\/:*?"<>|]/g, '-')
                                   .replace(/\s+/g, ' ').trim() + '.xlsx';
}

function botonXls(nombre){
  return '<button type="button" class="xls" data-xls="' + esc(nombre) +
         '" title="Descargar esta tabla en Excel">Excel</button>';
}

// Delegado en el documento: las tarjetas se vuelven a dibujar enteras cada vez que
// cambia el estado, asi que enganchar el evento a cada boton se perderia al redibujar.
function cablearDescargas(){
  document.addEventListener('click', function(ev){
    var b = ev.target.closest ? ev.target.closest('.xls') : null;
    if(!b) return;
    var tarjeta = b.closest('.card'), tabla = tarjeta && tarjeta.querySelector('table');
    if(!tabla){ return; }
    var nombre = b.getAttribute('data-xls') || 'tabla';
    var t = leerTabla(tabla);
    descargar(libro(nombre, t.filas, t.cabeceras), nombreArchivo(nombre));
  });
}

function cablearPestanas(){
  TABS.forEach(function(t, i){
    var b = $(t.boton);
    b.onclick = function(){ mostrar(i, false); };
    b.onkeydown = function(ev){
      var salto = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
      if(salto !== undefined){
        ev.preventDefault();
        mostrar((i + salto + TABS.length) % TABS.length, true);
      } else if(ev.key === 'Home'){ ev.preventDefault(); mostrar(0, true); }
      else if(ev.key === 'End'){ ev.preventDefault(); mostrar(TABS.length - 1, true); }
    };
  });
  addEventListener('beforeprint', function(){
    TABS.forEach(function(t){ $(t.panel).hidden = false; });
    dibujarBloques(); dibujarTes();
  });
  addEventListener('afterprint', function(){ mostrar(activa, false); });
}

// ---------- orquestacion ----------
// Una selección inválida no se compromete: se avisa y se devuelven los controles
// al último par válido. Si el estado se quedara con T-1 >= T, cualquier redibujado
// posterior (cambiar de pestaña, conmutar la serie de una gráfica) partiría de un
// par que la pantalla no está mostrando.
function sincronizar(){
  if(S.t1 >= S.t){
    $('aviso-orden').textContent = 'T-1 debe ser anterior a T; se mantuvo el par anterior.';
    S.t = ultimoValido.t; S.t1 = ultimoValido.t1;
    S.ipcT = ipcDe(S.t); S.ipcT1 = ipcDe(S.t1);
    $('sel-t').value = S.t; $('sel-t1').value = S.t1;
    return;
  }
  $('aviso-orden').textContent = '';
  ultimoValido = { t: S.t, t1: S.t1 };
  $('ipc-t').value = (S.ipcT * 100).toFixed(2);
  $('ipc-t1').value = (S.ipcT1 * 100).toFixed(2);
  $('br').value = (S.br * 100).toFixed(2);
  actualizar();
  ajustarAlto();
}
function actualizar(){
  if(!rt() || !rt1()) return;
  document.title = 'Renta fija local · ' + S.t + ' vs ' + S.t1;
  renderResumen();
  renderCinta();
  $('embudos').innerHTML = embudo(rt1()) + embudo(rt());
  renderBloques();
  renderHpr();
  renderTes();
  renderCalidad();
  renderPie();
  TABS[activa].dibujar();
}
function leerNumero(id, porDefecto){
  var x = parseFloat(String($(id).value).replace(',', '.'));
  return isFinite(x) ? x / 100 : porDefecto;
}
function iniciar(){
  S.t = D.seleccion.t; S.t1 = D.seleccion.t1;
  ultimoValido = { t: S.t, t1: S.t1 };
  S.ipcT = ipcDe(S.t); S.ipcT1 = ipcDe(S.t1); S.br = D.params.tasa_br;
  llenarSelect($('sel-t'), S.t);
  llenarSelect($('sel-t1'), S.t1);
  $('sel-t').onchange = function(){ S.t = this.value; S.ipcT = ipcDe(S.t); sincronizar(); };
  $('sel-t1').onchange = function(){ S.t1 = this.value; S.ipcT1 = ipcDe(S.t1); sincronizar(); };
  $('ipc-t').oninput = function(){ S.ipcT = leerNumero('ipc-t', S.ipcT); actualizar(); };
  $('ipc-t1').oninput = function(){ S.ipcT1 = leerNumero('ipc-t1', S.ipcT1); actualizar(); };
  $('br').oninput = function(){ S.br = leerNumero('br', S.br); renderPie(); };
  cablearPestanas();
  cablearDescargas();
  ajustarAlto();
  var pedida = location.hash.slice(1);
  TABS.forEach(function(t, i){ if(t.hash === pedida) activa = i; });
  sincronizar();
  mostrar(activa, false);

  var to;
  addEventListener('resize', function(){
    clearTimeout(to);
    to = setTimeout(function(){ ajustarAlto(); TABS[activa].dibujar(); }, 150);
  });
}
iniciar();
})();
"""

# ----------------------------------------------------------------------------
# Documento
# ----------------------------------------------------------------------------

def render(*, serie, seleccion: tuple[str, str], params: MarketParams,
           tiempos: dict, version: str, escenarios=None) -> str:
    t1, t = seleccion
    layout = [{"nombre": f.name.replace("_", " "), "ini": f.start, "fin": f.end,
               "skip": f.kind == "skip", "desc": f.desc} for f in DETAIL_LAYOUT]
    bloques = [{"id": b.id, "label": b.label, "indicador": b.indicador,
                "periodicidad": b.periodicidad, "moneda": b.moneda,
                "familias": list(b.familias), "nota": b.nota,
                "margenAtajo": b.margen_atajo, "meses": b.meses,
                "indexado": b.indicador in ("IPC", "ICP", "IP4")}
               for b in cfg.BLOCKS]

    datos = serie.para_json()
    datos.update({
        "layout": layout,
        "bloques": bloques,
        "seleccion": {"t": t, "t1": t1},
        "ipcPorFecha": dict(params.ipc_por_fecha),
        "params": {"ipc_referencia": params.ipc_referencia, "tasa_br": params.tasa_br,
                   "fuente": params.fuente, "capturado_por": params.capturado_por},
        "config": {"minTitulos": cfg.MIN_TITULOS_POR_NODO,
                   "nominalDv01": params.nominal_dv01},
        "escenarios": escenarios.para_json() if escenarios is not None and
                      escenarios.activo else None,
        "hpr": {"horizontes": list(HORIZONTES),
                "pagos": dict(PAGOS_POR_ANIO), "indice": dict(INDICE_DE),
                },
        "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": version,
        "tiempos": tiempos,
    })
    payload = json.dumps(datos, separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")     # no cerrar el <script> por accidente

    avisos = "".join(
        f'<div class="issue aviso"><div class="hd"><h3>Aviso</h3>'
        f'<span class="cod">parametros</span></div><p>{e(a)}</p></div>'
        for a in params.avisos)

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Renta fija local</title>
<style>{CSS}</style></head><body>
<header class="top">
  <div class="top-in">
    <h1>Renta fija local</h1>
    <div class="tabs" role="tablist" aria-label="Secciones del reporte">
      <button type="button" class="tab" id="tab-curvas" role="tab"
        aria-controls="panel-curvas" aria-selected="true">Curvas por rango de plazo</button>
      <button type="button" class="tab" id="tab-hpr" role="tab"
        aria-controls="panel-hpr" aria-selected="false" tabindex="-1">Rentabilidades esperadas</button>
      <button type="button" class="tab" id="tab-datos" role="tab"
        aria-controls="panel-datos" aria-selected="false" tabindex="-1">Comparación y control</button>
    </div>
  </div>
  <div class="barra"><div class="barra-in">
    <label for="sel-t1">T-1 <select id="sel-t1" aria-label="Fecha de comparación"></select></label>
    <label for="sel-t">T <select id="sel-t" aria-label="Fecha de valoración"></select></label>
    <label for="ipc-t">IPC T <input id="ipc-t" type="number" step="0.01" inputmode="decimal"
      aria-label="IPC en la fecha T, en porcentaje"><span class="u">%</span></label>
    <label for="ipc-t1">IPC T-1 <input id="ipc-t1" type="number" step="0.01" inputmode="decimal"
      aria-label="IPC en la fecha T-1, en porcentaje"><span class="u">%</span></label>
    <label for="br">BanRep <input id="br" type="number" step="0.01" inputmode="decimal"
      aria-label="Tasa del Banco de la República, en porcentaje"><span class="u">%</span></label>
    <span class="aviso" id="aviso-orden"></span>
  </div></div>
</header>

<div class="wrap">
<noscript><p>Este reporte necesita JavaScript: las tablas se arman según el par de
fechas que elijas, así que no vienen escritas en el archivo.</p></noscript>

<div class="panel" id="panel-curvas" role="tabpanel" aria-labelledby="tab-curvas">
  <div id="bloques"></div>
</div>

<div class="panel" id="panel-hpr" role="tabpanel" aria-labelledby="tab-hpr" hidden>
<section id="rentabilidades"><p class="eyebrow">CDT sintético por rango</p>
<h2>Rentabilidades esperadas</h2>
<p class="lede">Cada ventana de la rejilla se trata como un CDT independiente que vence
al final de la ventana, con el cupón y la tasa que esa ventana muestra en T. No se
promedia ni se interpola entre rangos, y no entra ninguna fuente distinta de las que ya
usa el reporte más las sendas de proyección de IPC e IBR.</p>
<div class="controles" id="hpr-controles"></div>
<div id="hpr-tablas"></div>
</section>
</div>

<div class="panel" id="panel-datos" role="tabpanel" aria-labelledby="tab-datos" hidden>

<section id="resumen"><p class="eyebrow">Comparación</p><h2>Resumen</h2>
<div class="tiles" id="resumen-tiles"></div></section>

<section id="cinta"><p class="eyebrow">Origen del dato</p><h2>La cinta</h2>
<p class="lede">El archivo del proveedor es un plano de ancho fijo de 270 bytes por
título. Este es el primer registro del archivo de la fecha T, cortado por campo: cada
número del reporte se puede rastrear hasta una posición concreta de esta cinta. Las
columnas en gris son relleno que el proceso descarta.</p>
<div class="card"><div class="card-hd" id="cinta-hd"></div>
  <div class="cinta"><div class="cinta-in" id="cinta-in"></div></div></div>
<details class="raw"><summary>Ver controles de integridad de las dos fechas</summary>
<div style="margin-top:10px" id="checks"></div></details>
</section>

<section id="universo"><p class="eyebrow">Depuración</p>
<h2>Del archivo al universo valorado</h2>
<p class="lede">Las exclusiones se aplican antes de materializar los datos, no borrando
filas de una hoja. Los índices DTF, DTE e IB3 se descartan por estar fuera de alcance.</p>
<div class="embudos" id="embudos"></div>
</section>

<section id="tes"><p class="eyebrow">Título a título</p><h2>TES</h2>
<p class="lede">Referencias de Nación a tasa fija presentes en las dos fechas. Tabla
descriptiva: condiciones faciales, plazo, duración, precio y valoración con su
diferencia. La única medida derivada es el DV01. Quedan fuera los nemotécnicos de
relleno CINAS y TDS.</p>
<div class="card" id="tes-card"></div>
</section>

<section id="calidad"><p class="eyebrow">Control</p><h2>Calidad de datos</h2>
<p class="lede">Todo lo que el proceso anterior resolvía en silencio queda listado aquí.
Se muestran las observaciones de las dos fechas comparadas.</p>
{avisos}
<div id="calidad"></div>
</section>

</div>

<footer id="pie"></footer>
</div>
<script id="sx-datos" type="application/json">{payload}</script>
<script id="sx-calc">{JS_CALC}</script>
<script id="sx-ui">{JS}</script>
</body></html>"""
