# Локальный запуск из корня проекта: проверка окружения -> кластер PostgreSQL -> seed.py -> Uvicorn app:app.
# Port — порт HTTP-сайта (по умолчанию 8000); порт отдельной БД остаётся 55433.
# Использует .venv, .env и .local/postgres, браузер открывается пользователем.
param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Сначала выполните python -m venv .venv и установите requirements.txt.'
}
if (-not (Test-Path -LiteralPath '.env')) {
    throw 'Сначала выполните .\.venv\Scripts\python.exe scripts\setup_local_db.py или настройте .env вручную.'
}
# Этот кластер принадлежит только TechStore. Остальные службы PostgreSQL не затрагиваются.
$dataPath = Join-Path $PSScriptRoot '.local\postgres'
if (Test-Path -LiteralPath $dataPath) {
    $versionText = (Get-Content -LiteralPath (Join-Path $dataPath 'PG_VERSION') -Raw).Trim()
    $pgCtl = Join-Path $env:ProgramFiles "PostgreSQL\$versionText\bin\pg_ctl.exe"
    & $pgCtl -D $dataPath status *> $null
    if ($LASTEXITCODE -ne 0) {
        & $pgCtl -D $dataPath -l (Join-Path $PSScriptRoot '.local\postgres.log') -o '-h 127.0.0.1 -p 55433' start
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось запустить локальный PostgreSQL.' }
    }
}
& $pythonPath seed.py
if ($LASTEXITCODE -ne 0) { throw 'Проверьте DATABASE_URL и доступность PostgreSQL.' }
Write-Host "TechStore: http://localhost:$Port"
& $pythonPath -m uvicorn app:app --host 127.0.0.1 --port $Port
