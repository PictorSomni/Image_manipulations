@echo off
setlocal

cd /d "%~dp0"

set "EXPECTED_ORIGIN=https://github.com/PictorSomni/Image_manipulations.git"

for /f "usebackq delims=" %%i in (`git rev-parse --show-toplevel 2^>nul`) do set "REPO_ROOT=%%i"

if not defined REPO_ROOT (
    echo [ERREUR] Ce dossier n'est pas un depot Git valide.
    echo [INFO] Dossier courant: %CD%
    pause
    exit /b 1
)

if /I not "%REPO_ROOT%"=="%CD%" (
    echo [ERREUR] Chemin du repo invalide pour ce script.
    echo [INFO] Racine Git detectee: %REPO_ROOT%
    echo [INFO] Dossier du script:   %CD%
    pause
    exit /b 1
)

for /f "usebackq delims=" %%i in (`git remote get-url origin 2^>nul`) do set "ORIGIN_URL=%%i"

if not defined ORIGIN_URL (
    echo [ERREUR] Remote 'origin' introuvable.
    pause
    exit /b 1
)

if /I not "%ORIGIN_URL%"=="%EXPECTED_ORIGIN%" (
    echo [ERREUR] Mauvais depot distant configure.
    echo [INFO] Origin detecte:  %ORIGIN_URL%
    echo [INFO] Origin attendu:  %EXPECTED_ORIGIN%
    pause
    exit /b 1
)

echo [INFO] Mise a jour du depot Git...
git pull

if %ERRORLEVEL% neq 0 (
    echo [ERREUR] Echec du git pull.
    pause
    exit /b %ERRORLEVEL%
)

echo [OK] Depot mis a jour.
pause
