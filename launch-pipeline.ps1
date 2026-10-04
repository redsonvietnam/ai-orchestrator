$lock = "D:\ai-orchestrator\runs\launch.lock"
$gate = New-Item -ItemType File -Path $lock -ErrorAction SilentlyContinue
if (-not $gate) {
    Write-Output "launch lock already held, exiting"
    exit 0
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'orchestrator\.py|worker\.py' } | ForEach-Object {
    Write-Output "killing stale $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
if (-not $env:GROQ_API_KEY) { throw "GROQ_API_KEY environment variable is required" }
if (-not $env:GOOGLE_API_KEY) { throw "GOOGLE_API_KEY environment variable is required" }
$models = "groq/openai/gpt-oss-120b,groq/openai/gpt-oss-20b"
Start-Process -FilePath "D:\ai-orchestrator\.venv\Scripts\python.exe" `
    -ArgumentList '-u', 'D:\ai-orchestrator\orchestrator.py', '--model', $models, '--problem-file', 'D:\ai-orchestrator\runs\todo-problem.txt' `
    -WorkingDirectory "D:\ai-orchestrator" `
    -RedirectStandardOutput "D:\ai-orchestrator\runs\pipe7.stdout.txt" `
    -RedirectStandardError "D:\ai-orchestrator\runs\pipe7.stderr.txt"
Set-Content -Path $lock -Value (Get-Date -Format o)
Write-Output "launched at $(Get-Date -Format HH:mm:ss)"
