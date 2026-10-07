@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  重新打包 TarkovMarketInfo.exe
echo ============================================
echo.

REM --exclude-module：Pillow 的 Image.py / ImageFilter.py / _typing.py 里有
REM   "import numpy" 这类可选引用，PyInstaller 静态分析会当真，把整个 numpy
REM   （含 20MB 的 OpenBLAS）拖进来；numpy 又顺带拖进 psutil / yaml /
REM   charset_normalizer。本程序一行都没用到它们，全部排除。
C:\Python314\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
  --name TarkovMarketInfo ^
  --icon "%~dp0app.ico" ^
  --add-data "%~dp0app.ico;." ^
  --paths src ^
  --exclude-module numpy ^
  --exclude-module psutil ^
  --exclude-module yaml ^
  --exclude-module charset_normalizer ^
  --exclude-module win32pdh ^
  --distpath . ^
  --workpath build/work ^
  --specpath build ^
  src/main.py

if errorlevel 1 (
  echo.
  echo 打包失败，看上面的报错。
  pause
  exit /b 1
)

echo.
echo ============================================
echo  打包完成
echo  产物: %~dp0TarkovMarketInfo.exe
echo.
echo  自检（不弹窗口，把整条链路跑一遍）:
echo    TarkovMarketInfo.exe --selftest
echo    TarkovMarketInfo.exe --selftest 100     ^(压测 100 条的长图^)
echo  结果写到: %%TEMP%%\tarkov_selftest.txt
echo.
echo  看界面（开发用，截一张窗口图）:
echo    python src\main.py --shot shot.png --light
echo ============================================
pause
