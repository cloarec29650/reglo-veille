@echo off
REM Collecte hebdomadaire + digest. A planifier dans le Planificateur de taches Windows
REM (voir README.md, section "Automatiser"). Les journaux vont dans data\veille.log.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m veille run >> "data\veille.log" 2>&1
