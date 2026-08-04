@echo off
cd /d D:\ProcessCenter\StackChan\server
docker compose up -d
echo Waiting for MySQL and Redis...
timeout /t 15 /nobreak >nul
echo Starting funnel_proxy.py...
start /B python funnel_proxy.py > proxy.log 2>&1
echo Done. Services started.
