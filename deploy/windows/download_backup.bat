@echo off
rem Downloads the server's newest database backup into OneDrive, and keeps the last 7 days there.
rem Run daily by Windows Task Scheduler (deploy/README.md, "Backups"). It uses its own key, which the
rem server only lets fetch the latest backup, so it needs no passphrase.
setlocal
set SERVER=john@162.214.171.209
set KEY=%USERPROFILE%\.ssh\congress_backup
set DEST=%USERPROFILE%\OneDrive\congress-backups
set KEEP_DAYS=7

if not exist "%DEST%" mkdir "%DEST%"
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
set FILE=%DEST%\congress-%TODAY%.dump

rem cmd's ">" keeps the file byte for byte (PowerShell's would change it). Write to .part, then rename.
ssh -i "%KEY%" -o BatchMode=yes -o ConnectTimeout=30 %SERVER% > "%FILE%.part" 2>> "%DEST%\download.log"
if errorlevel 1 goto failed
for %%f in ("%FILE%.part") do if %%~zf LSS 10000000 goto failed
move /y "%FILE%.part" "%FILE%" > nul
echo %date% %time% OK %FILE% >> "%DEST%\download.log"
forfiles /p "%DEST%" /m congress-*.dump /d -%KEEP_DAYS% /c "cmd /c del @path" 2> nul
exit /b 0

:failed
del "%FILE%.part" 2> nul
echo %date% %time% FAILED (see the lines above) >> "%DEST%\download.log"
exit /b 1
