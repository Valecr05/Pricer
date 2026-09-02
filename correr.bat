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

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo No encuentro el entorno virtual. Corre esto una sola vez, en una
  echo ventana de comandos abierta en esta misma carpeta:
  echo.
  echo    py -m venv .venv
  echo    .venv\Scripts\python -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
  echo.
  pause
  exit /b 1
)

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

.venv\Scripts\python -m sx_pricer ^
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
