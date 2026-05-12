# このリポジトリ付近の python.exe 一覧（PID / 親PID / コマンドライン全文）
# 使い方: .\run_process_view.ps1
#         .\run_process_view.ps1 -Name notepad.exe

param(
    [string] $Name = 'python.exe'
)

Get-CimInstance Win32_Process -Filter "Name='$Name'" |
    Select-Object ProcessId, ParentProcessId, CommandLine |
    Format-List
