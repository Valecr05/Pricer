@echo off
REM ===================================================================
REM  sx-pricer  ·  reprocesar TODO desde cero
REM
REM  Igual que correr.bat, pero ignora los resumenes en cache y vuelve a
REM  leer todos los planos. Tarda unos seis segundos por archivo.
REM
REM  Usalo cuando cambie la forma de calcular algo, no en el dia a dia:
REM  la corrida normal ya procesa por su cuenta los planos nuevos.
REM
REM  NO edites este archivo: tus rutas van en  mis_rutas.bat
REM ===================================================================
setlocal
set "SX_REHACER=--rehacer"
call "%~dp0correr.bat"
exit /b %ERRORLEVEL%
