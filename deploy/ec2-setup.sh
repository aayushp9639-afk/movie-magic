#!/usr/bin/env bash
# ==============================================================================
# Movie Magic — Amazon Linux 2023 (AL2023) EC2 Automated Setup Script
# Run as root or with sudo: sudo bash deploy/ec2-setup.sh
# ==============================================================================
set -euo pipefail

APP_DIR="/home/ec2-user/movie-magic"
APP_USER="ec2-user"
APP_GROUP="ec2-user"
PYTHON_BIN="python3.11"

echo "=========================================================="
echo "🎬 Starting Movie Magic EC2 Deployment Setup on $(uname -s)"
echo "=========================================================="

# 1. Update system packages
echo "📦 Updating OS packages..."
dnf update -y -q

# 2. Install required packages (Python 3.11, pip, git, nginx)
echo "📦 Installing Python 3.11, Git, and Nginx..."
dnf install -y -q ${PYTHON_BIN} ${PYTHON_BIN}-pip git nginx

# 3. Ensure target directory permissions
if [ ! -d "${APP_DIR}" ]; then
    echo "📥 Cloning repository from GitHub..."
    git clone https://github.com/GKExpo/movie-magic.git "${APP_DIR}"
else
    echo "🔄 Existing repository found; pulling latest updates..."
    cd "${APP_DIR}"
    sudo -u ${APP_USER} git pull origin main || true
fi

cd "${APP_DIR}"
chown -R ${APP_USER}:${APP_GROUP} "${APP_DIR}"

# 4. Set up Python virtual environment
echo "🐍 Configuring Python virtual environment..."
if [ ! -d "${APP_DIR}/.venv" ]; then
    sudo -u ${APP_USER} ${PYTHON_BIN} -m venv "${APP_DIR}/.venv"
fi

sudo -u ${APP_USER} "${APP_DIR}/.venv/bin/pip" install --upgrade pip -q
sudo -u ${APP_USER} "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q

# 5. Generate production .env configuration if not already existing
if [ ! -f "${APP_DIR}/.env" ]; then
    echo "🔐 Creating production .env file with generated SECRET_KEY..."
    RANDOM_SECRET=$(sudo -u ${APP_USER} "${APP_DIR}/.venv/bin/python" -c "import secrets; print(secrets.token_hex(32))")
    
    sudo -u ${APP_USER} tee "${APP_DIR}/.env" > /dev/null <<EOF
# Production Environment Configuration for Movie Magic
FLASK_APP=run.py
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=${RANDOM_SECRET}

APP_NAME=Movie Magic
APP_PORT=5000
APP_HOST=127.0.0.1
DEFAULT_CITY=Kolhapur

# Session Security (Set to True if SSL/HTTPS termination is configured)
SESSION_COOKIE_SECURE=False
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax

# AWS Integration Settings
AWS_REGION=ap-south-1
DYNAMODB_TABLE_PREFIX=moviemagic_
DYNAMODB_ENDPOINT_URL=

# Live AWS Mode (uses EC2 IAM instance profile credentials)
USE_AWS_MOCK=False

# Optional SNS Topic ARN (paste your created topic ARN here)
SNS_BOOKING_TOPIC_ARN=
EOF
    chmod 600 "${APP_DIR}/.env"
else
    echo "ℹ️ Existing .env file found at ${APP_DIR}/.env. Preserving existing SECRET_KEY and configuration."
fi

# 6. Install and configure systemd service
echo "⚙️ Configuring systemd service..."
cp "${APP_DIR}/deploy/moviemagic.service" /etc/systemd/system/moviemagic.service
systemctl daemon-reload
systemctl enable moviemagic.service
systemctl restart moviemagic.service

# 7. Configure Nginx reverse proxy
echo "🌐 Configuring Nginx reverse proxy..."
# Ensure default Nginx welcome page does not conflict
if [ -f /etc/nginx/nginx.conf ]; then
    # Make sure ec2-user home directory is traversable by nginx for static files
    chmod 755 /home/ec2-user
fi

cp "${APP_DIR}/deploy/nginx-moviemagic.conf" /etc/nginx/conf.d/moviemagic.conf
nginx -t
systemctl enable nginx
systemctl restart nginx

# 8. Local Verification probe
echo "🩺 Verifying local health check..."
sleep 2
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/health || echo "FAILED")

if [ "${HEALTH_STATUS}" = "200" ]; then
    echo "=========================================================="
    echo "✅ Movie Magic deployed and running successfully!"
    echo "🩺 Health Check Status: HTTP 200 OK"
    echo "🌐 View live status with: systemctl status moviemagic"
    echo "📜 View app logs with:    journalctl -u moviemagic.service -f"
    echo "=========================================================="
else
    echo "⚠️ Warning: Health probe returned code ${HEALTH_STATUS}. Inspecting logs..."
    journalctl -u moviemagic.service -n 20 --no-pager
fi
