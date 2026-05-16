# Pi Zero 2W — Argon POD Status Panel

Single-page system status panel for the Argon POD 2.8" TFT (ILI9341, 320×240) on a headless Pi Zero 2W. Shows hostname, IP addresses, CPU usage / clock / temperature, RAM, disk, and uptime — refreshes every 2 seconds.

Companion to [PiZero2W-PINN-ArgonPOD](../PiZero2W-PINN-ArgonPOD/) — that repo gets the POD usable in PINN; this one gives the TFT a job on the installed OS.

---

## What it looks like

```
hostname              OK 12:34:56 UTC
─────────────────────────────────────────
wlan0   192.168.1.42
eth0    192.168.1.43
─────────────────────────────────────────
CPU  ████████░░  23.4%   1.20GHz  45.2°C
RAM  █████░░░░░  52.1%   508/976MB
Swap ░░░░░░░░░░   0.0%   0/512MB
Disk ███░░░░░░░  31.0%   4/14GB

up 2d 14h 7m                          UV
```

Screen elements:
- **Clock:** UTC, sourced from systemd-timesyncd. `OK` (green) next to the time means NTP is synced; `NO` (red) means it hasn't synced yet (or timesyncd isn't running).
- **Bars:** CPU% with current clock speed and SoC temperature; RAM used/total in MB; Swap (covers both real swap and zram-backed swap — psutil sums them); root disk used/total in GB.
- **Throttle indicator (bottom right):** parses `vcgencmd get_throttled`. Blank = clean. `UV` (red) = currently under-voltage. `THR` (red) = currently throttled. `CAP` (amber) = ARM frequency or soft-temp cap active. `△` (amber) = throttled or under-voltage at some point since boot but ok right now.

---

## Target

- **OS:** Raspberry Pi OS Lite (Trixie) on a Pi Zero 2W
- **Display:** Argon POD 2.8" TFT, ILI9341, SPI0 CE0, DC=GPIO22, RST=GPIO27
- **Backlight:** wired to 3V3 on the POD — always on, no GPIO needed
- **Buttons:** Argon POD 4-button strip on GPIO 16 / 20 / 21 / 26

Should also work on Bookworm and other ARMv7/v8 Pis with the same TFT wiring.

---

## Button mapping

| Button | GPIO | Action |
|---|---|---|
| 1 | 16 | Cycle rotation (0° → 90° → 180° → 270° → 0°) |
| 2 | 20 | Reserved (future multi-page nav) |
| 3 | 21 | Reserved (future multi-page nav) |
| 4 | 26 | Toggle screen on/off |

State (rotation + on/off) is persisted to `/var/lib/pod-status/state.json` and survives reboots.

> Screen on/off draws an all-black frame and stops refreshing. The POD's backlight is hardwired to 3V3, so the panel will still glow faintly when "off" — true power-off would require a hardware mod to put the backlight on a GPIO.

---

## How it talks to the display

Direct SPI via [`luma.lcd`](https://luma-lcd.readthedocs.io/) — no framebuffer device, no `fb_ili9341` kernel module, no `bcm_host` / legacy userland. This is intentional: it sidesteps the Bookworm/Trixie removal of the legacy graphics stack that bites the PINN-stage `fbcp` build.

If you previously enabled the `tft9341` overlay in `/boot/firmware/config.txt`, **remove it on the installed OS** — `luma.lcd` and `fb_ili9341` will fight over the same SPI device. Only PINN needs that overlay.

---

## Install

On the Pi (SSH in):

```bash
git clone https://github.com/jwood149/PiZero2W-POD-Status.git
cd PiZero2W-POD-Status
sudo ./install.sh
sudo reboot
```

The installer:
- Installs system Python plus `python3-pil` (Pillow), `python3-psutil`, `fonts-dejavu-core`, and `libraspberrypi-bin` (provides `vcgencmd`)
- Enables `dtparam=spi=on` in `config.txt` (idempotent)
- Creates an unprivileged system user `pod-status` and adds it to the `spi` + `gpio` groups
- Copies sources to `/opt/pod-status/` (root-owned, read-only to the service)
- Creates a virtualenv at `/opt/pod-status/venv` **with `--system-site-packages`** so apt's Pillow and psutil are used directly — no slow pip source-compile
- pip-installs `luma.lcd`, `gpiozero`, `lgpio` (which all have piwheels-cached wheels for armv7l)
- Creates `/var/lib/pod-status/` (writable only by the service user, mode 0750)
- Installs and enables `pod-status.service`

After reboot, the panel comes up shortly after `network-online.target`.

---

## Security model

The service runs as a dedicated unprivileged system user `pod-status` with no login shell, no home directory, and three group memberships: `spi` (for `/dev/spidev0.0`), `gpio` (for `/dev/gpiochip0`), and `video` (for `/dev/vcio`, used by `vcgencmd` for throttle/undervolt detection). Nothing else.

`pod-status.service` adds the standard systemd sandbox layer on top:

| Directive | What it blocks |
|---|---|
| `User=pod-status` + `CapabilityBoundingSet=` (empty) | No root, no capabilities — can't bind low ports, can't `mount`, can't `chown`, can't `setuid`, nothing |
| `ProtectSystem=strict` + `ReadWritePaths=/var/lib/pod-status` | Whole filesystem is read-only except the state dir |
| `ProtectHome=yes` | `/home`, `/root`, `/run/user` invisible |
| `PrivateTmp=yes` | Private `/tmp` |
| `DevicePolicy=closed` + `DeviceAllow=/dev/spidev0.0`, `/dev/gpiochip0`, `/dev/vcio` (rw) | Only the three devices it actually needs |
| `NoNewPrivileges=yes` | Can't gain privileges via setuid binaries |
| `ProtectKernelTunables/Modules/Logs=yes` | Can't poke `/proc/sys`, can't load modules, can't read kernel ring buffer |
| `RestrictNamespaces=yes`, `RestrictRealtime=yes`, `RestrictSUIDSGID=yes` | Can't create namespaces, can't request RT scheduling, can't create setuid files |
| `LockPersonality=yes`, `MemoryDenyWriteExecute=yes` | Can't change exec personality, can't allocate W+X memory (no JIT) |
| `SystemCallFilter=@system-service` minus `@privileged @resources` | Syscall surface trimmed to the @system-service set |

If `pod_status.py` ever had a bug or vulnerability, the blast radius is its own state dir. It can't modify its own code (root-owned `/opt/pod-status`), can't touch the rest of the filesystem, can't escalate, and can't speak to any device other than the SPI port and the GPIO controller.

To verify the sandbox is active after install:

```bash
systemd-analyze security pod-status
```

A score under ~2.0 is "safe" by systemd's reckoning.

---

## Manage the service

```bash
sudo systemctl status pod-status
sudo systemctl restart pod-status
sudo journalctl -u pod-status -f
```

---

## Customizing

Edit `/opt/pod-status/pod_status.py` (root-owned — use `sudo`) and `sudo systemctl restart pod-status`.

Common tweaks:

| Want to | Change |
|---|---|
| Different refresh rate | `REFRESH_SECONDS` near the top |
| Different fonts | `FONT_REGULAR` / `FONT_BOLD` paths |
| Different display GPIO wiring | `GPIO_DC`, `GPIO_RST` constants |
| Different button wiring | `BTN_ROTATE`, `BTN_TOGGLE` constants |
| Reset persisted state | `sudo rm /var/lib/pod-status/state.json && sudo systemctl restart pod-status` |

Rotation is button-driven (no code edit needed). The default rotation on first run is 0°; press Button 1 to cycle through 90° → 180° → 270° → 0°. The setting is remembered.

---

## Why not fbcp?

`fbcp` mirrors HDMI to the TFT — useful when something else (PINN, RetroPie, EmulationStation) owns the screen. On a headless Pi with no desktop, there's no HDMI source worth mirroring, and `fbcp` itself drags in the legacy `bcm_host` userland that Bookworm and Trixie removed. Drawing to the TFT directly over SPI is both simpler and OS-version-portable.

See [PiZero2W-PINN-ArgonPOD/README.md](../PiZero2W-PINN-ArgonPOD/README.md) for the cases where `fbcp` is still the right tool (PINN, RetroPie).

---

## Troubleshooting

**Screen stays black after reboot**
- Check `dtparam=spi=on` is in `/boot/firmware/config.txt`
- Confirm no `dtoverlay=tft9341` / `dtoverlay=fb_ili9341` line is present (PINN-only)
- `ls /dev/spidev0.0` should exist
- `sudo systemctl status pod-status` for service errors

**ImportError on first run**
- Confirm the venv was created: `ls /opt/pod-status/venv/bin/python`
- Re-run `sudo ./install.sh`

**Wrong colors / mirror image**
- Adjust `rotate=` (0/1/2/3) in the `ili9341(...)` call

**IPs show as "—"**
- Wait — the service starts after `network-online.target` but DHCP may not have completed yet on first boot. The panel refreshes every 2s and will pick up the IP when it appears.
