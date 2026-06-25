@echo off
REM Script d'installation pour Windows
REM Dashboard Image Manipulation

echo ======================================
echo Dashboard Image Manipulation Setup
echo ======================================
echo.

REM Vérifier si Python est installé
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Erreur:Python n'est pas installe.
    echo Telechargez Python 3.8+ depuis https://www.python.org/downloads/
    echo Assurez-vous de cocher "Add Python to PATH" lors de l'installation
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo Python %PYTHON_VERSION% detecte

REM Vérifier si pip est installé
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Erreur:pip n'est pas installe.
    echo Reinstallez Python en cochant "pip" lors de l'installation
    pause
    exit /b 1
)

echo pip detecte
echo.

echo Mise a jour de pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [AVERTISSEMENT] Impossible de mettre pip a jour, poursuite de l'installation...
)

REM Vérifier ImageMagick (optionnel mais recommandé)
echo Verification d'ImageMagick (requis pour la conversion d'images)...
magick --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Avertissement:ImageMagick n'est pas installe.
    echo.
    echo Pour installer ImageMagick :
    echo   Telechargez depuis https://imagemagick.org/script/download.php#windows
    echo   Choisissez "ImageMagick-...-Q16-HDRI-x64-dll.exe"
    echo.
    set /p CONTINUE="Voulez-vous continuer sans ImageMagick ? (certaines fonctionnalites ne fonctionneront pas) [O/N] : "
    if /i not "%CONTINUE%"=="O" (
        echo Installation annulee.
        pause
        exit /b 1
    )
) else (
    echo ImageMagick detecte
)

echo.
echo Installation des dependances Python...
python -m pip install -r requirements.txt --upgrade
if %errorlevel% neq 0 (
    echo.
    echo [AVERTISSEMENT] Echec de l'installation standard des dependances.
    echo [INFO] Nouvelle tentative avec fallback ONNX CPU ^(si backend GPU indisponible sur cette machine^)...

    set "TMP_REQ=%TEMP%\requirements_fallback_%RANDOM%.txt"
    powershell -NoProfile -Command "(Get-Content 'requirements.txt') -replace '^onnxruntime-gpu>=.*$', 'onnxruntime>=1.16.0' | Set-Content '%TMP_REQ%'"

    python -m pip install -r "%TMP_REQ%" --upgrade
    del /f /q "%TMP_REQ%" >nul 2>&1

    if %errorlevel% neq 0 (
        echo [ERREUR] Installation des dependances impossible.
        pause
        exit /b 1
    )

    echo [OK] Installation terminee avec fallback ONNX CPU.
)

echo.
echo Verification d'Ollama (IA locale)...
set "_OLLAMA_EXE="
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    set "_OLLAMA_EXE=ollama"
) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "_OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
) else if exist "%PROGRAMFILES%\Ollama\ollama.exe" (
    set "_OLLAMA_EXE=%PROGRAMFILES%\Ollama\ollama.exe"
)

if defined _OLLAMA_EXE (
    echo [OK] Ollama detecte.
    echo [INFO] Telechargement du modele texte par defaut ^(llama3.2:3b^)...
    "%_OLLAMA_EXE%" pull llama3.2:3b
    echo [OK] Modele pret.
) else (
    echo [INFO] Ollama non detecte. Installation en cours...
    powershell -Command "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '%TEMP%\OllamaSetup.exe'; Start-Process '%TEMP%\OllamaSetup.exe' -Wait"
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        echo [OK] Ollama installe.
        echo [INFO] Telechargement du modele texte par defaut ^(llama3.2:3b^)...
        ollama pull llama3.2:3b
        echo [OK] Modele pret.
    ) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        echo [OK] Ollama installe.
        echo [INFO] Telechargement du modele texte par defaut ^(llama3.2:3b^)...
        "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" pull llama3.2:3b
        echo [OK] Modele pret.
    ) else (
        echo [AVERTISSEMENT] Impossible d'installer Ollama automatiquement.
        echo [INFO] Installez-le manuellement depuis https://ollama.com/download
    )
)

echo.
echo ======================================
echo Installation terminee !
echo ======================================
echo.
echo Pour lancer le Dashboard :
echo   run.bat
echo ou
echo   python Dashboard.pyw
echo.
pause
