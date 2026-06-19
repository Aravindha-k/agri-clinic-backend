# Start local PostgreSQL 18 (requires Administrator).
# Right-click PowerShell -> Run as administrator, then:
#   cd D:\agri_clinic
#   .\scripts\start_postgres.ps1

$serviceName = "postgresql-x64-18"
$svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if (-not $svc) {
    Write-Error "PostgreSQL service '$serviceName' not found. Install PostgreSQL 18 or update the service name in this script."
    exit 1
}

if ($svc.Status -eq "Running") {
    Write-Host "PostgreSQL is already running."
} else {
    Write-Host "Starting $serviceName ..."
    Start-Service $serviceName
    Start-Sleep -Seconds 2
    $svc.Refresh()
    if ($svc.Status -ne "Running") {
        Write-Error "Failed to start PostgreSQL. Check Windows Event Viewer or PostgreSQL logs."
        exit 1
    }
    Write-Host "PostgreSQL started."
}

$pgIsReady = & "C:\Program Files\PostgreSQL\18\bin\pg_isready.exe" -h 127.0.0.1 -p 5432 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Port 5432 is accepting connections."
} else {
    Write-Warning "Service is running but pg_isready failed — wait a few seconds and retry."
}
