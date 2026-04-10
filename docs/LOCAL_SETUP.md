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

Copy [.env.example](../.env.example) to `.env` and keep these values for local:

- `APP_ENV=local`
- `DEBUG=True`
- Leave `DATABASE_URL` empty to use sqlite
- `ALLOWED_HOSTS=localhost,127.0.0.1`
- `CORS_ALLOW_ALL_ORIGINS=true`

## 4. Run migrations and start server

```powershell
python manage.py migrate
python manage.py runserver
```

## 5. Optional local production check

```powershell
$env:APP_ENV='production'; $env:DEBUG='False'; python manage.py check --deploy
```
