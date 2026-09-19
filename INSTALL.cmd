@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 goto use_py
:try_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto missing_python
python install.py apply
goto done
:use_py
py -3 install.py apply
goto done
:missing_python
echo A working Python 3.10 or newer was not found. No operation was performed.
set "RESULT=1"
goto finish
:done
set "RESULT=%ERRORLEVEL%"
:finish
echo.
pause
popd
exit /b %RESULT%
