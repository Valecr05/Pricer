// Extrae la capa de cálculo del reporte y vuelca sus tablas como JSON, para poder
// comparar en la suite de pruebas lo que hace el navegador contra lo que hace Python.
//
//   node tests/verificar_js.js reporte.html 2026-07-28 2026-07-27 0.0614 0.0614
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const trozo = (id) =>
  html.match(new RegExp('<script id="' + id + '"[^>]*>([\\s\\S]*?)</script>'))[1];

const D = JSON.parse(trozo('sx-datos').replace(/<\\\//g, '</'));
const lib = eval(trozo('sx-calc') + '; SX');

const [, , , t, t1, ipcT, ipcT1] = process.argv;
const rt = D.porFecha[t], rt1 = D.porFecha[t1];
if (!rt || !rt1) { throw new Error('fecha no presente en el reporte'); }

const salida = {
  fechas: D.fechas,
  buckets: D.buckets,
  bloques: {},
  tes: lib.tes(D, rt, rt1),
  muestra: {},
  formato: {
    miles: lib.fmt(1234567.891, 2),
    pct: lib.pct(0.116598, 3),
    bpsNeg: lib.bps(-4.25),
    bpsPos: lib.bps(7.9),
    vacio: lib.fmt(null, 2),
    claseNeg: lib.clase(-1),
    claseCero: lib.clase(0.01),
    claseNula: lib.clase(null)
  }
};
D.bloques.forEach((b) => b.familias.forEach((fam) => {
  const clave = b.id + '|' + fam;
  const filas = lib.nodos(D, rt, rt1, b.id, fam, +ipcT, +ipcT1);
  salida.bloques[clave] = filas;
  salida.muestra[clave] = lib.muestraCorta(filas, D.config.minTitulos);
}));
process.stdout.write(JSON.stringify(salida));
