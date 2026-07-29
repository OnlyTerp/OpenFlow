' OpenFlow — silent launcher (no CMD windows).
' Install root should be %LOCALAPPDATA%\OpenFlow after: python -m openflow install
Option Explicit
Dim sh, fso, dir, pyw, localApp, candidates, i, exitCode
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

' Single entry: python -m openflow start. Wait so we can show a visible
' error if the desktop shell is missing or unpatched (pythonw has no console).
exitCode = sh.Run("""" & pyw & """ -m openflow start", 0, True)
If exitCode = 2 Then
  MsgBox "OpenFlow could not find the Wispr Flow desktop app." & vbCrLf & _
         "Please install Wispr Flow from https://wisprflow.ai first, then run OpenFlow again.", _
         vbCritical, "OpenFlow — Desktop shell not found"
ElseIf exitCode = 4 Then
  MsgBox "OpenFlow could not patch the Wispr Flow desktop app." & vbCrLf & _
         "Close Wispr Flow and run: python -m openflow patch", _
         vbCritical, "OpenFlow — Patch failed"
ElseIf exitCode <> 0 Then
  MsgBox "OpenFlow launcher failed (code " & exitCode & ")." & vbCrLf & _
         "Check the logs folder in: " & dir, _
         vbCritical, "OpenFlow — Launch failed"
End If
