@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  QuantFactorLab  一键打包为 Windows exe
echo  建议使用 Python 3.11 / 3.12（64位）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 https://www.python.org/downloads/
  echo        安装时务必勾选 "Add python.exe to PATH"
  pause
  exit /b 1
)

if not exist .venv (
  echo [1/4] 创建虚拟环境...
  python -m venv .venv
)
call .venv\Scripts\activate

echo [2/4] 安装依赖...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto fail
pip install pyinstaller
if errorlevel 1 goto fail

echo [3/4] 打包...
pyinstaller --noconfirm --clean --onefile ^
  --name QuantFactorLab ^
  --add-data "web;web" ^
  --collect-submodules akshare ^
  --collect-data akshare ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import app.server ^
  run.py
if errorlevel 1 goto fail

echo.
echo [4/4] 完成！exe 位于 dist\QuantFactorLab.exe
echo        首次运行若提示 SmartScreen，选择"仍要运行"即可。
echo        配置文件与行情缓存会生成在 exe 同级的 data 目录。
echo.
pause
exit /b 0

:fail
echo.
echo [失败] 打包过程中出错，请把上方红色错误信息截图反馈。
pause
exit /b 1
