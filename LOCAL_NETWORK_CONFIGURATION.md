# Local network / Android device testing — Kavya Agri Clinic

This guide configures Django so a phone on the same Wi-Fi can call the API via your PC’s LAN IP **without** hardcoding that IP in `settings.py`.

## Environment variables

| Variable | Purpose | Example (safe) |
|----------|---------|----------------|
| `APP_ENV` | `local` / `staging` / `production` / … | `local` |
| `DEBUG` | Local debugging | `True` (local only) |
| `ALLOWED_HOSTS` | Comma-separated hostnames (no `http://`, no port) | `localhost,127.0.0.1,YOUR_LAN_IP` |
| `EXTRA_ALLOWED_HOSTS` | Optional hosts **merged** into `ALLOWED_HOSTS` | `YOUR_LAN_IP` |
| `CSRF_TRUSTED_ORIGINS` | Full origins with scheme + port | `http://localhost:8000,http://YOUR_LAN_IP:8000` |
| `EXTRA_CSRF_TRUSTED_ORIGINS` | Optional origins merged into CSRF list | `http://YOUR_LAN_IP:8000` |
| `CORS_ALLOW_ALL_ORIGINS` | Dev convenience for admin SPA | `true` local; **`false` in production** |
| `CORS_ALLOWED_ORIGINS` | Explicit SPA origins when not allowing all | `http://localhost:5173` |

Placeholders such as `YOUR_LAN_IP` are ignored by settings (they never become real hosts).

Configuration lives in **`.env`** (copy from `.env.local.example`). Loaded by `python-dotenv` in `config/settings.py`.

## ALLOWED_HOSTS behaviour

- Production-like `APP_ENV` defaults: deploy hostnames (e.g. Render), never `*`.
- Local defaults: `localhost`, `127.0.0.1`.
- Set `ALLOWED_HOSTS` and/or `EXTRA_ALLOWED_HOSTS` in `.env` for your current LAN IP.
- Entries may include a port or scheme in error; the loader **strips** them for `ALLOWED_HOSTS`.

**Do not** use `ALLOWED_HOSTS=*`.

## CORS

- Local default: `CORS_ALLOW_ALL_ORIGINS=true` (existing project behaviour for Vite admin on `:5173`).
- Production: `CORS_ALLOW_ALL_ORIGINS=false` + explicit `CORS_ALLOWED_ORIGINS`.
- The **mobile app uses JWT** and does not depend on browser CORS for API calls.

## CSRF

- Mobile Bearer JWT APIs are not CSRF-bound.
- Browser/admin cookie flows need `CSRF_TRUSTED_ORIGINS` to include `http://YOUR_LAN_IP:8000` when you open the API host from another origin on LAN.
- Production must keep HTTPS origins only.

## Find your LAN IP

### Windows

```powershell
ipconfig
```

Use **IPv4 Address** under the active Wi-Fi / Ethernet adapter (e.g. `192.168.1.42`). Not `127.0.0.1`.

### Linux

```bash
ip addr
# or
hostname -I
```

### macOS

```bash
ifconfig
# or
ipconfig getifaddr en0
```

Replace every `YOUR_LAN_IP` in `.env` with that address, then **restart** `runserver`.

## Local API on all interfaces

```powershell
cd d:\agri_clinic
.\.venv\Scripts\Activate.ps1
python manage.py runserver 0.0.0.0:8000
```

On startup the log should include something like:

```text
Django boot APP_ENV=local DEBUG=True ALLOWED_HOSTS=['localhost', '127.0.0.1', '192.168.x.x']
```

## Android phone testing

1. Phone and PC on the **same Wi-Fi**.
2. `.env` includes your LAN IP in `ALLOWED_HOSTS` (or `EXTRA_ALLOWED_HOSTS`).
3. Server bound to `0.0.0.0:8000`.
4. Phone browser: `http://YOUR_LAN_IP:8000/healthz/` → `{"status":"ok",...}`.
5. Mobile `.env`: `EXPO_PUBLIC_API_BASE=http://YOUR_LAN_IP:8000/api/v1`.
6. See also `KAVYA_AGRI_CLINIC_PHASE_A_SMOKE_TEST.md`.

## Windows firewall

Allow inbound **TCP 8000** on Private networks (Windows Defender Firewall → Inbound Rules), or allow Python when prompted.

## Common troubleshooting

| Symptom | Fix |
|---------|-----|
| `DisallowedHost: '192.168.x.x:8000'` | Add `192.168.x.x` to `ALLOWED_HOSTS` or `EXTRA_ALLOWED_HOSTS` in `.env`, restart server |
| Phone cannot connect | Same Wi-Fi; `0.0.0.0:8000`; firewall; wrong IP after DHCP renew |
| Still only localhost works | Confirm `.env` is in repo root and restart; check boot log `ALLOWED_HOSTS=` |
| `YOUR_LAN_IP` in boot log | You left the placeholder — replace with a real IPv4 |
| Staging/production | Do not add home LAN IPs; use HTTPS hostnames only |

## Related files

- `config/settings.py` — `env_host_list`, `EXTRA_ALLOWED_HOSTS`, boot log
- `.env.local.example` — local template
- `.env.production.example` — production template
- `mobile/.env.example` — Expo API base for the phone
