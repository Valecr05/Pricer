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
  // Cada barra de diferencia llega hasta el punto medio con su vecina y se le
  // descuentan 2 px de aire: entre el borde derecho de una y el izquierdo de la
  // siguiente queda siempre esa misma separacion, ni mas ni menos.
  const rects = [...el.querySelectorAll('rect')]
    .map((r) => ({ x: +r.getAttribute('x'), w: +r.getAttribute('width') }))
    .sort((a, b) => a.x - b.x);
  const separaciones = new Set();
  for (let i = 1; i < rects.length; i++) {
    separaciones.add(((rects[i].x - (rects[i - 1].x + rects[i - 1].w))).toFixed(1));
  }
  const textos = [...el.querySelectorAll('text')].map((t) => t.textContent);
  const ejeD = [...el.querySelectorAll('text.ejed')].map((t) => t.textContent);
  return { existe: true, svg: el.querySelectorAll('svg').length,
           series: el.querySelectorAll('path').length,
           puntos: el.querySelectorAll('circle').length,
           barras: rects.length, separaciones: [...separaciones],
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
  // el selector de vista: un boton por bloque y uno por familia del bloque visible
  vistas: [...doc.querySelectorAll('#bloques .tg[data-vista]')]
    .map((b) => b.dataset.vista + ':' + b.dataset.val),
  vistaActiva: [...doc.querySelectorAll('#bloques .tg[data-vista][aria-pressed="true"]')]
    .map((b) => b.dataset.vista + ':' + b.dataset.val),
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

// El panel de curvas muestra UN bloque a la vez; para llegar a los demas hay que
// pulsar su boton de vista. Antes los nueve estaban apilados y bastaba con leerlos.
const verBloque = (id) => {
  const b = doc.querySelector(`#bloques .tg[data-vista="bloque"][data-val="${id}"]`);
  if (b) b.click();
  return !!b;
};
const verFamilia = (f) => {
  const b = doc.querySelector(`#bloques .tg[data-vista="familia"][data-val="${f}"]`);
  if (b) b.click();
  return !!b;
};

const salida = { alCargar: estado(), errores: [] };

// Si el reporte lanza una excepcion al cargar, todo lo que sigue —pulsar una
// pestania, cambiar de bloque— falla en cadena contra un DOM a medio construir. El
// volcado tiene que salir igual: la lista de `errores` es justo el diagnostico que
// hace falta, y un stack de jsdom en su lugar no dice nada.
try {
  $('tab-datos').click();
  salida.trasAbrirDatos = estado();

  $('tab-curvas').click();
  salida.trasVolverACurvas = estado();

  verBloque('ipc');
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
  // Solo hay un bloque a la vista, asi que se recorren pulsando su boton de vista.
  // El filtro por `data-serie` es lo que separa el conmutador de serie del selector
  // de vista, que comparte la clase `.tg`.
  $('tab-curvas').click();
  const conmutadoresDe = (bloque) => {
    verBloque(bloque);
    return [...doc.querySelectorAll('#bloques .tg[data-serie]')];
  };
  const todosLosConmutadores = [];
  for (const b of ['fs', 'ipc', 'ibr']) todosLosConmutadores.push(...conmutadoresDe(b));
  salida.conmutadores = {
    botones: todosLosConmutadores.length,
    graficas: [...new Set(todosLosConmutadores.map((b) => b.dataset.gr))],
    etiquetas: [...new Set(todosLosConmutadores.map((b) => b.textContent.trim()))],
    // el conmutador nunca se esconde: sin margen queda visible y deshabilitado
    deshabilitados: todosLosConmutadores.filter((b) => b.disabled).length,
    conTitulo: todosLosConmutadores.filter((b) => b.disabled && b.getAttribute('title')).length
  };

  // Cada bloque abre en su propia serie, asi que se recorre en el orden en que el
  // conmutador la cambia: primero la que trae por defecto y luego la otra.
  const conmutar = (bloque, desde, hacia) => {
    verBloque(bloque);
    const gr = doc.querySelector('#bloques .tg[data-serie]');
    if (!gr) return null;
    const gid = gr.dataset.gr;
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
  // IBR abre en la tasa y conmuta al margen del atajo; IPC al reves
  salida.grafica = conmutar('ibr', 'tir', 'margen');
  salida.graficaIpc = conmutar('ipc', 'margen', 'tir');

  // --- columnas de margen y celdas «sin curva» ---
  const leerTablaBloque = (bloque) => {
    verBloque(bloque);
    const sec = `#idx-${bloque}`;
    const fila = doc.querySelector(`${sec} table tbody tr`);
    return {
      celdas: fila ? fila.children.length : 0,
      encabezados: [...doc.querySelectorAll(`${sec} table thead th.grupo`)]
        .map((e) => e.textContent.trim()),
      sinCurva: doc.querySelectorAll(`${sec} td.sincurva`).length,
      conmutadores: doc.querySelectorAll(`${sec} .tg[data-serie]`).length,
      notas: [...doc.querySelectorAll(`${sec} .nota-tabla`)]
        .map((e) => e.textContent.trim().slice(0, 220))
    };
  };
  salida.tablaIbr = leerTablaBloque('ibr');
  salida.tablaIpc = leerTablaBloque('ipc');
  salida.tablaFs = leerTablaBloque('fs');
  // Las familias del bloque visible se pueden recorrer sin romper nada.
  salida.familias = { botones: estado().vistas.filter((v) => v.startsWith('familia:')),
                      activa: estado().vistaActiva.filter((v) => v.startsWith('familia:')) };
  const otraFamilia = salida.familias.botones
    .find((v) => !salida.familias.activa.includes(v));
  if (otraFamilia) {
    verFamilia(otraFamilia.split(':')[1]);
    salida.trasCambiarFamilia = estado();
  }

  // --- pestaña de rentabilidades esperadas ---
  $('tab-hpr').click();
  // El panel trae dos tablas: «Resumen», con los indicadores en las filas y cinco
  // plazos en las columnas, y «Detalle de rentabilidades», con un rango por fila y un
  // horizonte a la vez. La columna de HPR del detalle es la ultima.
  const detalle = () => doc.querySelectorAll('#hpr-tablas table')[1] || null;
  const resumen = () => doc.querySelectorAll('#hpr-tablas table')[0] || null;
  const filaResumen = (etiqueta) => {
    const t = resumen();
    if (!t) return [];
    const tr = [...t.querySelectorAll('tbody tr')]
      .find((f) => f.children[0].textContent.trim() === etiqueta);
    return tr ? [...tr.children].slice(1).map((td) => td.textContent.trim()) : [];
  };
  const leerHpr = () => ({
    panel: !$('panel-hpr').hidden,
    tablas: doc.querySelectorAll('#hpr-tablas table').length,
    titulos: [...doc.querySelectorAll('#hpr-tablas .card-hd h3')].map((e) => e.textContent.trim()),
    filas: detalle() ? detalle().querySelectorAll('tbody tr').length : 0,
    filasResumen: resumen() ? resumen().querySelectorAll('tbody tr').length : 0,
    columnasResumen: resumen()
      ? [...resumen().querySelectorAll('thead th')].map((e) => e.textContent.trim()) : [],
    celdasAlVenc: doc.querySelectorAll('#hpr-tablas td.alvenc').length,
    extrap: doc.querySelectorAll('#hpr-tablas .extrap').length,
    notas: doc.querySelectorAll('#hpr-tablas .nota-tabla').length,
    horizonteActivo: [...doc.querySelectorAll('[data-hpr-h]')]
      .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.hprH),
    horizontes: [...doc.querySelectorAll('[data-hpr-h]')].map((b) => b.textContent.trim()),
    primera: [...(detalle() ? detalle().querySelector('tbody tr') : { children: [] }).children]
      .map((td) => td.textContent.trim()),
    // las cuatro primeras rentabilidades del detalle, en el horizonte que este activo
    hpr90: detalle()
      ? [...detalle().querySelectorAll('tbody tr')].slice(0, 4)
          .map((tr) => tr.children[tr.children.length - 1].textContent.trim()) : [],
    // y la fila de 90 dias del resumen, que no depende del horizonte activo
    resumen90: filaResumen('Rentabilidad 90 días'),
    escenarioActivo: [...doc.querySelectorAll('[data-hpr-esc]')]
      .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.hprEsc),
    escDeshabilitados: [...doc.querySelectorAll('[data-hpr-esc]')].filter((b) => b.disabled).length,
    tipoActivo: [...doc.querySelectorAll('[data-hpr-tipo]')]
      .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.hprTipo)
  });
  salida.hprTF = leerHpr();
  // Los botones de horizonte cambian el detalle sin tocar el resumen.
  salida.porHorizonte = [0, 1, 2].map((i) => {
    const b = doc.querySelector(`[data-hpr-h="${i}"]`);
    if (b) b.click();
    const h = leerHpr();
    return { i, activo: h.horizonteActivo, hpr: h.hpr90, resumen90: h.resumen90 };
  });
  doc.querySelector('[data-hpr-h="0"]').click();       // y se deja como estaba

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
  // Una gráfica por bloque, y hay que traer cada bloque a la vista para medirla.
  $('tab-curvas').click();
  salida.barras = {};
  for (const bloque of ['fs', 'ipc', 'ibr']) {
    verBloque(bloque);
    verFamilia('CDT');
    salida.barras['ch-' + bloque + '-CDT'] = grafica('ch-' + bloque + '-CDT');
  }
  salida.barrasTes = grafica('ch-tes').barras;
} catch (e) {
  salida.abortado = String(e && e.stack || e);
}

salida.errores = errores;
process.stdout.write(JSON.stringify(salida, null, 1));
