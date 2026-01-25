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
    echo [91mErreur:[0m Python n'est pas installe.
    echo Telechargez Python 3.8+ depuis https://www.python.org/downloads/
    echo Assurez-vous de cocher "Add Python to PATH" lors de l'installation
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [92mPython %PYTHON_VERSION% detecte[0m

REM Vérifier si pip est installé
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [91mErreur:[0m pip n'est pas installe.
    echo Reinstallez Python en cochant "pip" lors de l'installation
    pause
    exit /b 1
)

echo [92mpip detecte[0m
echo.

REM Vérifier ImageMagick (optionnel mais recommandé)
echo Verification d'ImageMagick (requis pour la conversion d'images)...
magick --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [93mAvertissement:[0m ImageMagick n'est pas installe.
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
    echo [92mImageMagick detecte[0m
)

echo.
echo Installation des dependances Python...
pip install -r requirements.txt --upgrade

echo.
echo ======================================
echo [92mInstallation terminee ![0m
echo ======================================
echo.
echo Pour lancer le Dashboard :
echo   run.bat
echo ou
echo   python Dashboard.py
echo.
pause
