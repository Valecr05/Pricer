@echo off
REM ===================================================================
REM  sx-pricer  ·  corrida diaria
REM
REM  NO edites este archivo: tus rutas van en  mis_rutas.bat
REM  Solo haz doble clic.
REM ===================================================================
setlocal
cd /d "%~dp0"

if not exist "mis_rutas.bat" (
  echo.
  echo No encuentro "mis_rutas.bat", que es donde van TUS carpetas.
  echo.
  echo Hazlo una sola vez:
  echo    1. Copia el archivo  mis_rutas.ejemplo.bat
  echo    2. Renombra la copia a  mis_rutas.bat
  echo    3. Abrela con el Bloc de notas y pon tus tres rutas
  echo.
  echo Ese archivo no viene en las actualizaciones, asi que de ahora en
  echo adelante tus rutas no se pierden al reemplazar la carpeta.
  echo.
  pause
  exit /b 1
)

call "mis_rutas.bat"

REM ===================================================================
REM  El entorno virtual, comprobado de verdad
REM
REM  Un .venv guarda en pyvenv.cfg la ruta ABSOLUTA del Python con el que
REM  se creo. Si Windows actualiza o reinstala Python en otra carpeta, esa
REM  ruta apunta al vacio: el archivo .venv\Scripts\python.exe sigue ahi
REM  -asi que "if not exist" no lo detecta- pero al arrancar dice
REM  "No Python at ..." y no explica que hacer.
REM
REM  Por eso no se comprueba que el archivo exista, sino que el entorno
REM  RESPONDA: se le pide su version y se mira que conteste "Python ...".
REM  Se usa -V y no un -c "print..." a proposito: los parentesis de una
REM  llamada de Python cerrarian antes de tiempo el bloque del for /f.
REM ===================================================================
call :comprobar
if not "%SXPY%"=="Python" goto entorno_roto
goto entorno_listo

:comprobar
set "SXPY="
if not exist ".venv\Scripts\python.exe" goto :eof
for /f "tokens=1" %%a in ('.venv\Scripts\python.exe -V 2^>^&1') do set "SXPY=%%a"
goto :eof

:entorno_roto
echo.
if exist ".venv\Scripts\python.exe" (
  echo El entorno virtual apunta a una version de Python que ya no esta en
  echo su sitio. Pasa despues de actualizar o reinstalar Python.
) else (
  echo Todavia no existe el entorno virtual con las librerias.
)
echo.
echo Se arregla recreandolo, aqui mismo. Tarda un par de minutos y no se
echo pierde nada: el entorno solo contiene librerias. Tus rutas siguen en
echo mis_rutas.bat y los resumenes en .sx-cache, asi que la corrida no
echo tiene que volver a leer los planos.
echo.
set "RESP="
set /p "RESP=Escribe S y pulsa Enter para recrearlo ahora, o N para salir: "
if /i not "%RESP%"=="S" goto salir_sin_entorno

echo.
echo Recreando el entorno...
if exist ".venv" rmdir /s /q ".venv"
py -m venv .venv
if errorlevel 1 goto sin_python

echo.
echo Instalando las librerias...
.venv\Scripts\python -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 goto sin_librerias

call :comprobar
if not "%SXPY%"=="Python" goto sigue_roto
echo.
echo Entorno recreado. Sigo con la corrida.
echo.
goto entorno_listo

:salir_sin_entorno
echo.
echo No se recreo nada. Vuelve a hacer doble clic cuando quieras hacerlo.
echo.
pause
exit /b 1

:sin_python
echo.
echo Windows no encontro Python. Instalalo de python.org/downloads y marca
echo "Add python.exe to PATH" en el instalador. Para comprobar que quedo,
echo abre una ventana de comandos y escribe:  py --version
echo.
pause
exit /b 1

:sin_librerias
echo.
echo No se pudieron instalar las librerias. Suele ser la red de la oficina.
echo El mensaje de pip esta unas lineas mas arriba.
echo.
pause
exit /b 1

:sigue_roto
echo.
echo El entorno se recreo pero sigue sin responder. Copia lo que salio
echo arriba y pidele ayuda a quien mantiene la herramienta.
echo.
pause
exit /b 1

:entorno_listo

if not exist "%PLANOS%" (
  echo.
  echo No existe la carpeta de planos indicada en mis_rutas.bat:
  echo    %PLANOS%
  echo.
  pause
  exit /b 1
)
if not exist "%CURVAS%" (
  echo.
  echo No existe la carpeta de curvas indicada en mis_rutas.bat:
  echo    %CURVAS%
  echo.
  pause
  exit /b 1
)
if /i not "%SALIDA:~-5%"==".html" (
  echo.
  echo SALIDA tiene que ser la ruta de un ARCHIVO que termine en .html,
  echo no una carpeta. Ahora dice:
  echo    %SALIDA%
  echo.
  echo Corrigelo en mis_rutas.bat, por ejemplo:
  echo    set SALIDA=%SALIDA%\reporte.html
  echo.
  pause
  exit /b 1
)

REM %SX_REHACER% va vacio en la corrida normal. rehacer_todo.bat lo pone en
REM --rehacer y llama aqui, para no repetir todas las comprobaciones.
.venv\Scripts\python -m sx_pricer %SX_REHACER% ^
  --archivos "%PLANOS%\SX*.001" ^
  --curvas "%CURVAS%" ^
  --params params.json ^
  -o "%SALIDA%"

set CODIGO=%ERRORLEVEL%
echo.
if %CODIGO%==0 echo Listo, sin novedades.
if %CODIGO%==1 echo ERROR de uso: revisa las rutas en mis_rutas.bat.
if %CODIGO%==2 echo ATENCION: el reporte se genero, pero hay controles de integridad fallidos.
if %CODIGO%==3 echo ATENCION: el reporte se genero, pero hay avisos de calidad de datos.
echo.
if %CODIGO% LEQ 3 if exist "%SALIDA%" start "" "%SALIDA%"
pause
