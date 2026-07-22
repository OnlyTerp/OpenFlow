' OpenFlow — silent launcher (no CMD windows).
' Install root should be %LOCALAPPDATA%\OpenFlow after: python -m openflow install
Option Explicit
Dim sh, fso, dir, pyw, localApp, candidates, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Environment("Process")("PYTHONPATH") = dir

pyw = ""
localApp = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%")
candidates = Array( _
  localApp & "\Programs\Python\Python313\pythonw.exe", _
  localApp & "\Programs\Python\Python312\pythonw.exe", _
  localApp & "\Programs\Python\Python311\pythonw.exe" _
)
For i = 0 To UBound(candidates)
  If fso.FileExists(candidates(i)) Then
    pyw = candidates(i)
    Exit For
  End If
Next
If pyw = "" Then pyw = "pythonw.exe"

' Single entry: python -m openflow start
sh.Run """" & pyw & """ -m openflow start", 0, False
