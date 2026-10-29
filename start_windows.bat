@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.11/3.12 并勾选 Add to PATH
  pause
  exit /b 1
)
echo 正在启动 QuantFactorLab（首次运行会自动安装依赖）...
python -m pip install -r requirements.txt --quiet
python run.py
pause
