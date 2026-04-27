@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d %~dp0

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo.
    echo [ERROR] No se encontro Python en el sistema.
    echo Instala Python 3 y marca la opcion ^"Add Python to PATH^".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [INFO] Creando entorno virtual local...
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :fail
)

set "VENV_PY=.venv\Scripts\python.exe"

"%VENV_PY%" -m pip --disable-pip-version-check --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo [INFO] Inicializando pip en el entorno virtual...
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 goto :fail
)

set "CUR_HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile requirements.txt SHA256 ^| findstr /R /V /C:"hash" /C:"CertUtil"') do (
    set "CUR_HASH=%%H"
    goto :hash_ready
)
:hash_ready
if not defined CUR_HASH set "CUR_HASH=NO_HASH"
set "CUR_HASH=!CUR_HASH: =!"

set "NEED_INSTALL=1"
if exist ".venv\requirements.sha256" (
    set /p OLD_HASH=<.venv\requirements.sha256
    if /I "!OLD_HASH!"=="!CUR_HASH!" set "NEED_INSTALL=0"
)

if "%NEED_INSTALL%"=="1" (
    echo.
    echo [INFO] Instalando / actualizando dependencias del proyecto...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :fail
    > ".venv\requirements.sha256" echo !CUR_HASH!
)

echo.
echo [INFO] Iniciando interfaz web...
"%VENV_PY%" gui.py
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" goto :fail_runtime
exit /b 0

:fail_runtime
echo.
echo [ERROR] La aplicacion termino con error. Codigo: %EXITCODE%
pause
exit /b %EXITCODE%

:fail
echo.
echo [ERROR] No se pudo preparar el entorno para ejecutar la app.
echo Si es la primera ejecucion, verifica tu conexion a internet para instalar dependencias.
pause
exit /b 1
