' Launches the H.265 transcoder service with no visible console window.
' Used by the scheduled task created by install-service.bat.
Dim fso, sh, here
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & here & "\run.bat""", 0, False
