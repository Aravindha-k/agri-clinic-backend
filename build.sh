#!/usr/bin/env bash
# Legacy Render build script (sandbox only). Production builds on AWS EC2
# via scripts/deploy_production.sh — do not use Render Postgres.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt
python manage.py collectstatic --noinput
