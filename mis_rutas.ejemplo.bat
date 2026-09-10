@echo off
REM ===================================================================
REM  TUS carpetas.  Este es el UNICO archivo que editas.
REM
REM  Como usarlo, una sola vez:
REM    1. Copia este archivo (Ctrl+C, Ctrl+V en la misma carpeta)
REM    2. Renombra la copia a   mis_rutas.bat
REM    3. Abrela con el Bloc de notas y cambia las tres rutas de abajo
REM
REM  mis_rutas.bat no viene en las actualizaciones, asi que tus rutas no
REM  se pierden cuando reemplaces la carpeta por una version nueva.
REM
REM  Reglas:
REM    - Sin comillas y sin espacios alrededor del signo igual.
REM    - Las rutas SI pueden llevar espacios: escribelas tal cual.
REM    - SALIDA tiene que terminar en .html: es un ARCHIVO, no una carpeta.
REM ===================================================================

REM Carpeta con los planos de Precia (los archivos .001)
set PLANOS=C:\sx-pricer\Archivos Planos

REM Carpeta con las curvas IND_IBR_AAAAMMDD.txt, mas IB1.xlsx y
REM Escenarios_IPC-IBR_VC.xlsx
set CURVAS=C:\sx-pricer\Curvas

REM Donde se escribe el reporte. Tiene que terminar en .html
set SALIDA=C:\sx-pricer\reporte.html
