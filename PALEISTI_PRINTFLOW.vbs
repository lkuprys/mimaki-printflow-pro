Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\Projektai\TEST"
cmd = Chr(34) & "E:\Projektai\Podbase\CC\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & "E:\Projektai\TEST\main.py" & Chr(34)
WshShell.Run cmd, 0, False
