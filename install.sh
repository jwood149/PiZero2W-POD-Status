#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo ./install.sh" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR=/opt/pod-status
STATE_DIR=/var/lib/pod-status
SERVICE_USER=pod-status
CONFIG_TXT=/boot/firmware/config.txt

if [[ ! -f "$CONFIG_TXT" ]]; then
  CONFIG_TXT=/boot/config.txt
fi

echo "==> Installing system packages"
apt-get update
apt-get install -y \
  python3 python3-venv python3-pip \
  fonts-dejavu-core \
  libjpeg-dev libfreetype6-dev zlib1g-dev

echo "==> Enabling SPI in $CONFIG_TXT"
if grep -qE '^\s*#\s*dtparam=spi=on' "$CONFIG_TXT"; then
  sed -i 's/^\s*#\s*dtparam=spi=on/dtparam=spi=on/' "$CONFIG_TXT"
elif ! grep -qE '^\s*dtparam=spi=on' "$CONFIG_TXT"; then
  echo "dtparam=spi=on" >> "$CONFIG_TXT"
fi

echo "==> Creating service user '$SERVICE_USER'"
if ! getent passwd "$SERVICE_USER" >/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
for g in spi gpio; do
  if getent group "$g" >/dev/null; then
    usermod -aG "$g" "$SERVICE_USER"
  else
    echo "   note: group '$g' not present on this system, skipping"
  fi
done

echo "==> Copying files to $INSTALL_DIR (root-owned, read-only to service)"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$SRC_DIR/pod_status.py" "$INSTALL_DIR/pod_status.py"
install -m 0644 "$SRC_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"

echo "==> Preparing state directory $STATE_DIR (writable by service)"
mkdir -p "$STATE_DIR"
chown "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR"
chmod 0750 "$STATE_DIR"

echo "==> Creating virtualenv and installing Python deps"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Keep code+venv root-owned so the service can't modify its own binaries.
chown -R root:root "$INSTALL_DIR"
chmod -R a+rX "$INSTALL_DIR"

echo "==> Installing systemd unit"
install -m 0644 "$SRC_DIR/pod-status.service" /etc/systemd/system/pod-status.service
systemctl daemon-reload
systemctl enable pod-status.service

echo
echo "Done. Reboot to enable SPI and start the status panel:"
echo "  sudo reboot"
echo
echo "Or start without rebooting (SPI already enabled):"
echo "  sudo systemctl start pod-status.service"
