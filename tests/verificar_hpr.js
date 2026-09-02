// Ejecuta la capa de cálculo del reporte para la pestaña de rentabilidades
// esperadas y vuelca los resultados, para compararlos contra hpr.py.
//
//   node tests/verificar_hpr.js reporte.html 2026-07-28
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const trozo = (id) => html.match(new RegExp('<script id="' + id + '"[^>]*>([\\s\\S]*?)</script>'))[1];
const D = JSON.parse(trozo('sx-datos').replace(/<\\\//g, '</'));
const lib = eval(trozo('sx-calc') + '; SX');
const T = process.argv[3], salida = {};
for (const tipo of ['fs', 'ipc', 'ibr']) {
  const rt = D.porFecha[T];
  const nodos = lib.nodos(D, rt, rt, tipo, 'CDT', 0.0614, 0.0614);
  const senda = (tipo === 'fs' || !D.escenarios) ? null : D.escenarios.sendas[D.hpr.indice[tipo]];
  for (const esc of ['Alcista', 'Base', 'Bajista']) {
    for (const delta of [0, 50, -75]) {
      const idxHoy = senda ? lib.vigente(senda, T, esc)[0] : 0;
      salida[[tipo, esc, delta]] = nodos.map((r, i) => {
        const bruta = rt.nodos[tipo + '|CDT'].bruta[i];
        const mg = rt.nodos[tipo + '|CDT'].margen;
        if (bruta === null || r.cuponT === null) return null;
        let m = 0;
        if (tipo === 'ipc') m = (1 + bruta) / (1 + idxHoy) - 1;
        else if (tipo === 'ibr') { m = mg ? mg[i] : null; if (m === null) return null; }
        const venc = lib.sumarDias(r.hastaT, -1);
        const res = lib.rentabilidad(D, { tipo, fechaVal: T, vencimiento: venc, tir: bruta,
          cupon: r.cuponT / 100, margen: m, escenario: esc, deltaPb: delta });
        if (!res) return null;
        return { venc, margen: m, res: res.map(x => ({ h: x.horizonte, dias: x.dias,
          hpr: x.hpr, v0: x.v0, v1: x.v1, te: x.tasaEntrada, ts: x.tasaSalida,
          cup: x.cupones, av: x.alVencimiento, ex: x.extrapolado })) };
      });
    }
  }
}
process.stdout.write(JSON.stringify(salida));
