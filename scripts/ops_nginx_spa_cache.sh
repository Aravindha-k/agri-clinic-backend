#!/usr/bin/env bash
# Read-only audit or apply Nginx Cache-Control for Vite Admin SPA.
# Usage: MODE=audit|apply ./scripts/ops_nginx_spa_cache.sh
set -euo pipefail

MODE="${MODE:-audit}"
echo "=== MODE=${MODE} ==="

echo "=== nginx -T (filtered) ==="
sudo nginx -T 2>/dev/null | tee /tmp/nginx_full_t.txt | \
  grep -nE 'server_name|root |index |location |try_files|Cache-Control|expires|add_header|proxy_pass|alias |include |listen ' \
  | head -n 400 || true

echo
echo "=== Candidate config files ==="
sudo grep -RIlE 'index\.html|/assets|try_files|agri-admin|admin-frontend|dist' \
  /etc/nginx 2>/dev/null || true

echo
echo "=== Vite SPA roots ==="
shopt -s nullglob
for d in /var/www/* /var/www/*/*; do
  if [[ -f "$d/index.html" && -d "$d/assets" ]]; then
    echo "SPA_ROOT=$d"
    ls -la "$d/index.html" | head -n 1 || true
    ls "$d/assets"/index-*.js 2>/dev/null | head -n 3 || true
  fi
done
shopt -u nullglob

find_asset() {
  local ext="$1"
  grep -oE "/assets/index-[A-Za-z0-9_-]+\\.${ext}" \
    /var/www/*/index.html /var/www/*/*/index.html 2>/dev/null \
    | head -n 1 | sed 's/.*://' || true
}

print_headers() {
  local path="$1"
  echo "--- HEAD ${path} ---"
  curl -sI "http://127.0.0.1${path}" | tr -d '\r' \
    | grep -iE 'HTTP/|cache-control|content-type|expires|etag|last-modified|location' || true
}

echo
echo "=== Current response headers ==="
for path in / /index.html /masters/crops /healthz/; do
  print_headers "$path"
done
ASSET_JS="$(find_asset js)"
ASSET_CSS="$(find_asset css)"
echo "ASSET_JS=${ASSET_JS}"
echo "ASSET_CSS=${ASSET_CSS}"
[[ -n "${ASSET_JS}" ]] && print_headers "${ASSET_JS}"
[[ -n "${ASSET_CSS}" ]] && print_headers "${ASSET_CSS}"

identify_conf() {
  local f root
  for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [[ -f "$f" ]] || continue
    if sudo grep -q 'try_files' "$f" && sudo grep -qE 'index\.html|/assets' "$f"; then
      echo "$f"
      return 0
    fi
  done
  for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [[ -f "$f" ]] || continue
    root="$(sudo awk '/^[[:space:]]*root /{print $2}' "$f" | tr -d ';' | head -n1)"
    if [[ -n "$root" && -f "${root}/index.html" && -d "${root}/assets" ]]; then
      echo "$f"
      return 0
    fi
  done
  return 1
}

if [[ "${MODE}" == "audit" ]]; then
  CONF="$(identify_conf || true)"
  echo "ACTIVE_SPA_CONF_CANDIDATE=${CONF:-NONE}"
  if [[ -n "${CONF:-}" ]]; then
    echo "=== FULL SITE FILE ${CONF} ==="
    sudo cat "${CONF}"
  fi
  echo "AUDIT_ONLY_DONE=1"
  exit 0
fi

echo
echo "=== APPLY ==="
CONF="$(identify_conf)"
echo "ACTIVE_SPA_CONF=${CONF}"
BACKUP="/tmp/nginx_spa_backup_$(date +%Y%m%d%H%M%S).conf"
sudo cp -a "${CONF}" "${BACKUP}"
echo "BACKUP=${BACKUP}"

sudo python3 - "${CONF}" <<'PY'
import re
import sys
from pathlib import Path

conf_path = Path(sys.argv[1])
text = conf_path.read_text(encoding="utf-8", errors="replace")
print("PATCHING", conf_path)

# Strip previous marker blocks
text = re.sub(
    r"\n?[ \t]*# BEGIN AGRICLINIC_SPA_CACHE.*?# END AGRICLINIC_SPA_CACHE\n?",
    "\n",
    text,
    flags=re.S,
)
# Strip previous HTML cache inject lines
text = re.sub(
    r"\n[ \t]*# AGRICLINIC_SPA_HTML_CACHE\n[ \t]*add_header Cache-Control \"no-cache, must-revalidate\";\n?",
    "\n",
    text,
)

m2 = re.search(r"^([ \t]*)location\s+/\s*\{", text, re.M)
if not m2:
    raise SystemExit("Could not find location / block")
indent = m2.group(1)
assets_block = f"""
{indent}# BEGIN AGRICLINIC_SPA_CACHE
{indent}location ^~ /assets/ {{
{indent}    expires 1y;
{indent}    add_header Cache-Control "public, max-age=31536000, immutable";
{indent}    try_files $uri =404;
{indent}}}
{indent}location = /index.html {{
{indent}    add_header Cache-Control "no-cache, must-revalidate";
{indent}}}
{indent}# END AGRICLINIC_SPA_CACHE
"""
patched = text[: m2.start()] + assets_block + text[m2.start() :]

# Inject no-cache into exact location / block
for match in re.finditer(r"^([ \t]*)location\s+/\s*\{", patched, re.M):
    line_start = match.start()
    brace = patched.find("{", line_start)
    depth = 0
    end = None
    for i in range(brace, len(patched)):
        ch = patched[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise SystemExit("Unbalanced braces in location /")
    block = patched[brace + 1 : end]
    if "AGRICLINIC_SPA_HTML_CACHE" not in block:
        inject = (
            f"\n{match.group(1)}    # AGRICLINIC_SPA_HTML_CACHE\n"
            f'{match.group(1)}    add_header Cache-Control "no-cache, must-revalidate";\n'
        )
        patched = patched[: brace + 1] + inject + patched[brace + 1 :]
    break

conf_path.write_text(patched, encoding="utf-8")
print("WROTE", conf_path)
print("--- PATCHED FILE ---")
print(conf_path.read_text(encoding="utf-8", errors="replace"))
PY

echo "=== nginx -t ==="
if ! sudo nginx -t; then
  echo "NGINX_T_FAILED=1"
  sudo cp -a "${BACKUP}" "${CONF}"
  sudo nginx -t || true
  exit 1
fi
echo "NGINX_T_OK=1"

echo "=== reload nginx ==="
sudo systemctl reload nginx
echo "NGINX_RELOAD_OK=1"
sleep 1

ASSET_JS="$(find_asset js)"
ASSET_CSS="$(find_asset css)"
echo "ASSET_JS=${ASSET_JS}"
echo "ASSET_CSS=${ASSET_CSS}"
echo "=== POST headers ==="
for path in / /index.html /masters/crops /masters/crops/55/problems /api/v1/ /healthz/; do
  print_headers "$path"
done
[[ -n "${ASSET_JS}" ]] && print_headers "${ASSET_JS}"
[[ -n "${ASSET_CSS}" ]] && print_headers "${ASSET_CSS}"

echo "=== bundle marker ==="
if [[ -n "${ASSET_JS}" ]]; then
  if curl -s "http://127.0.0.1${ASSET_JS}" | grep -q "Manage Pest"; then
    echo "JS_HAS_MANAGE_PEST=YES"
  else
    echo "JS_HAS_MANAGE_PEST=NO"
  fi
fi
echo "APPLY_DONE=1"
