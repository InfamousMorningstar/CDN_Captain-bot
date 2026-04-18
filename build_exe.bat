@echo off
echo ================================================
echo   CDN_Captain — Build Installer .exe
echo ================================================
echo.

echo [1/2] Installing PyInstaller...
pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)

echo [2/2] Building CDN_Captain_Installer.exe...
python -m PyInstaller --onefile --windowed --name "CDN_Captain_Installer" launcher.py
if %errorlevel% neq 0 (
    echo ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

if exist dist\CDN_Captain_Installer.exe (
    copy dist\CDN_Captain_Installer.exe CDN_Captain_Installer.exe >nul
    echo.
    echo ================================================
    echo   SUCCESS!
    echo   CDN_Captain_Installer.exe is ready to share.
    echo.
    echo   Users only need to:
    echo     1. Double-click CDN_Captain_Installer.exe
    echo     2. Choose install folder
    echo     3. Enter Discord Token + Anthropic API key
    echo     4. Click Install and Start Bot
    echo ================================================
) else (
    echo ERROR: .exe not found in dist\ folder.
)

pause
@echo off
echo ================================================
echo   CDN_Captain — Build Installer .exe
echo ================================================
echo.

:: ── PASTE YOUR DISCORD TOKEN BELOW ──────────────
set DISCORD_TOKEN=PASTE_YOUR_TOKEN_HERE
:: ─────────────────────────────────────────────────

if "%DISCORD_TOKEN%"=="PASTE_YOUR_TOKEN_HERE" (
    echo ERROR: Open build_exe.bat and replace PASTE_YOUR_TOKEN_HERE with your Discord token.
    pause
    exit /b 1
)

echo [1/3] Installing PyInstaller...
pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)

echo [2/3] Injecting Discord token and building .exe...
powershell -Command "(Get-Content launcher.py) -replace '__DISCORD_TOKEN__', '%DISCORD_TOKEN%' | Set-Content launcher_build.py"
if %errorlevel% neq 0 (
    echo ERROR: Could not inject token.
    pause
    exit /b 1
)

python -m PyInstaller --onefile --windowed --distpath . --name "CDN_Captain" launcher_build.py
del launcher_build.py 2>nul

echo [3/3] Finalising...
if exist dist\CDN_Captain.exe (
    copy dist\CDN_Captain.exe CDN_Captain.exe >nul
    echo.
    echo ================================================
    echo   SUCCESS!
    echo   CDN_Captain.exe is ready — send it to the admin.
    echo   They only need to enter their Anthropic API key.
    echo ================================================
) else (
    echo ERR