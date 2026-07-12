# launcher.ps1 — Lanzar Portfolio Dashboard desde Windows
# USO: .\launcher.ps1 o doble-click en Windows Explorer

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "╔═══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     PORTFOLIO DASHBOARD LAUNCHER          ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Verificar Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "❌ ERROR: Python no encontrado en PATH" -ForegroundColor Red
    Write-Host "Instala Python 3.13+ y agrega a PATH" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "✓ Python detectado: $(python --version)" -ForegroundColor Green

# Verificar BD
$dbPath = ".\data\db\portfolio.duckdb"
if (-not (Test-Path $dbPath)) {
    Write-Host "⚠️  BD no encontrada: $dbPath" -ForegroundColor Yellow
    Write-Host "Creando schema..." -ForegroundColor Yellow
    python ".\code\setup_db.py"
}

# Verificar reqs
$reqsFile = ".\code\requirements.txt"
if (Test-Path $reqsFile) {
    Write-Host "📦 Instalando dependencias..." -ForegroundColor Cyan
    pip install -q -r $reqsFile
}

Write-Host ""
Write-Host "🚀 Iniciando Portfolio Dashboard..." -ForegroundColor Green
Write-Host "📍 Abre: http://localhost:8050" -ForegroundColor Cyan
Write-Host ""

# Ejecutar
python ".\launcher.py"
