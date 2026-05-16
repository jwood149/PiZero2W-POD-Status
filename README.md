# Pi Zero 2W — Argon POD Status Panel

Multi-page system status panel for the Argon POD 2.8" TFT (ILI9341, 320×240) on a headless Pi Zero 2W. Two pages today (stats + system info), cycled with a POD button. Refreshes every 2 seconds.

Companion to [PiZero2W-PINN-ArgonPOD](../PiZero2W-PINN-ArgonPOD/) — that repo gets the POD usable in PINN; this one gives the TFT a job on the installed OS.

---

## What it looks like

### Page 1 — Stats

```
hostname                 12:34:56 UTC
─────────────────────────────────────────
wlan0   192.168.1.42
eth0    192.168.1.43
─────────────────────────────────────────
CPU  ██████░░░░  23.4%    1.2GHz   45°C
RAM  █████░░░░░  52.1%    508/976M
Swap ░░░░░░░░░░   0.0%    off
Disk ███░░░░░░░  31.0%    4/14G

Load  0.42  0.31  0.28
Procs 178t  2R  174S  0Z  0T

up 2d 14h 7m              UV     1/2
```

### Page 2 — System

```
hostname                 12:34:56 UTC
─────────────────────────────────────────
Model   Raspberry Pi Zero 2 W
OS      Raspberry Pi OS Lite (Trixie)
Ver     13 (trixie)
Kernel  6.6.51-rpt2-v7
─────────────────────────────────────────
SSH       active
Connect   inactive
NTP       synced
─────────────────────────────────────────
▶ next    ↻ rotate    ☀☾ on/off

up 2d 14h 7m                     2/2
```

### Screen elements

- **Clock (header, both pages):** UTC, sourced from systemd-timesyncd. NTP sync state lives on Page 2 (under services) rather than the header, to keep the header uncluttered.
- **Stats bars (Page 1):** CPU% with current clock speed and SoC temp (the Pi Zero 2W has one die-temperature sensor that covers CPU + GPU); RAM used/total in MB; Swap (covers both real swap and zram-backed swap — psutil sums them); root disk used/total in GB.
- **Load average (Page 1):** 1/5/15-min load. The 1-min value turns amber when it meets or exceeds the core count (4 on a Pi Zero 2W) — sustained load over that means saturation.
- **Process counts (Page 1):** total / Running / Sleeping / Zombie / Stopped. Zombie and Stopped counts turn amber if nonzero.
- **System info (Page 2):** Pi model from `/proc/device-tree/model`, OS pretty name + version from `/etc/os-release`, kernel from `uname -r`.
- **Service status (Page 2):** `systemctl is-active` results for the services in `TRACKED_SERVICES` (default: `ssh`, `rpi-connect`). Plus NTP synced/not-synced from `/run/systemd/timesync/synchronized`. Green when active/synced, dim otherwise. Edit the list in [pod_status.py](pod_status.py) to add more (e.g. `avahi-daemon`, `NetworkManager`, `fail2ban`).
- **Button legend (Page 2):** ▶ = next page (Button 1 / GPIO 16), ↻ = cycle rotation (Button 2 / GPIO 20), ☀☾ = toggle screen on/off (Button 4 / GPIO 26).
- **Throttle indicator (footer, both pages):** parses `vcgencmd get_throttled`. Blank = clean. `UV` (red) = currently under-voltage. `THR` (red) = currently throttled. `CAP` (amber) = ARM frequency or soft-temp cap active. `△` (amber) = throttled or under-voltage at some point since boot but ok right now.
- **Page indicator (footer, both pages):** `N/total` in the bottom-right corner.

### Background image

The installer generates a stylized greyscale raspberry at `/opt/pod-status/background.png` by default (see [generate_background.py](generate_background.py) — overlapping circles in a heart-shape with two leaves, no trademark concerns). The renderer composites it under everything, pre-darkened to ~20% brightness so it stays subtle and the foreground text remains high-contrast.

To use your own image instead:

```bash
sudo cp my-pi-logo.png /opt/pod-status/background.png
sudo systemctl restart pod-status
```

Any size works — it's resized to 320×240 on load. To regenerate the default after overwriting:

```bash
sudo /opt/pod-status/venv/bin/python /opt/pod-status/generate_background.py --force
sudo systemctl restart pod-status
```

To go without a background entirely:

```bash
sudo rm /opt/pod-status/background.png
sudo systemctl restart pod-status
```

The renderer falls back to plain black when the file is absent.

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
| 1 | 16 | Cycle page (1 → 2 → … → 1) |
| 2 | 20 | Cycle rotation (0° → 90° → 180° → 270° → 0°) |
| 3 | 21 | Reserved |
| 4 | 26 | Toggle screen on/off |

State (current page + rotation + on/off) is persisted to `/var/lib/pod-status/state.json` and survives reboots.

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
- Installs system Python plus `python3-pil` (Pillow), `python3-psutil`, `python3-gpiozero`, `python3-pigpio`, `pigpio` (daemon), `fonts-dejavu-core`, `libraspberrypi-bin` (provides `vcgencmd`), and Pillow source-build deps as a fallback
- Enables `pigpiod` — handles all GPIO access so our service never needs `/dev/mem` or `/dev/gpiochip0`
- Enables `dtparam=spi=on` in `config.txt` (idempotent)
- Creates an unprivileged system user `pod-status` and adds it to the `spi` + `video` groups
- Copies sources to `/opt/pod-status/` (root-owned, read-only to the service)
- Creates a virtualenv at `/opt/pod-status/venv` **with `--system-site-packages`** so apt's Pillow / psutil / gpiozero / pigpio client lib are used directly — no slow pip source-compile
- pip-installs only `luma.lcd` (the one library with no apt package)
- Creates `/var/lib/pod-status/` (writable only by the service user, mode 0750)
- Installs and enables `pod-status.service`

After reboot, the panel comes up shortly after `network-online.target`.

---

## Security model

The service runs as a dedicated unprivileged system user `pod-status` with no login shell, no home directory, and three group memberships: `spi` (for `/dev/spidev0.0`), `gpio` (for `/dev/gpiomem` — luma.lcd uses RPi.GPIO internally for the display's DC/RST pins, and RPi.GPIO talks to the kernel-restricted `/dev/gpiomem` rather than full `/dev/mem` when running as non-root), and `video` (for `/dev/vcio`, used by `vcgencmd`).

Button input is routed separately through `pigpiod` — gpiozero with `GPIOZERO_PIN_FACTORY=pigpio` connects to the daemon's localhost socket instead of touching GPIO hardware directly.

`pod-status.service` adds the standard systemd sandbox layer on top:

| Directive | What it blocks |
|---|---|
| `User=pod-status` + `CapabilityBoundingSet=` (empty) | No root, no capabilities — can't bind low ports, can't `mount`, can't `chown`, can't `setuid`, nothing |
| `ProtectSystem=strict` + `ReadWritePaths=/var/lib/pod-status` | Whole filesystem is read-only except the state dir |
| `ProtectHome=yes` | `/home`, `/root`, `/run/user` invisible |
| `PrivateTmp=yes` | Private `/tmp` |
| `DevicePolicy=closed` + `DeviceAllow=/dev/spidev0.0`, `/dev/gpiomem`, `/dev/vcio` (rw) | Only the three devices it actually needs. Button GPIO goes through pigpiod (socket, not device); display DC/RST goes through `/dev/gpiomem` (kernel-restricted GPIO register window) |
| `NoNewPrivileges=yes` | Can't gain privileges via setuid binaries |
| `ProtectKernelTunables/Modules/Logs=yes` | Can't poke `/proc/sys`, can't load modules, can't read kernel ring buffer |
| `ProtectProc=` left at default | Service can *see* all processes in `/proc/` (needed for the process-count breakdown on Page 1). It still can't modify them — `NoNewPrivileges` + empty capability set means no signals, no ptrace, nothing. Same model as `top`/`htop` running as your user. |
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

## Testing the throttle / undervoltage indicator

Real undervoltage happens when the Pi's input drops below ~4.65V — hard to trigger reproducibly without a marginal supply. Two ways to see the indicator without that:

**Software fake (no hardware needed):**

```bash
sudo systemctl edit pod-status
```

Add the override:
```
[Service]
Environment=POD_STATUS_FAKE_THROTTLED=0x1
```

Then `sudo systemctl restart pod-status`. Values you can try:
- `0x1` — currently under-voltage → `UV` red
- `0x4` — currently throttled → `THR` red
- `0x2` or `0x8` — frequency / soft-temp cap → `CAP` amber
- `0x10000` — sticky bit only → `△` amber
- `0x0` (or remove the line) — clean

**Physical (real undervoltage):**

Run CPU stress on a marginal supply or with a thin/long USB cable:
```bash
sudo apt install stress-ng
stress-ng --cpu 4 --timeout 60s
```

A quality 5V/2.5A supply with a short thick cable should *not* trigger UV. If yours does, that's diagnostic — your power chain is the weak link.

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
