@echo off
REM Collecte quotidienne depuis ce PC, puis publication sur GitHub (le dashboard Streamlit Cloud se met a jour).
REM Planifiee par la tache Windows "Reglo - Veille quotidienne" (voir README.md, section "Automatiser").
REM Journal : data\veille.log
cd /d "%~dp0"
set LOG=data\veille.log

echo. >> "%LOG%"
echo ===== Collecte du %date% a %time% ===== >> "%LOG%"

".venv\Scripts\python.exe" -m veille run >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ECHEC de la collecte : rien n'est publie. >> "%LOG%"
    exit /b 1
)

git add data/veille.sqlite reports/ >> "%LOG%" 2>&1
git diff --cached --quiet
if not errorlevel 1 (
    echo Aucune nouveaute a publier. >> "%LOG%"
    exit /b 0
)

git commit -q -m "Veille : collecte locale du %date%" >> "%LOG%" 2>&1
REM Recupere d'abord les modifications faites sur GitHub (ex. fichiers ajoutes depuis Streamlit Cloud).
git pull --rebase -q >> "%LOG%" 2>&1
git push >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ECHEC du push : le commit est garde en local et partira au prochain passage. >> "%LOG%"
    exit /b 1
)
echo Publie sur GitHub. >> "%LOG%"
