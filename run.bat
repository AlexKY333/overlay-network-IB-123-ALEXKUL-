@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ======================================================================
echo   АВТОМАТИЧЕСКИЙ ЗАПУСК ОВЕРЛЕЙНОЙ СЕТИ
echo ======================================================================

:: 1. Поиск честного CPython (отсекаем pypy и заглушки WindowsApps)
set "PY_EXE="

:: Пробуем стандартный лаунчер py
where py >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('py -0p 2^>nul ^| findstr /v /i "pypy"') do (
        for /f "tokens=2*" %%a in ("%%i") do (
            if exist "%%b" set "PY_EXE=%%b"
        )
    )
)

:: Если py launcher не нашел, перебираем типовые системные пути
if "%PY_EXE%"=="" (
    for %%p in (
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Python\bin\python.exe"
        "C:\Program Files\Python310\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Program Files\Python312\python.exe"
    ) do (
        if exist "%%~p" (
            set "PY_EXE=%%~p"
            goto :found_python
        )
    )
)

:: Проверяем обычный python из PATH, если это не pypy
if "%PY_EXE%"=="" (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        for /f "tokens=*" %%i in ('where python') do (
            echo "%%i" | findstr /i "WindowsApps pypy" >nul
            if errorlevel 1 (
                set "PY_EXE=%%i"
                goto :found_python
            )
        )
    )
)

:found_python
if "%PY_EXE%"=="" (
    echo [ОШИБКА] Не найден стандартный интерпретатор CPython 3.10+!
    echo Установите Python с python.org и поставьте галочку "Add to PATH".
    pause
    exit /b 1
)

echo [OK] Используется интерпретатор: %PY_EXE%

:: 2. Проверка или создание чистого venv
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Создание виртуального окружения .venv...
    if exist ".venv" rd /s /q .venv
    "%PY_EXE%" -m venv .venv
)

:: Проверяем, что venv рабочий (не скопирован с другого пути)
.venv\Scripts\python.exe -c "import sys" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Обнаружен перенесенный или поврежденный .venv. Пересоздаем...
    rd /s /q .venv
    "%PY_EXE%" -m venv .venv
)

:: 3. Проверка и установка зависимостей
echo [INFO] Проверка библиотек (cryptography, pytest, matplotlib)...
.venv\Scripts\python.exe -c "import cryptography, pytest, matplotlib" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Установка зависимостей из requirements.txt...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

:: 4. Запуск всех тестов и экспериментов
echo ======================================================================
echo   СТАРТ ОРКЕСТРАТОРА run_all.py
echo ======================================================================
.venv\Scripts\python.exe run_all.py

echo.
pause