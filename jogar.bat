@echo off
rem Hertz & Beats -- execucao com console (util para ver erros/placar final).
rem Para o atalho sem console na area de trabalho, rode uma vez:
rem   powershell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1
cd /d "%~dp0"
python -m hertzbeats %*
if errorlevel 1 pause
