Option Explicit
Dim fs, root, shell, python, app
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = root & "\.analysis-tools\pyenv\Scripts\pythonw.exe"
app = root & "\auto_infantry\app.pyw"
shell.Run """" & python & """ """ & app & """", 1, False
