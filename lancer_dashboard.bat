@echo off
REM Ouvre le dashboard de veille dans le navigateur (http://localhost:8501).
REM Fermer cette fenetre arrete le dashboard.
cd /d "%~dp0"
start "" http://localhost:8501
".venv\Scripts\streamlit.exe" run dashboard.py
