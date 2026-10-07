@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  重新打包 TarkovMarketInfo.exe (v1.3 带查价)
echo ============================================
echo.

REM app.ico 必须给绝对路径，不能写裸的 app.ico：
REM PyInstaller 把 --add-data 的相对路径按 spec 所在目录（build\）解析，
REM 写相对路径会去找 build\app.ico，报Unable to find。
REM%~dp0 展开出来是带尾反斜杠的绝对路径，这个写法实测可用。
REM 另外 --distpath / --workpath 要和项目在同一个盘，
REM 跨盘（--distpath C:\... 而项目在 E:）会在 relpath 时报
REM "path is on mount 'E:', start on mount 'C:'"。
REM --exclude-module：Pillow 的 Image.py / ImageFilter.py / _typing.py 里有
REM   "import numpy" 这类可选引用，PyInstaller 静态分析会当真，把整个 numpy
REM   （含 20MB 的 OpenBLAS）拖进来；numpy 又顺带拖进 psutil / yaml /
REM   charset_normalizer。本程序一行都没用到它们，全部排除。
C:/Python314/python.exe -m PyInstaller --noconfirm --onefile --windowed ^
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
echo  结果写到: %%TEMP%%\tarkov_selftest.txt
echo.
echo  不带参数双击 = 查价主窗口
echo  顶部「打开排行报表」=原来的报表窗口
echo.
echo  运行时目录（都在 exe 文件夹内）:
echo    data\     数据库 / 配置 / 收藏 / 日志
echo    icon\物品图标
echo    reports\  生成的报表
echo.
pause