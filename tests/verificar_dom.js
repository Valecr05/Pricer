// Carga el reporte en un DOM real (jsdom), lo interactúa y vuelca el estado como
// JSON. Sirve para detectar lo que una prueba de datos no ve: una excepción que
// corta el render, una gráfica que nunca se traza, un panel que no reacciona.
//
//   node tests/verificar_dom.js reporte.html
//
// Requiere jsdom:  npm install jsdom
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');

// jsdom no implementa scrollTo ni hace layout; ese ruido no es un error del reporte.
const RUIDO = [/scrollTo/i, /Could not parse CSS/i, /replaceState/i, /targetURL/i];
const errores = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => {
  const t = String(e && e.message || e);
  if (!RUIDO.some((r) => r.test(t))) errores.push(t);
});
vc.on('error', (...a) => errores.push(a.join(' ')));

const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'), {
  runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc
});
const { window } = dom;
const doc = window.document;

// Sin layout, clientWidth es 0 y las gráficas no sabrían qué ancho usar.
for (const p of ['clientWidth', 'offsetWidth']) {
  Object.defineProperty(window.Element.prototype, p, { get: () => 1200, configurable: true });
}
for (const p of ['clientHeight', 'offsetHeight']) {
  Object.defineProperty(window.Element.prototype, p, { get: () => 300, configurable: true });
}

const $ = (id) => doc.getElementById(id);
const grafica = (id) => {
  const el = $(id);
  if (!el) return { existe: false };
  // las barras de diferencia van pegadas: cada una llega hasta el punto medio con
  // su vecina, asi que entre el borde derecho de una y el izquierdo de la siguiente
  // no debe quedar hueco
  const rects = [...el.querySelectorAll('rect')]
    .map((r) => ({ x: +r.getAttribute('x'), w: +r.getAttribute('width') }))
    .sort((a, b) => a.x - b.x);
  let huecos = 0;
  for (let i = 1; i < rects.length; i++) {
    if (Math.abs((rects[i - 1].x + rects[i - 1].w) - rects[i].x) > 0.15) huecos++;
  }
  const textos = [...el.querySelectorAll('text')].map((t) => t.textContent);
  const ejeD = [...el.querySelectorAll('text.ejed')].map((t) => t.textContent);
  return { existe: true, svg: el.querySelectorAll('svg').length,
           series: el.querySelectorAll('path').length,
           puntos: el.querySelectorAll('circle').length,
           barras: rects.length, huecosEntreBarras: huecos,
           ejeDelta: ejeD,
           rotuloDelta: textos.includes('\u0394 pb') };
};
const estado = () => ({
  panelVisible: ['panel-curvas', 'panel-datos'].filter((p) => !$(p).hidden),
  pestanaActiva: ['tab-curvas', 'tab-datos']
    .filter((t) => $(t).getAttribute('aria-selected') === 'true'),
  graficasBloque: [...doc.querySelectorAll('#bloques .chart')].map((el) => ({
    id: el.id, svg: el.querySelectorAll('svg').length,
    series: el.querySelectorAll('path').length
  })),
  tes: grafica('ch-tes'),
  filasTes: doc.querySelectorAll('#tes-card tbody tr').length,
  tablasBloque: doc.querySelectorAll('#bloques table').length,
  notas: doc.querySelectorAll('#bloques .nota-tabla').length,
  tiles: doc.querySelectorAll('#resumen-tiles .tile').length,
  camposCinta: doc.querySelectorAll('#cinta-in .campo').length,
  embudos: doc.querySelectorAll('#embudos .embudo').length,
  avisos: doc.querySelectorAll('#calidad .issue').length,
  fechasEnSelect: $('sel-t').options.length,
  titulo: doc.title
});

const disparar = (id, tipo) => {
  const ev = new window.Event(tipo, { bubbles: true });
  $(id).dispatchEvent(ev);
};
// Margen real de las dos fechas en el primer nodo del bloque IPC. En vez de fijar
// índices de columna, que se mueven al añadir columnas, se localizan por el grupo
// del encabezado: las tres celdas bajo «Margen real».
const margenesIpc = () => {
  const tabla = doc.querySelector('#idx-ipc table');
  if (!tabla) return null;
  let col = 0, inicio = null;
  for (const th of tabla.querySelectorAll('thead tr:first-child th')) {
    const ancho = parseInt(th.getAttribute('colspan') || '1', 10);
    if (/Margen real/.test(th.textContent)) { inicio = col; break; }
    col += ancho;
  }
  if (inicio === null) return null;
  const c = tabla.querySelector('tbody tr').children;
  return { t1: c[inicio].textContent.trim(), t: c[inicio + 1].textContent.trim(),
           delta: c[inicio + 2].textContent.trim() };
};

const salida = { alCargar: estado(), errores: [] };

$('tab-datos').click();
salida.trasAbrirDatos = estado();

$('tab-curvas').click();
salida.trasVolverACurvas = estado();

salida.margenAntes = margenesIpc();
$('ipc-t').value = '9.00';
disparar('ipc-t', 'input');
salida.margenTrasIpcT = margenesIpc();
$('ipc-t1').value = '3.00';
disparar('ipc-t1', 'input');
salida.margenTrasIpcT1 = margenesIpc();

// Un par inválido (T-1 igual o posterior a T) debe avisarse y no comprometerse.
$('sel-t1').value = $('sel-t').value;
disparar('sel-t1', 'change');
salida.parInvalido = { aviso: $('aviso-orden').textContent.trim(),
                       t1: $('sel-t1').value, t: $('sel-t').value };

const otra = [...$('sel-t1').options].map((o) => o.value)
  .filter((v) => v < $('sel-t').value).sort().reverse()[1] || $('sel-t1').value;
$('sel-t1').value = otra;
disparar('sel-t1', 'change');
// Rehacer las tablas destruye el SVG de la pestaña que no está visible; la
// invariante que importa es que al abrirla se vuelva a trazar.
salida.trasCambiarFecha = { t1: otra, estado: estado() };
$('tab-datos').click();
salida.trasCambiarFechaYAbrirDatos = estado();

// --- conmutadores de serie: IPC (Tasa / Margen real) e IBR (TIR / Margen) ---
// Acotado a los bloques: la pestaña de rentabilidades usa la misma clase de botón.
const conMargen = [...doc.querySelectorAll('#bloques .tg')]
  .filter((b) => !b.disabled || b.dataset.serie === 'margen');
salida.conmutadores = {
  botones: conMargen.length,
  graficas: [...new Set(conMargen.map((b) => b.dataset.gr))],
  etiquetas: [...new Set(conMargen.map((b) => b.textContent.trim()))],
  // el conmutador nunca se esconde: sin margen queda visible y deshabilitado
  deshabilitados: conMargen.filter((b) => b.disabled).length,
  conTitulo: conMargen.filter((b) => b.disabled && b.getAttribute('title')).length
};
// Cada bloque abre en su propia serie, asi que se recorre en el orden en que el
// conmutador la cambia: primero la que trae por defecto y luego la otra.
const conmutar = (gid, desde, hacia) => {
  const puntos = () => grafica(gid).puntos;
  const yLabel = () => {
    const t = [...$(gid).querySelectorAll('text')].map((e) => e.textContent);
    return t.find((x) => /Tasa|Margen/i.test(x)) || null;
  };
  const pulsar = (serie) => doc.querySelector(`.tg[data-gr="${gid}"][data-serie="${serie}"]`);
  const out = { id: gid, porDefectoEje: yLabel(), porDefectoPuntos: puntos(),
                pressedPorDefecto: pulsar(desde).getAttribute('aria-pressed') };
  pulsar(hacia).click();
  out.otraEje = yLabel();
  out.otraPuntos = puntos();
  out.pressedOtra = pulsar(hacia).getAttribute('aria-pressed');
  pulsar(desde).click();                 // y vuelve a la de por defecto
  out.vuelvePuntos = puntos();
  out.vuelveEje = yLabel();
  return out;
};
const primera = (prefijo) => (conMargen.find((b) => b.dataset.gr.startsWith(prefijo)) || {})
  .dataset?.gr || null;
const gidIbr = primera('ch-ibr-'), gidIpc = primera('ch-ipc-');
// IBR abre en la tasa y conmuta al margen del atajo; IPC al reves
if (gidIbr) salida.grafica = conmutar(gidIbr, 'tir', 'margen');
if (gidIpc) salida.graficaIpc = conmutar(gidIpc, 'margen', 'tir');

// --- columnas de margen y celdas «sin curva» ---
const filaIbr = doc.querySelector('#idx-ibr table tbody tr');
salida.tablaIbr = {
  celdas: filaIbr ? filaIbr.children.length : 0,
  encabezados: [...doc.querySelectorAll('#idx-ibr table thead th.grupo')].map((e) => e.textContent.trim()),
  sinCurva: doc.querySelectorAll('#idx-ibr td.sincurva').length,
  notas: [...doc.querySelectorAll('#idx-ibr .nota-tabla')].map((e) => e.textContent.trim().slice(0, 220))
};
const filaIpc = doc.querySelector('#idx-ipc table tbody tr');
salida.tablaIpc = {
  celdas: filaIpc ? filaIpc.children.length : 0,
  encabezados: [...doc.querySelectorAll('#idx-ipc table thead th.grupo')].map((e) => e.textContent.trim())
};
const filaFs = doc.querySelector('#idx-fs table tbody tr');
salida.tablaFs = { celdas: filaFs ? filaFs.children.length : 0,
  sinCurva: doc.querySelectorAll('#idx-fs td.sincurva').length,
  conmutadores: doc.querySelectorAll('#idx-fs .tg').length };

// --- pestaña de rentabilidades esperadas ---
$('tab-hpr').click();
const leerHpr = () => ({
  panel: !$('panel-hpr').hidden,
  tablas: doc.querySelectorAll('#hpr-tablas table').length,
  titulos: [...doc.querySelectorAll('#hpr-tablas .card-hd h3')].map((e) => e.textContent.trim()),
  filas: doc.querySelectorAll('#hpr-tablas table tbody tr').length,
  celdasAlVenc: doc.querySelectorAll('#hpr-tablas td.alvenc').length,
  extrap: doc.querySelectorAll('#hpr-tablas .extrap').length,
  notas: doc.querySelectorAll('#hpr-tablas .nota-tabla').length,
  primera: [...(doc.querySelector('#hpr-tablas table tbody tr') || { children: [] }).children]
    .map((td) => td.textContent.trim()),
  hpr90: [...doc.querySelectorAll('#hpr-tablas table')][0]
    ? [...doc.querySelectorAll('#hpr-tablas table')[0].querySelectorAll('tbody tr')]
        .slice(0, 4).map((tr) => tr.children[7].textContent.trim()) : [],
  escenarioActivo: [...doc.querySelectorAll('[data-hpr-esc]')]
    .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.hprEsc),
  escDeshabilitados: [...doc.querySelectorAll('[data-hpr-esc]')].filter((b) => b.disabled).length,
  tipoActivo: [...doc.querySelectorAll('[data-hpr-tipo]')]
    .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.hprTipo)
});
salida.hprTF = leerHpr();

// Los controles de escenario solo existen si se cargaron las sendas de proyección;
// sin ellas la pestaña avisa y no calcula nada, que es un modo de uso válido.
const clic = (sel) => { const b = doc.querySelector(sel); if (b) b.click(); return !!b; };
salida.conEscenarios = !!doc.querySelector('[data-hpr-esc]');

if (salida.conEscenarios) {
  clic('[data-hpr-esc="Alcista"]');            // la tasa fija no debe moverse
  salida.hprTFAlcista = leerHpr().hpr90;

  clic('[data-hpr-tipo="ipc"]');
  salida.hprIPCBase = leerHpr();
  clic('[data-hpr-esc="Bajista"]');
  salida.hprIPCBajista = leerHpr().hpr90;
  clic('[data-hpr-esc="Base"]');

  $('hpr-delta').value = '100';                // el delta mueve el resultado
  disparar('hpr-delta', 'input');
  salida.hprIPCDelta = leerHpr().hpr90;
  $('hpr-delta').value = '0';
  disparar('hpr-delta', 'input');

  clic('[data-hpr-tipo="ibr"]');
  salida.hprIBR = leerHpr();
} else {
  clic('[data-hpr-tipo="ipc"]');
  salida.hprSinSendas = {
    tablas: doc.querySelectorAll('#hpr-tablas table').length,
    aviso: (doc.querySelector('#hpr-tablas .issue') || {}).textContent || ''
  };
}

// --- botones de descarga a Excel: uno por tabla, y ninguno suelto ---
salida.excel = {};
for (const [clave, panel] of [['curvas', 'panel-curvas'], ['hpr', 'panel-hpr'],
                              ['datos', 'panel-datos']]) {
  const p = $(panel);
  salida.excel[clave] = {
    botones: p.querySelectorAll('button.xls').length,
    tablas: p.querySelectorAll('.card table').length,
    // cada boton tiene que estar dentro de una tarjeta que traiga tabla, y ser el
    // ultimo hijo de la cabecera para quedar en la esquina
    bienColocados: Array.from(p.querySelectorAll('button.xls')).filter((b) => {
      const card = b.closest('.card');
      return card && card.querySelector('table') &&
             b.parentNode.classList.contains('card-hd') &&
             b.parentNode.lastElementChild === b &&
             (b.getAttribute('data-xls') || '').length > 0;
    }).length
  };
}
// nombres distintos: si dos tablas comparten nombre, los archivos se pisan
salida.excel.nombres = Array.from(doc.querySelectorAll('button.xls'))
  .map((b) => b.getAttribute('data-xls'));

// --- barras de diferencia en las graficas de bloque ---
salida.barras = {};
for (const gid of ['ch-fs-CDT', 'ch-ipc-CDT', 'ch-ibr-CDT']) {
  salida.barras[gid] = grafica(gid);
}
salida.barrasTes = grafica('ch-tes').barras;

salida.errores = errores;
process.stdout.write(JSON.stringify(salida, null, 1));
