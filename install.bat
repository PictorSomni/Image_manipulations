@echo off
REM Installation Windows — non interactive (appele par setup.ps1 ou a la main)
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python introuvable. Lancez plutot setup.ps1.
    pause
    exit /b 1
)
magick --version >nul 2>&1 || echo [AVERTISSEMENT] ImageMagick absent : conversions limitees.

python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt --upgrade
if %errorlevel% neq 0 (
    echo [INFO] Nouvel essai avec ONNX CPU ^(pas de GPU compatible^)...
    set "TMP_REQ=%TEMP%\requirements_cpu_%RANDOM%.txt"
    powershell -NoProfile -Command "(Get-Content 'requirements.txt') -replace '^onnxruntime-gpu.*$', 'onnxruntime>=1.16.0' | Set-Content '%TMP_REQ%'"
    python -m pip install -r "%TMP_REQ%" --upgrade
    if errorlevel 1 (
        echo [ERREUR] Installation des dependances impossible.
        pause
        exit /b 1
    )
)
echo [OK] Installation terminee. Lancer : run.bat
