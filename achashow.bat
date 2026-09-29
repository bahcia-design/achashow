@echo off
rem Abre o achashow: atualiza, liga o servidor e abre o navegador.
rem Para fechar o app, feche esta janela preta.
title achashow
cd /d "%~dp0"
if not exist "web\frontend\dist\index.html" (
  echo Preparando a tela pela primeira vez...
  pushd web\frontend
  call npm install --silent
  call npm run build
  popd
)
start "" "http://127.0.0.1:8000"
echo achashow aberto em http://127.0.0.1:8000  (feche esta janela para desligar)
".venv\Scripts\python.exe" -m uvicorn web.api:app --host 127.0.0.1 --port 8000 --log-level warning
