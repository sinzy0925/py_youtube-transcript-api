# このリポジトリ付近のプロセス一覧（PID / 親PID / コマンドライン全文）
#
# 使い方:
#   .\run_process_view.ps1
#   .\run_process_view.ps1 -Name python.exe
#   .\run_process_view.ps1 -Name bash.exe
#
# 止め方（PowerShell）:
#   1. 下の一覧で止めたい ProcessId（PID）を確認する
#   2. 最後に出る Stop-Process をコピーして実行する
#      Stop-Process -Id 12345,67890 -Force
#
# このリポジトリでよく動いているもの:
#   - python.exe ... a05_pipeline_youtube_to_email.py（要約パイプライン）
#   - bash.exe ... run_pipeline.sh --drain-execute-queue（キューワーカー）
#   - bash.exe ... run_channel.sh（チャンネル連続処理）
#
# キューを止めたあと、ロックが残ることがあります（次回起動で詰まる場合）:
#   Remove-Item -Recurse -Force execute_urls.lock.d -ErrorAction SilentlyContinue
#   Remove-Item -Force execute_urls.lock -ErrorAction SilentlyContinue
#
# キューに残した URL を消す場合:
#   Clear-Content execute_urls.txt

param(
    [string] $Name = 'python.exe'
)

Write-Host '=== プロセス一覧 ===' -ForegroundColor Cyan
Write-Host "対象: $Name"
Write-Host ''
Write-Host '[止め方] 一覧の ProcessId を使う:  Stop-Process -Id <PID> -Force'
Write-Host '  目安: 子の python -> 親の bash (--drain-execute-queue / run_channel.sh) の順'
Write-Host '  ロック残り: Remove-Item -Recurse -Force execute_urls.lock.d'
Write-Host ''

$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq $Name })

if ($processes.Count -eq 0) {
    Write-Host "($Name は実行中なし)" -ForegroundColor Yellow
    exit 0
}

$processes |
    Select-Object ProcessId, ParentProcessId, CommandLine |
    Format-List

$ids = @($processes | ForEach-Object { $_.ProcessId })
$idList = $ids -join ','

Write-Host ''
Write-Host '=== 停止コマンド（コピーして実行） ===' -ForegroundColor Cyan
Write-Host "Stop-Process -Id $idList -Force" -ForegroundColor Green
