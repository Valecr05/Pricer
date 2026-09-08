// Ejercita el exportador a Excel del reporte sobre una tabla de prueba y escribe el
// .xlsx resultante, para que la prueba de Python lo abra con openpyxl.
//
//   node tests/verificar_xls.js salida.xlsx
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const py = fs.readFileSync(path.join(__dirname, '..', 'sx_pricer', 'report.py'), 'utf8');
const ui = py.split('JS = r"""')[1].split('\n"""')[0];
const expo = ui.slice(ui.indexOf('// ---------- exportar una tabla a Excel'),
                      ui.indexOf('function cablearPestanas(){'));

// Una tabla con todo lo que el lector tiene que saber deshacer: cabecera de grupos
// con colspan, porcentajes, punto de miles, negativos, el punto medio de «sin dato»,
// la marca de extrapolacion, el «(al venc.)» y texto con caracteres de XML.
const dom = new JSDOM(`<!doctype html><body>
<div class="card"><div class="card-hd"><h3>IPC · CDT</h3>
<span class="meta">12 nodos</span>
<button type="button" class="xls" data-xls="IPC CDT">Excel</button></div>
<div class="tw"><table>
<thead>
<tr><th class="grupo" colspan="2">Ventana</th><th class="grupo" colspan="2">Tasa</th></tr>
<tr><th>Desde</th><th>Hasta</th><th>T-1</th><th>T</th></tr>
</thead>
<tbody>
<tr><td>2026-08-28</td><td>2026-09-27</td><td>11,070 %</td><td>11,235 %</td></tr>
<tr><td>2026-09-28</td><td>2026-10-27</td><td>·</td><td>12,800 %<span class="extrap">*</span></td></tr>
<tr><td>2026-10-28</td><td>2026-11-27</td><td>1.234,567</td><td>-0,500 %<small>(al venc.)</small></td></tr>
<tr><td>TFIT16&lt;240724&gt;</td><td>"comillas" &amp; ampersand</td><td>+12,3</td><td>0</td></tr>
</tbody></table></div></div>`, { url: 'http://localhost/' });

global.window = dom.window;
global.document = dom.window.document;
global.Blob = dom.window.Blob;
global.URL = dom.window.URL;
global.TextEncoder = TextEncoder;
const SX = { VACIO: '·' };
const S = { t: '2026-07-28' };
function esc(s){ const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

let blob = null, nombre = null;
eval(expo);
descargar = function(b, n){ blob = b; nombre = n; };
cablearDescargas();
document.querySelector('.xls').click();

if(!blob) { console.error('el boton no genero ningun archivo'); process.exit(1); }
blob.arrayBuffer().then(buf => {
  fs.writeFileSync(process.argv[2], Buffer.from(buf));
  process.stdout.write(JSON.stringify({ nombre: nombre, bytes: buf.byteLength }));
});
