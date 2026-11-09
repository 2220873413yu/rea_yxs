Option Explicit
Dim shell, fso, root, pythonPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonPath = root & "\.analysis-tools\pyenv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonPath) Then
    MsgBox "Python environment is missing: " & pythonPath, 16, "Xinyue Helper"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
command = Chr(34) & pythonPath & Chr(34) & " -m xinyue_helper.app"
shell.Run command, 0, False
