' Double-click this to start Rocky with no console window flash at all.
' It just runs start_rocky_windows.ps1 completely hidden in the background.
'
' Tip: right-click this file -> Send to -> Desktop (create shortcut), then
' right-click that new shortcut -> Properties -> Change Icon... to give it
' a custom picture (any .ico file, or a sprite converted to .ico) so it
' looks like a real clickable app icon instead of a plain script file.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript = scriptDir & "\start_rocky_windows.ps1"

shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & psScript & """", 0, False
