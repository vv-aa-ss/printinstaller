@echo off
Setlocal Enableextensions
Setlocal Enabledelayedexpansion

RMDIR /S /Q %appdata%\..\Local\QuickScanTool

PUSHD %UserProfile%\Desktop

FOR /r %%X in (*.lnk) do (
	SET shortcut="%%X"
	CALL :IsTargetQuickScan !shortcut!,isQuickScan
	IF !isQuickScan!==0 (
 		ECHO Shortcut   ld!shortcut!
		DEL "!shortcut!"
	)
)

ECHO ----------------------------------------------------------------
ECHO.
)

GOTO :END

:IsTargetQuickScan
SET shortcut=%~1
ECHO SET WshShell = WScript.CreateObject("WScript.Shell")>DecodeShortCut.vbs
ECHO SET Lnk = WshShell.CreateShortcut(WScript.Arguments.Unnamed(0))>>DecodeShortCut.vbs
ECHO wscript.Echo Lnk.TargetPath>>DecodeShortCut.vbs
SET vbscript=cscript //nologo DecodeShortCut.vbs
FOR /f "delims=" %%T in ( ' %vbscript% "%Shortcut%" ' ) do set target=%%T
DEL DecodeShortCut.vbs
REM ECHO Target   %target%


ECHO.%target% | findstr /C:"QuickScan.exe">nul && (SET "%~2=0") || (SET "%~2=1")

EXIT /B 0

:END
REM PAUSE
EXIT /B