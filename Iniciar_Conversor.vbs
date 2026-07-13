Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonExe = "C:\Users\mateu\anaconda3\envs\docling\pythonw.exe"
scriptPath = scriptDir & "\converter_gui.py"

WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & pythonExe & """ """ & scriptPath & """", 1, False
