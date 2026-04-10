Write-Host "⚠️ Resetting Django database and migrations..." -ForegroundColor Yellow

# 1. Delete SQLite DB if exists
if (Test-Path "db.sqlite3") {
    Remove-Item "db.sqlite3" -Force
    Write-Host "✔ Deleted db.sqlite3"
}
else {
    Write-Host "ℹ db.sqlite3 not found"
}

# 2. List of apps to clear migrations
$apps = @(
    "accounts",
    "tracking",
    "visits",
    "notifications",
    "masters"
)

foreach ($app in $apps) {
    $migrationsPath = Join-Path $app "migrations"

    if (Test-Path $migrationsPath) {
        Get-ChildItem $migrationsPath -Filter "*.py" |
            Where-Object { $_.Name -ne "__init__.py" } |
            Remove-Item -Force

        Write-Host "✔ Cleared migrations for $app"
    }
    else {
        Write-Host "ℹ No migrations folder for $app"
    }
}

Write-Host "✅ Reset completed successfully." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  python manage.py makemigrations"
Write-Host "  python manage.py migrate"
Write-Host "  python manage.py createsuperuser"
