@echo off
title Alien Worlds Miner
color 0A
echo ========================================
echo   ALIEN WORLDS MINER - Starting...
echo ========================================
echo.
cd /d "%~dp0"
echo เริ่มเซิร์ฟเวอร์ขุด...
echo.
echo เปิด http://localhost:5000 เพื่อควบคุมบอท
echo กด Ctrl+C เพื่อหยุด
echo.
start http://localhost:5000
python mine_web.py
pause
