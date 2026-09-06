# sx-pricer

Reemplaza el libro `Local_Fixed_Income___FX_Pricer.xlsm`. Procesa una serie de planos
SX —un día, un trimestre, un año— y emite un reporte HTML autocontenido donde **el par
de fechas a comparar se elige en pantalla**, junto con el IPC de cada fecha y la tasa
del Banco de la República.

Unos **6 segundos por archivo**, y solo la primera vez: los resúmenes quedan en caché,
así que sumar el plano de hoy a un año de historia cuesta una sola lectura. El libro de
Excel de 122 MB tardaba varios minutos en comparar dos fechas.

---

## Instalación

Necesita numpy, pandas y openpyxl (este último para la senda histórica de IBR).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Puesta en marcha en Windows, paso a paso

**1. Instalar Python.** Descárgalo de [python.org/downloads](https://www.python.org/downloads/)
—versión 3.10 o posterior— y en el instalador **marca «Add python.exe to PATH»** antes de
darle a Instalar. Para comprobar que quedó, abre el menú Inicio, escribe `cmd`, y en la
ventana negra escribe:

```
py --version
```

Debe responder algo como `Python 3.12.4`.

**2. Descomprimir la herramienta.** Descomprime `sx-pricer.zip` donde vayas a dejarla, por
ejemplo `C:\sx-pricer`. Dentro deben quedar la carpeta `sx_pricer`, `params.json`,
`requirements.txt`, `correr.bat` y `mis_rutas.ejemplo.bat`.

Si ya tenías una versión anterior, **conserva tu `mis_rutas.bat`**: es el único archivo con
tu configuración.

**3. Crear el entorno e instalar las librerías.** Una sola vez. En la ventana de comandos:

```
cd C:\sx-pricer
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

La última línea descarga numpy, pandas y openpyxl. Tarda un par de minutos.

**4. Organizar los archivos de entrada.** Dos carpetas, donde te sea cómodo:

| Carpeta | Qué va dentro |
|---|---|
| Planos | los `.001` de Precia, con el nombre que traigan |
| Curvas | los `IND_IBR_AAAAMMDD.txt`, más `IB1.xlsx` y `Escenarios_IPC-IBR_VC.xlsx` |

**5. Ajustar los parámetros.** Abre `params.json` con el Bloc de notas y pon el IPC de
referencia y la tasa del Banco de la República del día. Todo en decimal: `0.0614`, no
`6.14`.

**6. Poner tus rutas.** Copia `mis_rutas.ejemplo.bat`, renombra la copia a
`mis_rutas.bat`, ábrela con el Bloc de notas y pon tus tres carpetas. `SALIDA` tiene que
ser la ruta de un **archivo** que termine en `.html`, no una carpeta.

`mis_rutas.bat` es el único archivo que editas, y **las actualizaciones no lo incluyen**:
así tus rutas no se pierden cuando reemplaces la carpeta por una versión nueva. A
`correr.bat` no hay que tocarlo.

**7. Correr.** Doble clic en `correr.bat`. La primera vez procesa todos los planos que
encuentre —unos seis segundos por archivo— y de ahí en adelante solo el nuevo. Al terminar
abre el reporte en el navegador.

### Limpiar el caché y reprocesar todo desde cero

Dos formas:

- **Borrar la carpeta.** Por defecto es `.sx-cache`, dentro de la carpeta de la
  herramienta. Bórrala (a mano, o `rmdir /s /q .sx-cache`) y la próxima corrida
  reprocesa todo.
- **`--rehacer`**, sin borrar nada: ignora el caché existente y reprocesa cada plano.
  Doble clic en `rehacer_todo.bat` hace esto con tus rutas de `mis_rutas.bat`.

Conviene forzarlo, por ejemplo, después de agregar curvas `IND_IBR` que faltaban, para
confirmar que ya se están usando en vez de fiarte del resumen guardado.

### Cómo saber qué curvas está viendo

Al arrancar, la ventana negra lista las curvas encontradas y las que ignoró:

```
curvas IBR: 3 archivo(s) · 2026-07-26, 2026-07-27, 2026-07-28
curvas IBR: estos archivos se IGNORARON:
    IND IBR_20260624.txt        ->  el nombre no encaja con IND_IBR_AAAAMMDD.txt
    IND_IBR_20260531 (1).txt    ->  el nombre no encaja con IND_IBR_AAAAMMDD.txt
    IND_IBR_24062026.txt        ->  «24062026» no es una fecha AAAAMMDD
```

Y por cada plano dice con qué curva calculó el margen:

```
SX 20260728.001 -> 2026-07-28 (294.034 títulos, 7,4 s) · margen con la curva del 2026-07-27
```

Un espacio en lugar del guion bajo, el `(1)` que agrega el navegador al descargar dos
veces, o la fecha en formato `ddmmaaaa` bastan para que un archivo se ignore. Esa lista
los saca a la luz en vez de dejarlos pasar en silencio.

### El día a día

Cada mañana: dejas el plano nuevo en la carpeta de planos y su `IND_IBR` en la de curvas,
y doble clic en `correr.bat`. Nada más.

### Si algo sale mal

La ventana negra no se cierra: ahí queda el mensaje. Los casos frecuentes:

| Mensaje | Qué pasó |
|---|---|
| `No encuentro "mis_rutas.bat"` | falta el paso 6 |
| `No encuentro el entorno virtual` | falta el paso 3 |
| `SALIDA tiene que ser la ruta de un ARCHIVO` | en `mis_rutas.bat` pusiste una carpeta y no un `.html` |
| `No existe la carpeta de planos` | la ruta de `mis_rutas.bat` está mal escrita |
| `Sin coincidencias para ...` | la ruta de planos del `.bat` está mal escrita |
| `sin margen IBR: ...` | falta la curva del día hábil anterior a esa fecha; el resto del reporte sale igual |
| `estos archivos se IGNORARON` | hay `.txt` en la carpeta de curvas cuyo nombre no encaja con `IND_IBR_AAAAMMDD.txt`; la ventana dice cuáles y por qué |
| `controles de integridad fallidos` | un plano llegó truncado o incompleto; el reporte dice cuál y en qué control |
| `Se necesitan al menos dos fechas` | solo hay un plano procesado |

### En macOS o Linux

Los mismos pasos, cambiando `py` por `python3` y `.venv\Scripts\` por `.venv/bin/`:

```bash
cd ~/sx-pricer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m sx_pricer --archivos "planos/SX*.001" --curvas curvas \
                              --params params.json -o reporte.html
```

## Uso

```bash
python -m sx_pricer \
    --archivos "Z:/CEI/Fiduciaria/Precios/Archivos Planos/SX*.001" \
    --params params.json \
    -o reporte.html
```

Procesa todos los planos que encuentre y emite **un solo reporte con toda la serie
embebida**. El par de fechas a comparar se elige dentro del reporte, en dos listas
desplegables; `--t` y `--t1` solo fijan con qué par abre.

Los archivos ya no tienen que llamarse `SX T.001` y `SX T-1.001`, y pueden estar en
cualquier orden: la fecha se lee del propio archivo.

### La primera corrida y las siguientes

Cada plano se reduce una sola vez a un resumen de unos 5 KB que queda en la carpeta de
caché (`.sx-cache` por defecto). Procesar un año de historia toma unos veinte minutos;
agregarle el plano de hoy toma seis segundos, porque los demás se reutilizan.

```bash
# día a día: agrega el plano nuevo y reutiliza el resto
python -m sx_pricer --archivos "Archivos Planos/SX*.001" --curvas "Curvas IBR" \
                    --params params.json -o reporte.html

# armar el reporte sin volver a tocar los planos
python -m sx_pricer --solo-cache --params params.json -o reporte.html

# abrir comparando el cierre de junio contra ayer
python -m sx_pricer --solo-cache --params params.json --t 2026-07-28 --t1 2026-06-30 -o reporte.html
```

El caché se invalida por sí solo. Cada resumen recuerda el nombre, el tamaño y la fecha
de modificación del archivo que lo produjo, **y también la huella de los insumos de IBR
de esa fecha** —el archivo de curva que se usó y los dos meses de senda histórica que el
margen llega a consultar—: si mañana agregas la curva de un día ya procesado, o corriges
un valor de la senda, se vuelve a procesar ese día y ninguno más.

| Opción | Qué hace |
|---|---|
| `--archivos` | planos SX; acepta comodines, por ejemplo `"Archivos Planos/SX*.001"` |
| `--params` | JSON con los parámetros de mercado |
| `-o` | ruta del reporte |
| `--t`, `--t1` | par con el que abre el reporte (por defecto, las dos últimas fechas) |
| `--cache` | carpeta de resúmenes (por defecto `.sx-cache`) |
| `--solo-cache` | armar el reporte sin leer planos |
| `--sin-cache` | no leer ni escribir caché |
| `--rehacer` | reprocesar todo, ignorando el caché |
| `--curvas CARPETA` | curvas `IND_IBR_AAAAMMDD.txt` y senda histórica `IB1.xlsx` |
| `--ibr-historico XLSX` | senda histórica en otra ruta (por defecto, `IB1.xlsx` dentro de `--curvas`) |
| `--escenarios XLSX` | sendas de proyección de IPC e IBR (por defecto, `Escenarios_IPC-IBR_VC.xlsx` dentro de `--curvas`) |
| `--procesos N` | procesar N archivos en paralelo |
| `--csv CARPETA` | exporta a CSV las tablas del par elegido |
| `--estricto` | aborta si un control de integridad falla |
| `--silencioso` | no imprime progreso |

`--procesos` ayuda si la máquina tiene varios núcleos; en uno solo no cambia nada,
porque el trabajo está limitado por el ancho de banda de memoria.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | todo bien |
| `1` | error de uso, ningún archivo procesable, o par de fechas inválido |
| `2` | el reporte se generó, pero hay controles de integridad fallidos |
| `3` | el reporte se generó, pero hay errores de calidad en el par elegido |

### Parámetros

```json
{
  "ipc_referencia": 0.0614,
  "tasa_br": 0.12,
  "ipc_por_fecha": {
    "2025-12-31": 0.0518,
    "2026-06-30": 0.0621,
    "2026-07-28": 0.0614
  },
  "nominal_dv01": 1000000000,
  "fuente": "DANE / Banco de la República",
  "capturado_por": "nombre de quien los capturó"
}
```

Todo en decimal, no en porcentaje.

- **`ipc_referencia`** es el único IPC que interviene en el procesamiento, y solo para
  calcular la duración al vencimiento de los indexados. Se usa uno solo para toda la
  serie porque la duración es muy poco sensible a él —mover el IPC de 6,14 % a 7 %
  cambia la duración de un bono a tres años en menos de 0,02 años— y porque así el
  caché no se invalida cada vez que el DANE publica.
- **`ipc_por_fecha`** es opcional y no entra en ningún cálculo: precarga los campos de
  IPC de la pantalla al elegir cada fecha. Si falta una fecha, se usa el de referencia.
- **`tasa_br`** se registra y se muestra, pero hoy no la consume ningún cálculo.
- `fuente` y `capturado_por` quedan impresos en el pie del reporte: es la trazabilidad
  que el Excel no tenía.

Los `params.json` escritos para la versión anterior (con `ipc_t`, `ipc_t1`,
`horizonte_dias`) siguen funcionando: `ipc_t` se toma como `ipc_referencia`, el resto se
ignora, y el reporte lo avisa en la sección de calidad.

---

## El par de fechas se elige en el reporte

La barra superior del HTML tiene dos listas de fechas, **T-1** y **T**, con todas las
que se hayan procesado. La comparación siempre es entre dos, como debe ser, pero cuál
par se compara se decide al momento y las tablas y gráficas se rehacen al instante.

También se editan ahí el **IPC de cada fecha** y la **tasa BanRep**. Al elegir una fecha,
su IPC se precarga desde `ipc_por_fecha`; cambiarlo recalcula el margen real de los nodos
indexados, su diferencia entre fechas, las gráficas de esos bloques y —desde que el HPR
toma ese mismo margen— las rentabilidades esperadas de IPC.

Que el recálculo sea exacto depende de una propiedad del margen real: es una función
**afín** de la tasa de valoración, así que aplicarla al promedio de las tasas de un nodo
da lo mismo que promediar los márgenes de sus títulos. Por eso el resumen de cada fecha
lleva la tasa bruta promedio de cada nodo y no hace falta volver a agrupar los 300.000
títulos.

Lo único que **no** se recalcula en pantalla es la duración de los indexados, que se
computa al procesar con `ipc_referencia`.

## La rejilla: ventanas mensuales de vencimiento

Los bloques ya no se cortan por buckets de plazo sino por **ventanas mensuales de
vencimiento**, la rejilla de la hoja `TF` del libro original. Cada paso suma los días
del mes en curso, de modo que los anclajes caen el mismo día de cada mes y la ventana
cruza dos meses de calendario:

| Fechas (T) | Rango | Δ D T | Día T | ventana |
|---|---|---|---|---|
| 21/08 a 20/09 | ago-26 | 31 | 0 | 2026-08-21 a 2026-09-20 |
| 21/09 a 20/10 | sep-26 | 30 | 31 | 2026-09-21 a 2026-10-20 |
| 21/10 a 20/11 | oct-26 | 31 | 61 | 2026-10-21 a 2026-11-20 |

La primera columna dice qué fechas está tomando cada renglón, porque la etiqueta del
mes por sí sola no lo revela.

**Cada fecha ancla su propia rejilla** en su fecha de valoración. Compartir la de T no
serviría: con el selector, T-1 puede ser el cierre de un trimestre, y entonces la
primera ventana de T caería en el pasado de T-1. Así los renglones comparan el mismo
tramo de plazo y no el mismo mes de calendario. Las columnas «Día T-1» y «Día T» son el
desplazamiento de cada rejilla y solo difieren cuando las dos fechas caen en meses de
distinta duración; una nota al pie da la ventana de T-1 cuando no coincide con la de T.

**El nodo promedia todos los títulos que vencen en la ventana.** El Excel se quedaba
solo con los empatados en el plazo máximo del bucket, que es de donde venían los nodos
de uno o dos papeles. El primer nodo de tasa fija pasa de un puñado a **999 títulos**, y
en 24 meses no queda ninguno con menos de tres en ningún bloque.

Horizonte por bloque: **7 años** en tasa fija, **3 años** en IPC y en IBR.

La escala de calificación es la de corto plazo (`F1+`) mientras la ventana termine
dentro del primer año, y la de largo plazo (`AAA`) desde ahí.

## Rentabilidades esperadas

Tercera pestaña. Cada ventana de la rejilla se trata como un **CDT sintético
independiente** que vence al final de su ventana, con el cupón y la tasa que esa
ventana muestra en T. No se promedia ni se interpola entre rangos, y no entra ninguna
fuente distinta de las que ya usa el reporte más las sendas de proyección.

Controles: tipo (tasa fija / IPC / IBR), escenario (Alcista · Base · Bajista) y un campo
libre de delta en puntos básicos. Tres tablas por tipo: **90 días, 180 días y al
vencimiento**.

### El bloque de IPC, de principio a fin

Esta es la metodología acordada para IPC, con un ejemplo completo. Lo que sigue después,
en «Cómo se construye», es la mecánica común a los tres tipos.

**Los tres insumos** salen del nodo del bloque IPC · CDT en la fecha T, y de ningún otro
lado:

| Insumo | Qué es | En el ejemplo |
|---|---|---|
| **TIR** | la tasa de valoración promedio del nodo, sin convertir — la columna «Tasa» de la pestaña de curvas | 11,070 % |
| **Cupón** | el cupón facial promedio del nodo, que en IPC es el **spread sobre inflación**, no una tasa nominal | 3,000 % |
| **Margen real** | `(1 + TIR) / (1 + IPC de la barra) − 1` — **el mismo número que muestra la columna «Margen real»** de la pestaña de curvas | 4,6448 % |

**El CDT sintético** vence en el borde de su ventana —el último día en que un título
puede vencer y aún contar en ese rango— y paga **cupón trimestral**. El calendario se
cuenta hacia atrás desde el vencimiento, así que el día del mes no se arrastra al pasar
por un mes corto.

**La tasa cupón de cada período** es `[(1 + cupón T) × (1 + IPC)]^(1/4) − 1`, y ese IPC se
lee **tres meses antes del pago del propio cupón** — para el primero, eso es el día en
que se pagó el último cupón antes de hoy, que siempre cae en o antes de la valoración y
por tanto es un dato publicado. Los demás son proyección y salen de la senda del
escenario elegido. Valorando el 28-jul-2026 un rango que vence el 27-jul-2027:

| Cupón paga | Lee el IPC de | Alcista | Base |
|---|---|---|---|
| 27-oct-2026 | 27-jul-2026 | 6,140 % → 2,2537 % | 6,140 % → 2,2537 % |
| 27-ene-2027 | 27-oct-2026 | 6,292 % → 2,2902 % | 6,140 % → 2,2537 % |
| 27-abr-2027 | 27-ene-2027 | 6,442 % → 2,3263 % | 6,140 % → 2,2537 % |
| 27-jul-2027 | 27-abr-2027 | 6,592 % → 2,3623 % | 6,140 % → 2,2537 % |

**V₀, el precio de entrada**, descuenta todos esos flujos a una sola tasa:
`(1 + IPC de la barra) × (1 + margen real) − 1`. Como el margen se despejó dividiendo por
ese mismo IPC, **el IPC se cancela y la tasa de entrada es exactamente la TIR del nodo**.
Escribir otro IPC arriba no mueve el precio: solo reparte distinto entre inflación y
margen. Los cupones, en cambio, sí se proyectan con la senda, así que **V₀ depende del
escenario**: comprar esperando más inflación cuesta más hoy.

**La salida**, en el día h (90 días, 180 días, o el vencimiento menos un día):

- Los flujos **anteriores** a la fecha de salida son V₀ hoy y cada cupón cobrado en la
  fecha en que se paga.
- Los flujos **posteriores** se traen a la fecha de salida —proyectados con la senda del
  escenario— a la tasa `(1 + margen real + δ) × (1 + IPC esperado en la fecha de salida) − 1`.
- Ese IPC esperado se lee **en la propia fecha de salida**, no tres meses antes: la regla
  de «tres meses antes» rige la tasa cupón, no la de descuento.
- El **margen no se recalcula**: es el de T y solo lo mueve el delta.

**El HPR** es el XIRR de `−V₀` hoy, los cupones cobrados en sus días y `+V₁` en el día h,
base ACT/365.

Con el ejemplo de arriba, IPC de la barra en 6,14 % y senda Base plana en ese mismo valor:

| Escenario | V₀ | Tasa de venta 90 d | V₁ 90 d | HPR 90 d | 180 d | Al venc. |
|---|---|---|---|---|---|---|
| Alcista | 98,7056 | 11,1764 % | 101,2246 | 10,7609 % | 10,8133 % | 11,0683 % |
| Base | 98,5060 | 11,0700 % | 101,0894 | **11,0700 %** | **11,0700 %** | **11,0700 %** |
| Bajista | 98,3060 | 10,9636 % | 100,9536 | 11,3805 % | 11,3283 % | 11,0717 % |

La fila Base devuelve exactamente la tasa de entrada en los tres horizontes, que es el
invariante de la construcción. Y fíjate en el signo: **el escenario alcista rinde menos**,
no más. No es un error — al proyectar V₀ con la senda, ya pagaste hoy por esa inflación,
así que que se cumpla no te deja ganancia extra.

El delta, siempre sobre la tasa de venta:

| δ | HPR 90 d | 180 d | Al venc. |
|---|---|---|---|
| −50 pb | 12,6299 % | 11,5913 % | 11,0714 % |
| 0 | 11,0700 % | 11,0700 % | 11,0700 % |
| +100 pb | 8,0366 % | 10,0421 % | 11,0672 % |

Como el delta mueve el **margen** y este va dentro del producto, 100 pb de delta se
traducen en unos 106 pb sobre la tasa de venta. Es deliberado.

#### Conviene que `params.json` y el archivo de escenarios coincidan en T

El margen se despeja con el IPC de la barra, pero la venta se recompone con el IPC que la
**senda** proyecta en la fecha de salida. Si esos dos valores no coinciden en T, la brecha
aparece como rentabilidad ya en el primer trimestre:

| IPC de la barra (senda en T = 6,21 %) | HPR 90 d |
|---|---|
| 5,50 % | 8,92 % |
| 6,14 % | 10,86 % |
| **6,21 %** — igual que la senda | **11,07 %** |
| 7,00 % | 13,49 % |

No es un defecto del método: dice que el mercado descuenta hoy una inflación distinta a la
que arranca la senda. Pero si no es eso lo que se quiere leer, los dos archivos tienen que
estar alineados en la fecha T.

#### Dónde está en el código

`hpr.py` lo implementa y `JS_CALC`, dentro de `report.py`, lo replica para que el navegador
pueda recalcular al vuelo; las dos versiones se comparan celda por celda en las pruebas.
`filasHpr` es quien arma la llamada: pasa el IPC de la barra como índice de entrada en
IPC, y la senda publicada del día en IBR.

### Cómo se construye

**Calendario** hacia atrás desde el vencimiento, en pasos de tres meses (tasa fija e
IPC) o de un mes (IBR), conservando las fechas posteriores a T. El primer cupón es de
período completo: se cobra entero, y por eso V₀ es precio sucio.

**Cupón del período.** El índice se lee al **inicio del período** y no en su pago, en los
dos índices: un cupón trimestral del 25 de agosto de 2026 usa el IPC de mayo de 2026, y
uno mensual del 27 de agosto usa el IBR del 27 de julio. Es la misma convención del atajo
de la bvc. En el primer cupón ese inicio siempre cae en o antes de la fecha de
valoración, así que ahí el índice es un dato publicado y no una proyección. El exponente
de IPC es la fracción fija `1/4`; en tasa fija e IBR la conversión a periódica es
división lineal:

Esto rige solo la **tasa cupón**. La tasa de descuento usa el índice de hoy en la entrada
y el proyectado en T+h en la salida. En IPC ese «índice de hoy» es el de la barra; en IBR,
el que la senda trae en T.

| Tipo | Cupón del período | Tasa de descuento |
|---|---|---|
| Tasa fija | `cupón / 4` | `TIR(T)` |
| IPC | `((1+IPC_inicio) × (1+cupón))^(1/4) − 1` | `(1 + margen) × (1 + IPC) − 1` |
| IBR | `(IBR_inicio + cupón) / 12` | `(1 + (IBR + margen)/12)^12 − 1` |

El margen es, en IPC, **el mismo número que muestra la columna «Margen real» de la
pestaña de curvas**: despejado con el IPC que esté puesto en la barra de arriba, no con
el del archivo de escenarios. Ese mismo IPC recompone la tasa de entrada, así que los dos
se cancelan y V₀ descuenta a la TIR del nodo escriba lo que escriba el usuario. Lo que sí
se mueve al cambiar el IPC de la barra es la **tasa de venta**, porque el margen entra en
ella. En IBR el margen es el del atajo de la bvc.

**V₀** descuenta todos los flujos a la tasa recompuesta con el índice de hoy, que por
construcción es **la TIR del nodo**: el margen se despejó dividiendo por ese mismo
índice, así que al multiplicarlo de vuelta el índice se cancela. Una sola tasa plana
para todos los cupones.

**Los cupones se proyectan con la senda del escenario elegido, en los dos bloques
indexados**: cada uno lee el índice al inicio de su período —tres meses antes del pago en
IPC, un mes antes en IBR— también más allá de la fecha de valoración. Así que **V₀ cambia
con el escenario**: comprar esperando más inflación, o más IBR, cuesta más hoy.

Es una decisión de negocio, no una propiedad del método. Hasta cierto punto V₀ se
calculaba aplanando la senda al índice de hoy, de modo que el precio de entrada salía
igual en los tres escenarios; eso hacía que el mismo botón moviera los dos bloques en
sentidos opuestos, y por eso se retiró.

Las fechas de índice **anteriores a la valoración** no son proyección sino dato
publicado, y por eso se leen de la senda diaria real:

| Bloque | De dónde sale lo ya publicado |
|---|---|
| **IBR** | de `IB1.xlsx`, la misma senda contra la que se calcula el margen del atajo |
| **IPC** | del propio archivo de escenarios, cuyas tres sendas coinciden en el pasado |

En IBR eso importa porque son dos archivos distintos: si el histórico y el archivo de
escenarios no dijeran lo mismo de un día ya pasado, el margen y el cupón se separarían.
Si a `IB1.xlsx` le faltara ese día, se cae a la senda de proyección en vez de dejar el
rango sin cifra.

**V₁**, en el día h, descuenta los flujos posteriores —proyectados con el escenario— a
la tasa recompuesta con el índice proyectado en T+h y el margen desplazado por el delta.

**HPR** = XIRR por Newton (semilla 10 %, tolerancia 1e-11) sobre `−V₀` en el día 0, los
cupones cobrados en sus días y `+V₁` en el día h, base ACT/365. Al vencimiento,
`h = días − 1`.

### El delta

Siempre sobre la tasa de **salida**; la de entrada nunca se mueve.

| Tipo | Qué desplaza | Tasa de salida |
|---|---|---|
| Tasa fija | la TIR, porque no hay margen | `TIR(T) + δ` |
| IPC | el margen | `(1 + margen + δ) × (1 + IPC_proy(T+h)) − 1` |
| IBR | el margen | `(1 + (IBR_proy(T+h) + margen + δ)/12)^12 − 1` |

**A 90 y 180 días el delta pesa mucho; al vencimiento casi nada.** No es un defecto: al
usar `h = días − 1`, V₁ es el flujo final descontado un solo día, y a esa altura la tasa
que exija el mercado es irrelevante porque al vencimiento pagan el par. Ventana jun-27
de IBR, escenario Base:

| δ | 90 d | 180 d | vencimiento |
|---|---|---|---|
| −50 pb | 14,522 % | 13,611 % | 13,156 % |
| 0 | 12,914 % | 13,073 % | 13,154 % |
| +100 pb | 9,767 % | 12,005 % | 13,152 % |

### Cuatro invariantes, fijados en las pruebas

1. Tasa fija al vencimiento con δ = 0 devuelve **exactamente su propia TIR**.
2. El escenario **no mueve ni un decimal** en tasa fija, en ninguno de los tres
   horizontes: su cupón se conoce desde la negociación.
3. Con la senda del índice plana y δ = 0, el HPR devuelve **exactamente la tasa de
   entrada** en IPC y en IBR. Es lo que garantiza que entrada y salida usan la misma
   construcción y no aparecen ganancias fantasma.
4. En IPC, la **tasa de entrada es la TIR del nodo** para cualquier IPC que se escriba en
   la barra, porque el mismo valor despeja el margen y lo recompone. Cambiar el IPC de
   arriba no mueve V₀; mueve la venta.

### Dos advertencias que el reporte muestra

**Rangos que vencen antes del horizonte.** En las tablas de 90 y 180 días, esas filas
muestran su HPR al vencimiento con la etiqueta «(al venc.)» y una nota al pie con el
conteo. En la tabla del vencimiento no se marca nada, porque ahí es lo esperado.

**Extrapolación.** Las sendas llegan a enero de 2028 (IPC) y diciembre de 2027 (IBR),
mientras la rejilla de esos bloques cubre tres años. Las fechas que se salen arrastran el
último dato publicado y llevan un asterisco. A 90 y 180 días no hay extrapolación en
ninguna fila; solo afecta a los plazos largos de la tabla al vencimiento.

**En IBR, la tasa de entrada no es la columna «Tasa (T)»** de la otra pestaña, sino la
recompuesta desde el margen del atajo: difieren hasta 48 pb en los plazos largos, porque
el atajo descuenta contra la curva forward completa y aquí se recompone con un solo valor
de IBR. En IPC y en tasa fija coinciden exactamente.

## Tasa y margen, en columnas aparte

Los dos bloques indexados muestran **las dos medidas del mismo nodo**, cada una con sus
tres columnas (T-1, T y Δ pb): primero la **tasa** de valoración tal como la envía el
proveedor, y enseguida el margen —el **margen real** en IPC, el del atajo de la bvc en
IBR—. La gráfica lleva un conmutador para ver una u otra serie, y abre en la que define
cada bloque: IPC en su margen real, IBR en la tasa.

Tenerlas juntas importa porque **sus dos Δ pb no tienen por qué coincidir**. El de la
tasa es movimiento de mercado y nada más. El del margen real absorbe además la
diferencia entre el IPC de T-1 y el de T, así que con IPC distintos en las dos fechas
las dos columnas cuentan cosas distintas, y esa distancia es justamente la que se quiere
poder leer.

Editar el IPC en la barra de arriba mueve el margen real y deja la tasa quieta: el IPC
no entra en la cifra del proveedor.

## Margen sobre IBR, por el atajo de la bvc

El bloque de IBR trae, junto a la TIR, el **margen nominal sobre IBR** calculado con el
método «atajo» de la Calculadora IBR de la bvc. La gráfica del bloque tiene un botón
para ver una u otra serie.

Como el nodo es un agregado y no un título, se le supone un cronograma: **vence el
último día de su ventana**, paga cupón mensual hasta esa fecha y está «Previa». La fecha
es solo un supuesto; la TIR es la del propio nodo. No usa el cupón facial: el atajo no lo
necesita.

Que sea el **último día** y no el anclaje importa por dos razones. La ventana es
semiabierta —`[desde, hasta)`—, así que el último día en que un título puede vencer y aún
contar en el nodo es `hasta − 1`: un rango que va del 28 de agosto al 27 de septiembre
vence el 27 de septiembre. Y es la misma fecha que usa la pestaña de rentabilidades
esperadas, de modo que **el margen y el HPR de un rango hablan del mismo instrumento**.

Insumos, los dos por fecha:

| Archivo | Qué aporta | Dónde |
|---|---|---|
| `IND_IBR_AAAAMMDD.txt` | curva forward, tenor IB1; se usa la del **día hábil anterior** | carpeta de `--curvas` |
| `IB1.xlsx` | senda histórica diaria, de donde salen las lecturas anteriores a la valoración | la misma carpeta |

**Cada fecha usa la curva del día hábil anterior**, que es la que estaba publicada al
valorar. Se toma el archivo más reciente fechado antes de D, así que los lunes y los días
después de festivo toman el último día hábil con archivo. La **senda histórica no se
desplaza**: va entera, y de ella sale el índice de los períodos que ya habían empezado
al valorar.

### Dónde se lee el índice de cada cupón

La modalidad es **«Previa»**: la tasa de un período quedó fijada **al empezarlo**, no el
día en que se paga. Así que el índice de un cupón se lee **un período antes de su pago,
conservando el número del día**; si ese día no existe en el mes destino, se recorta al
último:

| Cupón paga | Índice que toma |
|---|---|
| 15 de julio | 15 de junio |
| 31 de diciembre | 30 de noviembre, porque noviembre no tiene 31 |
| 29 de marzo de 2027 | 28 de febrero de 2027 |

De dónde sale esa lectura depende de dónde caiga, y la regla es una sola: **en o antes de
la fecha de valoración es un dato publicado y se toma de la senda histórica; después es
una proyección y se toma de la curva forward**. El primer cupón siempre cae del lado de
la senda, porque su período empezó antes de valorar.

Con valoración del 28 de septiembre de 2026 y un nodo que vence el 30 de octubre, los
cupones caen los días 30:

| Cupón | Índice | De dónde |
|---|---|---|
| 30 de septiembre (paga en dos días) | 30 de agosto | senda histórica |
| 30 de octubre (vencimiento) | 30 de septiembre | curva forward |

**La fecha se busca exacta.** Si la senda no trae el día en que se fijó la tasa de algún
período —un festivo, un fin de semana— ese rango no se calcula y su celda dice «sin
dato», en vez de sustituirlo por el valor de otro día.

Cuando la fecha de valoración cae en un día que la rejilla mensual reproduce mes a mes
—lo habitual— el primer cupón lee exactamente la fecha de valoración. Solo cuando la
rejilla se desplaza, con valoraciones cerca de fin de mes, la lectura se va a un día
distinto.

Eso funciona sin puntos faltantes porque el archivo empieza en su propia fecha más un día:
la curva de D−1 arranca en D y cubre todos los flujos que el atajo consulta, que son
posteriores a D.

Si no hay ninguna curva fechada antes de D, el margen de D no se calcula: sus celdas dicen
«sin curva» y una nota al pie explica por qué. Nunca se reemplaza por la curva de otro día,
y el reporte deja constancia de con cuál se calculó cada fecha.

Consecuencia práctica: **la fecha más reciente de la serie no tendrá margen hasta que
llegue el archivo del día siguiente**, porque necesita una curva anterior a ella.

Convenciones: `J` son días calendario descontando los 29 de febrero del tramo; `L` es
base 30/360 US/NASD, la de `DAYS360` de Excel; el cronograma se ancla en el vencimiento
y retrocede en múltiplos exactos de mes, de modo que el día del mes no se arrastra al
pasar por un mes corto; la tasa de cada período se lee al inicio, un mes antes del pago,
según la regla de arriba; el margen es el promedio simple de los márgenes por período,
redondeado a dos decimales de porcentaje.

Comprobación del método, verificada contigo contra la Calculadora IBR: valoración
28-jul-2026, vencimiento supuesto 2028-01-28 (549 días), TIR 13,521 %, 18 flujos
mensuales, IBR previo 11,526 % → **margen 1,15 %**. Está fijada en las pruebas junto con
otros ocho plazos.

### Dos pestañas

### Dos pestañas

El título va centrado y las dos pestañas debajo. Las fechas comparadas no se repiten
en la cabecera: están en las listas de la barra de parámetros.

| Pestaña | Contenido |
|---|---|
| **Curvas por rango de plazo** | los bloques de tasa fija, IPC e IBR (los dos indexados con su margen en columnas aparte y conmutador de serie en la gráfica), cada uno con CDT, CDT HY y BONO |
| **Rentabilidades esperadas** | HPR del CDT sintético de cada rango a 90 días, 180 días y al vencimiento, por escenario y con delta |
| **Comparación y control** | el resumen del par, la cinta del archivo, el embudo de exclusiones, la tabla de TES y la calidad de datos |

La pestaña activa queda en el ancla de la dirección (`#curvas` o `#datos`), así que el
reporte se puede compartir abierto en una de las dos y el botón de atrás del navegador
funciona. Se cambia con el ratón o con las flechas del teclado.

Al **imprimir** salen las dos pestañas, no solo la visible.

### Colores y tipografía

Paleta rosada sobre crema: `#E58FB0` en la barra superior, `#FFB8D2` en la de
parámetros, `#FFD6E8` en los encabezados de tabla y `#FFFDF7` de fondo de página. La
tinta es un ciruela profundo (`#3A2230`) que armoniza con los rosados y da 6,1:1 de
contraste incluso sobre el rosado más fuerte. Todas las combinaciones de texto del
reporte cumplen el nivel AA (4,5:1); están medidas, no estimadas.

Los rosados quedaron en las superficies y la tinta oscura en los datos. Es la
jerarquía que hace legible una tabla densa: el color identifica la interfaz y el
contraste identifica las cifras.

Toda la tipografía es **Arial**. Conviene saber por qué eso funciona aquí: los dígitos
de Arial tienen ancho uniforme, así que las columnas numéricas quedan alineadas sin
necesidad de una fuente monoespaciada. La única excepción es el registro crudo de «la
cinta», que sigue en monoespaciada porque ahí el ancho fijo no es estética: es lo que
hace que los cortes de campo sean ciertos.

El eje X de todas las gráficas —las nueve de bloque y la de TES— es el **plazo, en
años**. En TES es el plazo del propio título. En los bloques el nodo no es un título
sino una ventana mensual de vencimientos, así que su plazo es el **final de la
ventana**: la misma convención con la que ya se le calcula el margen sobre IBR y su
rentabilidad esperada. Cada fecha lo mide contra su propia rejilla, igual que el resto
del reporte. La duración no desaparece: sigue en la tabla, en sus dos columnas.

Las gráficas de los tres bloques llevan, además de las dos curvas, **barras con la
diferencia en puntos básicos entre T y T-1**, en un eje derecho propio. Las diferencias
son de pocos puntos básicos —entre −10 y +9 en el archivo del 28 de julio— así que en el
eje de la tasa serían invisibles. La escala derecha va centrada en cero, con el cero
marcado, y las barras se dibujan detrás de las curvas.

Las barras van en gris neutro (`#9FA3A9`) y la curva de T en magenta (`#C93384`): al no
competir de tono, las barras pueden ir más opacas sin tapar las líneas. Al 50 % el gris
quedaba casi invisible —1,53 de contraste contra el fondo—, así que van al 70 %. Los
números del eje derecho usan un gris más oscuro, porque el de las barras no alcanza
contraste para texto.

Cada barra se ancla en el **plazo de T** y se extiende hasta los puntos medios con sus
vecinas, de modo que quedan pegadas. Sobre el eje de plazo los nodos quedan repartidos
parejo por construcción —son ventanas mensuales—, así que el ancho es prácticamente
uniforme: unos 8 píxeles en tasa fija y 18 en los bloques a tres años, con la variación
que dejan los meses de distinta duración. En el
En los dos bloques indexados la barra sigue la serie que muestre el conmutador: si está
en «Margen», la diferencia es de margen y no de tasa. La gráfica de TES no lleva barras.

Las series de las gráficas se distinguen por **cuatro luminancias distintas** y no solo
por matiz, de modo que siguen leyéndose impresas en gris o por alguien con deficiencia
de visión de color. El trazo discontinuo marca T-1 y el continuo T, igual en todo el
reporte.

### Por qué las tablas se arman en el navegador

Con un año de historia hay más de treinta mil pares de fechas posibles: pre-renderizar
las tablas de todos sería absurdo. Lo que va embebido es el resumen de cada fecha, unos
5 KB, y el navegador arma la comparación del par elegido.

Eso significa que **el reporte necesita JavaScript**. La contrapartida es que sigue
siendo un solo archivo sin dependencias de red: se abre sin conexión y se puede adjuntar
a un correo.

| Historia procesada | Tamaño del HTML |
|---|---|
| Un trimestre (60 fechas) | ~0,5 MB |
| Medio año (120 fechas) | ~0,9 MB |
| Un año (250 fechas) | ~1,8 MB |

---

## Qué hace, capa por capa

| Módulo | Reemplaza a | Función |
|---|---|---|
| `loader.py` | las dos consultas de Power Query | lee el plano de ancho fijo y valida los tres controles de la cabecera |
| `transform.py` | el VBA `Organizar_Datos` | excluye el universo fuera de alcance y calcula rango, calificación simple, margen, familia y duración |
| `bonds.py` | — | duración de Macaulay al vencimiento a partir del flujo de caja |
| `curves.py` | hojas `Main`, `TF`, `IPC`, `IBR`, `TES` | nodos por bucket y por vencimiento, análisis título a título |
| `ibr.py` | — | curva IND_IBR, senda histórica y margen por el atajo de la bvc |
| `escenarios.py` | — | sendas de proyección de IPC e IBR por escenario |
| `hpr.py` | — | CDT sintético y rentabilidad esperada por rango |
| `store.py` | — | resumen compacto por fecha y caché incremental |
| `report.py` | las gráficas y el formato del libro | HTML de un solo archivo con la serie embebida |
| `config.py` | hoja `Set Up` y las constantes dispersas en celdas | toda la parametría en un solo lugar |

### Todo lo configurable está en `config.py`

| Constante | Qué controla |
|---|---|
| `DETAIL_LAYOUT` | el layout del plano, campo por campo con sus posiciones |
| `RATING_MAP` | homologación de calificaciones (réplica exacta de la hoja `Set Up`) |
| `RATING_CORTO` / `RATING_LARGO` | el par que define la curva de referencia (`F1+` / `AAA`) |
| `CDT_HIGH_YIELD_PREFIXES` | emisores marcados HY por criterio propio |
| `EXCLUSIONS` | las exclusiones del universo, declarativas |
| `BLOCKS` | qué curvas construir: índice, periodicidad, moneda y años de rejilla |
| `INDICES_SIN_CONVERSION` | índices que entran sin transformar la tasa (hoy, IBR) |
| `TES_NEMOTECNICOS_EXCLUIDOS` | nemotécnicos de relleno fuera de la tabla de TES |
| `MIN_TITULOS_POR_NODO` | umbral de fragilidad de un nodo (hoy, 3) |
| `DURACION_FUENTE` | `proveedor`, `calculada` o `mixta` |

---

## Equivalencia verificada con el Excel

Comparado contra los valores cacheados del libro con los planos del 28 y 27 de julio
de 2026. Las pruebas de `tests/test_regresion.py` fijan estos números.

| Comprobación | Resultado |
|---|---|
| Registros leídos | 304.541 (T) y 303.404 (T-1), igual que la cabecera |
| Sumas de control del proveedor | las tres cuadran al milésimo |
| Títulos TES | 172, igual que `CDT/BONO = "TES"` |
| TES título a título | idénticos en plazo, duración, tasa y DV01 |
| Duración calculada vs. la del proveedor en tasa fija | diferencia mediana de 3e-5 años, 0,005 en el percentil 99 |

```bash
pytest -q          # 61 pruebas
```

Dos de ellas usan **node**, y se saltan si no está instalado:

- una ejecuta la misma capa de cálculo que corre en el navegador y compara sus tablas
  contra las de Python celda por celda: nodos, TES, y las rentabilidades esperadas de
  los tres tipos por tres escenarios por tres deltas, casi 30.000 valores;
- otra carga el reporte en un DOM real, cambia de pestaña, mueve el IPC y cambia la
  fecha de comparación, y verifica que todo se renderice y reaccione. Necesita jsdom:

```bash
npm install jsdom      # opcional, habilita la prueba de interfaz
```

Esa segunda prueba existe por un fallo concreto: la primera versión de las pestañas
actualizaba el ancla de la dirección **antes** de trazar la gráfica. Abierto con doble
clic el protocolo es `file://`, cuyo origen es «null», y ahí `history.replaceState` lanza
`SecurityError`: la excepción cortaba la función y la gráfica de TES quedaba vacía. Ahora
se dibuja primero y el ancla se actualiza al final, entre `try/catch`. Una prueba de
datos nunca habría visto eso.

Las tasas de los bloques indexados pueden diferir en el último bit: el navegador aplica
el margen al promedio de las tasas del nodo y Python promedia el margen de cada título.
Es la misma cuenta en aritmética real, pero no en punto flotante.

El universo depurado queda en **294.034** títulos, contra los 294.124 del Excel: la
diferencia son los 90 títulos en DTF, DTE e IB3 que ahora se excluyen a propósito.

La comparación nodo a nodo contra la hoja `Main` se retiró al cambiar el corte de
buckets de plazo a ventanas mensuales: son cortes distintos y el nodo ya no se arma con
`MAXIFS` sino promediando toda la ventana. La equivalencia con el libro sigue verificada
donde el corte no cambió.

---

## Decisiones de negocio aplicadas

| Tema | Decisión |
|---|---|
| Archivos | se procesan todos los que haya; el par a comparar se elige en pantalla |
| IPC en T y T-1, tasa BanRep | editables en pantalla |
| DTF, DTE e IB3 | se eliminan del universo (116 registros en T) |
| IBR (IB1) | bloque propio, con la TIR sin convertir y el margen por el atajo de la bvc en columnas aparte |
| Deuda privada (FS e IPC) | plazo, duración, cupón, tasa con su Δ —y en IPC además el margen real con el suyo— y muestra. Sin curva TES de referencia, sin spread y sin inflación implícita |
| Curva TES | descriptiva: condiciones faciales, plazo, duración, precio, valoración y su diferencia. Única medida derivada: DV01. Sin ajuste logarítmico, sin spreads, sin implícita, sin carry, sin extrapolación |
| Nemotécnicos CINAS y TDS | fuera de la tabla de TES (llegan con tasa y duración en cero) |
| Corte de los bloques | ventanas mensuales de vencimiento, con la ventana de fechas en la primera columna |
| Rentabilidades esperadas | solo CDT; tres tipos, tres escenarios, delta libre en pb |
| Valoración del CDT sintético de IPC | vence en el borde de su ventana; cupón trimestral `[(1+cupón T)(1+IPC)]^(1/4)−1` con el IPC de tres meses antes de cada pago; V₀ proyectado con la senda del escenario y descontado a la TIR del nodo; venta a `(1+margen real+δ)(1+IPC esperado en la fecha de salida)−1` |
| Horizonte | 7 años en tasa fija, 3 en IPC y en IBR |
| Contenido del nodo | promedio de todos los títulos que vencen en la ventana |
| Muestra por nodo | se incluye (`n T-1`, `n T`) con nota al pie si algún nodo queda corto |
| Cupón promedio del nodo en T | columna `Cupón · T` en los bloques FS e IPC |
| Duración | al vencimiento |
| Homologación de calificaciones | como en la hoja `Set Up`, sin agregados |
| Umbral de fragilidad | 3 títulos por nodo |
| Filtro de moneda | quitado |

---

## Diferencias con el Excel

Cada una corrige algo que el libro resolvía en silencio.

**1. Precisión de los campos de precio.**
`pandas.to_numeric` cuenta los ceros de relleno del plano como dígitos significativos
y corta en 17, de modo que `000000000000095.651` se lee como `95.65`. Sobre 300.000
registros eso desplazaba las sumas de control en más de mil pesos. El lector usa
`numpy.astype`, que es exacto y además tres veces más rápido.

**2. Se validan los tres controles del proveedor y la fecha.**
El plano trae conteo de registros y dos sumas de precio que cuadran exactamente. El
proceso anterior los descartaba, así que nada detectaba un archivo truncado o del día
equivocado.

**3. La homologación de calificaciones no falla en silencio.**
`VrR2-`, `VrR1`, `BRC2` y `SIN_CALIFI` no están en la hoja `Set Up`. En el Excel el
`VLOOKUP` fallaba y el error quedaba tragado por un `On Error Resume Next` que nunca
se desactivaba. El resultado es el mismo (9.750 títulos quedan sin calificación
simple y se clasifican como CDT HY), pero ahora se cuentan y se muestran.

**4. La duración de los indexados se calcula al vencimiento.**
El proveedor la reporta al próximo corte de cupón: en los IPC con más de 2 años es el
1,6 % del plazo, contra el 89 % en tasa fija. `bonds.py` la calcula a partir del flujo
de caja y la contrasta contra el proveedor en los 50.000 títulos de tasa fija con
cupón, donde el proveedor sí la mide al vencimiento: la diferencia mediana es de
0,00003 años.

El cupón proyectado depende del índice, y cada convención se eligió comparando el
precio teórico contra el precio sucio que envía el proveedor:

| Índice | Cupón proyectado | Error mediano de precio |
|---|---|---|
| FS | el cupón facial, nominal | 0,03 |
| IPC | `IPC + facial` | 0,63 |
| IBR, DTF | la propia tasa de valoración | 0,36 |

Los indexados a una tasa de corto plazo reponen su cupón en cada corte y cotizan a la
par (precio sucio entre 100,3 y 101,6), así que proyectar solo el spread facial dejaba
el precio teórico once puntos por debajo del real y sobrestimaba la duración.
**5. Los bloques de deuda privada son autónomos.**
No llevan curva TES de referencia, spread de crédito ni inflación implícita. Cada
bloque se lee por sí mismo: plazo, duración, cupón, tasa, su diferencia entre fechas y
el tamaño de la muestra. En los dos bloques indexados la medida comparable va en su
propio grupo de columnas, al lado de la tasa: el margen real en IPC y el del atajo de
la bvc en IBR.

**6. La tabla de TES no lleva medidas derivadas más allá del DV01.**
Sin el ajuste logarítmico que el libro traía escrito a mano en las celdas, sin spread
contra la curva y sin inflación implícita. Y sin los nemotécnicos CINAS y TDS, que
llegan con tasa y duración en cero.

**7. Cada nodo trae el promedio de su tasa cupón en T.**
Se promedia sobre el mismo conjunto que la duración y la tasa: todos los títulos que
vencen en la ventana. En el bloque IPC ese cupón es el
spread facial sobre inflación, no una tasa nominal.

**8. Se cuenta la muestra de cada nodo.**
Cada nodo trae su `n` en las dos fechas, y al pie de cada tabla una nota dice en cuántos
la muestra queda por debajo de tres títulos, enumerando la más corta de las dos listas.
Al pasar a ventanas mensuales y promediar toda la ventana, la muestra dejó de ser el
problema que era: en 24 meses ningún bloque tiene nodos cortos.

**9. Las titularizaciones se clasifican con prefijos de dos o más caracteres.**
El Excel usaba `Left(nemo,1) = "T"`, que atrapa cualquier bono corporativo de un
emisor cuyo nombre empiece por T.

**10. Sin `carry`, `slide` ni `neto` en la tabla TES.**
El Excel calculaba el slide como la diferencia de tasa contra otro título de la lista
dividida por la diferencia de días. Con dos referencias a un día de distancia y 70 pb
de diferencia salían slides de más de 2.000 pb, y cuando dos títulos compartían plazo
dividía por cero.

---

## Pendientes de decisión

1. **Referencia para IB3 y DTF** si en algún momento se quieren incorporar: hoy se
   excluyen del universo.
2. **`CERTS`** (2 registros) tiene la misma firma de relleno que CINAS y TDS: tasa y
   duración en cero. No se excluyó porque no se pidió; agregarlo a
   `TES_NEMOTECNICOS_EXCLUIDOS` en `config.py` es una línea.
3. **Tasa BanRep**: hoy no la consume ningún cálculo. Se mantiene en pantalla por
   pedido explícito y para trazabilidad.
4. **Retención del caché**: no se borra nada solo. Si la serie crece más de lo que
   conviene tener en un HTML, basta con mover a otra carpeta los resúmenes viejos.
5. **Convención del cupón proyectado en los IPC.** Se usa `IPC + facial`, que ajusta
   el precio del proveedor mejor que `(1+IPC)·(1+facial)−1` (error mediano de 0,63
   contra 1,71 en precio). La duración es poco sensible: 4,162 contra 4,143 años.
6. **`Call Implicitas`** estaba comentado en el VBA. Si era un paso faltante, hay que
   especificarlo.

## Estructura

```
sx_pricer/
    config.py       parametría: layout, homologaciones, buckets, bloques
    loader.py       lectura del plano + validación de integridad
    bonds.py        duración de Macaulay al vencimiento
    transform.py    exclusiones + columnas derivadas + calidad de datos
    curves.py       nodos, interpolación, análisis TES
    ibr.py          curva IBR y margen por el atajo de la bvc
    escenarios.py   sendas de proyección de IPC e IBR
    hpr.py          rentabilidad esperada del CDT sintético
    store.py        resumen por fecha y caché incremental
    report.py       generación del HTML con la serie embebida
    cli.py          línea de comandos
tests/
    test_regresion.py
    verificar_js.js   corre la capa de cálculo del navegador para compararla
params.json
requirements.txt
correr.bat              atajo para la corrida diaria en Windows (no se edita)
rehacer_todo.bat        igual, pero fuerza a reprocesar todo desde cero
mis_rutas.ejemplo.bat   plantilla: cópiala como mis_rutas.bat y pon tus rutas
```
