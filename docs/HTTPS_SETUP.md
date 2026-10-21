# HTTPS Setup Plan — Nginx on EC2

## Current state (audited 2026-10-21)

- Nginx `sites-enabled/agri-clinic`: `listen 80`, `server_name 13.207.17.117`
- **IP-only, no DNS name** — public CAs (Let's Encrypt included) will not
  issue a certificate for a bare IP address in practice for this flow.
- All API, admin JWT, and (future) attendance device-token traffic is
  currently cleartext HTTP.

## Prerequisite — DNS (operator action required)

1. Choose a hostname, e.g. `api.kavyaagriclinic.in` or `admin.<your-domain>`
   (**do not invent — confirm the actual registered domain with the owner**).
2. Create an `A` record pointing it at `13.207.17.117`.
3. Update the frontend `VITE_API_BASE_URL` (and any mobile-app base URL) to
   the `https://` hostname before cutover.

## Certificate options

| Option | Cost | Notes |
|---|---|---|
| Let's Encrypt via certbot (recommended) | Free | Auto-renewal via systemd timer; needs port 80 open for HTTP-01 challenge |
| AWS ACM | Free | Only usable behind ALB/CloudFront — requires architecture change; not recommended now |
| Commercial cert | Paid | Unnecessary for this deployment |

## Nginx changes (once DNS resolves)

```nginx
# /etc/nginx/sites-enabled/agri-clinic — after certbot runs
server {
    listen 80;
    server_name <your-domain>;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name <your-domain>;
    ssl_certificate     /etc/letsencrypt/live/<your-domain>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-domain>/privkey.pem;
    client_max_body_size 20M;
    root /var/www/agri-admin/agri-clinic-frontend/dist;
    index index.html;
    # ... existing location blocks unchanged (/api/, /admin/, /healthz/,
    #     /static/, /media/, /assets/, SPA fallback) ...
}
```

Commands (operator, after DNS propagation):

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d <your-domain>   # edits config + installs cert
sudo certbot renew --dry-run            # verify auto-renewal
```

## Attendance-relevant note

Attendance device tokens (`X-Device-Token` header) are single-use credentials.
They MUST travel over HTTPS before any real (non-test) device goes live —
treat TLS as a **hard prerequisite for the biometric/pilot phase**, not just
a hardening nicety.

## Cutover checklist

- [ ] DNS A-record created and resolving
- [ ] certbot cert issued; `nginx -t` clean; reload
- [ ] Frontend rebuilt/deployed with `VITE_API_BASE_URL=https://<domain>`
- [ ] Mobile app config updated to HTTPS base URL
- [ ] Security group still allows 443 (and 80 for renewal)
- [ ] `curl https://<domain>/healthz/` returns 200
