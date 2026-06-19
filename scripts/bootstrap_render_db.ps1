# Bootstrap new Render Postgres after old instance suspended
# Usage:
#   1. Create PostgreSQL in Render Dashboard (see docs/RENDER_DEPLOYMENT.md)
#   2. Copy Internal Database URL from the NEW instance
#   3. Run:
#        .\scripts\bootstrap_render_db.ps1 -DatabaseUrl "postgresql://USER:PASS@dpg-NEW-a/agri_clinic_db"
#   4. Update Render web service DATABASE_URL to the same URL and redeploy

param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,
    [string]$AdminPassword = "",
    [string]$AdminUsername = "renderadmin",
    [string]$Fixture = "local_export_for_render.json",
    [switch]$SkipFixture,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $AdminPassword) {
    $AdminPassword = Read-Host "Bootstrap admin password (for new superuser if needed)" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($AdminPassword)
    $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr)
}

# Update local gitignored env file (never commit)
$envFile = Join-Path $Root "render.production.env"
$lines = @()
if (Test-Path $envFile) {
    $lines = Get-Content $envFile
}
$found = $false
$newLines = foreach ($line in $lines) {
    if ($line -match '^DATABASE_URL=') {
        $found = $true
        "DATABASE_URL=$DatabaseUrl"
    } else {
        $line
    }
}
if (-not $found) {
    $newLines += "DATABASE_URL=$DatabaseUrl"
}
Set-Content -Path $envFile -Value ($newLines -join "`n") -Encoding utf8
Write-Host "Updated render.production.env DATABASE_URL (local only, gitignored)"

# Load production env into process
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
$env:APP_ENV = "production"
$env:RENDER = "true"
$env:BOOTSTRAP_ADMIN_USERNAME = $AdminUsername
$env:BOOTSTRAP_ADMIN_PASSWORD = $AdminPassword

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$args = @("manage.py", "bootstrap_render_db")
if (-not $DryRun) { $args += "--confirm" }
if (-not $SkipFixture -and (Test-Path (Join-Path $Root $Fixture))) {
    $args += @("--fixture", $Fixture)
}

Write-Host "Running: $py $($args -join ' ')"
& $py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Render Dashboard (manual) ===" -ForegroundColor Cyan
Write-Host "1. agri-clinic-backend -> Environment -> DATABASE_URL = (same URL as above)"
Write-Host "2. RENDER_POSTGRES_HOST_SUFFIX = singapore-postgres.render.com"
Write-Host "3. DB_SSL_REQUIRE = false"
Write-Host "4. Manual Deploy (clear build cache optional)"
Write-Host "5. Verify: https://agri-clinic-backend.onrender.com/healthz/"
Write-Host "6. Login: POST /api/v1/auth/login/ with username $AdminUsername"
