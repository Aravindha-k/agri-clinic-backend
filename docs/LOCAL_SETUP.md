# Local Setup (Development)

## 1. Create and activate virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2. Install dependencies

```powershell
pip install -r requirements.txt
```

## 3. Configure environment

Copy [`.env.local.example`](../.env.local.example) to `.env` (see also [`.env.example`](../.env.example)):

- `APP_ENV=local`
- `DEBUG=True`
- `ALLOWED_HOSTS=localhost,127.0.0.1,YOUR_LAN_IP` — replace `YOUR_LAN_IP` for phone testing
- `CORS_ALLOW_ALL_ORIGINS=true` (local only)

For physical Android / LAN setup, follow [LOCAL_NETWORK_CONFIGURATION.md](../LOCAL_NETWORK_CONFIGURATION.md).

## 4. Run migrations and start server

```powershell
python manage.py migrate
.\scripts\run_dev_server.ps1
```

Use `0.0.0.0` so devices on your Wi-Fi can reach the API.

On **Windows**, prefer `scripts/run_dev_server.ps1` (runs with `--noreload`). The default autoreloader can crash with `WinError 1450` after heavy dev sessions because it scans the entire `.venv` tree. Restart the script after backend code changes.
## 5. Optional local production check

```powershell
$env:APP_ENV='production'; $env:DEBUG='False'; python manage.py check --deploy
```
