' Launches the H.265 transcoder server (no console) WITHOUT the tray icon.
' Headless-only use. The normal logon path (install-service.bat) uses
' pythonw.exe tray.pyw directly instead.
Dim fso, sh, here
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & here & "\run.bat""", 0, False
