#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo or as root." >&2
  exit 1
fi

: "${CCBOT_PLATFORM_URL:?Set CCBOT_PLATFORM_URL, for example https://cybercareai.io}"
: "${CCBOT_ENROLLMENT_TOKEN:?Set CCBOT_ENROLLMENT_TOKEN from CyberCare AI}"

CCBOT_AGENT_VERSION="${CCBOT_AGENT_VERSION:-v0.1.2}"
CCBOT_AGENT_RAW_BASE="${CCBOT_AGENT_RAW_BASE:-https://raw.githubusercontent.com/ZHL-Technology/ccbot-agent/${CCBOT_AGENT_VERSION}}"
CCBOT_AGENT_SOURCE_URL="${CCBOT_AGENT_SOURCE_URL:-${CCBOT_AGENT_RAW_BASE}/ccbot_agent/main.py}"

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 curl ca-certificates openssl iproute2
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 curl ca-certificates openssl iproute
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 curl ca-certificates openssl iproute
  elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 curl ca-certificates openssl iproute2
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm python curl ca-certificates openssl iproute2
  else
    echo "No supported package manager found. Install python3, curl, ca-certificates, openssl, and ss/iproute2 manually." >&2
  fi
}

install_packages

id -u ccbot-agent >/dev/null 2>&1 || useradd --system --home /var/lib/ccbot-agent --shell /usr/sbin/nologin ccbot-agent
install -d -m 0755 /opt/ccbot-agent
install -d -m 0750 -o ccbot-agent -g ccbot-agent /etc/ccbot-agent /var/lib/ccbot-agent

curl -fsSL "${CCBOT_AGENT_SOURCE_URL}" -o /opt/ccbot-agent/ccbot-agent.py
/usr/bin/python3 -m py_compile /opt/ccbot-agent/ccbot-agent.py
chmod 0755 /opt/ccbot-agent/ccbot-agent.py

cat > /etc/ccbot-agent/config.json <<CONFIG
{
  "platform_url": "${CCBOT_PLATFORM_URL%/}",
  "enrollment_token": "${CCBOT_ENROLLMENT_TOKEN}",
  "heartbeat_seconds": 300,
  "report_every_seconds": 86400,
  "state_path": "/var/lib/ccbot-agent/state.json"
}
CONFIG
chown ccbot-agent:ccbot-agent /etc/ccbot-agent/config.json
chmod 0600 /etc/ccbot-agent/config.json

cat > /etc/systemd/system/ccbot-agent.service <<'SERVICE'
[Unit]
Description=CCBot Linux Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ccbot-agent
Group=ccbot-agent
ExecStart=/usr/bin/python3 /opt/ccbot-agent/ccbot-agent.py run
Restart=always
RestartSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/etc/ccbot-agent /var/lib/ccbot-agent

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
if command -v runuser >/dev/null 2>&1; then
  runuser -u ccbot-agent -- /usr/bin/python3 /opt/ccbot-agent/ccbot-agent.py enroll
else
  su -s /bin/sh ccbot-agent -c "/usr/bin/python3 /opt/ccbot-agent/ccbot-agent.py enroll"
fi
systemctl enable --now ccbot-agent
systemctl status ccbot-agent --no-pager
