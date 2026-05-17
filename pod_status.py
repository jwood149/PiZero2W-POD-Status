#!/usr/bin/env python3
"""Argon POD 2.8" TFT status panel for headless Pi Zero 2W."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
from gpiozero import Button
from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9341
from PIL import Image, ImageFont

GPIO_DC = 22
GPIO_RST = 27
SPI_PORT = 0
SPI_DEVICE = 0
SPI_HZ = 24_000_000

BTN_PAGE = 16
BTN_ROTATE = 20
BTN_TOGGLE = 26

WIDTH = 320
HEIGHT = 240
REFRESH_SECONDS = 2
DEBOUNCE_SECONDS = 0.05

PAGES = 2
VALID_ROTATIONS = (0, 2)

STATE_PATH = Path("/var/lib/pod-status/state.json")
DEFAULT_STATE = {"rotation": 0, "screen_on": True, "current_page": 0}

BACKGROUND_PATH = Path("/opt/pod-status/background.png")
BACKGROUND_DIM_ALPHA = 0.65

NTP_SYNC_PATH = Path("/run/systemd/timesync/synchronized")
VCGENCMD = "/usr/bin/vcgencmd"
SYSTEMCTL = "/usr/bin/systemctl"

TRACKED_SERVICES = ["ssh", "rpi-connect"]

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

WHITE = (255, 255, 255)
DIM = (140, 140, 140)
ACCENT = (90, 200, 255)
WARN = (255, 180, 60)
BAD = (255, 80, 80)
GOOD = (120, 220, 120)
BAR_BG = (40, 40, 40)
BAR_FG = (90, 200, 255)


class State:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.dirty = threading.Event()
        loaded = DEFAULT_STATE.copy()
        try:
            loaded.update(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass
        loaded_rot = int(loaded.get("rotation", 0)) % 4
        self.rotation = loaded_rot if loaded_rot in VALID_ROTATIONS else 0
        self.screen_on = bool(loaded.get("screen_on", True))
        self.current_page = int(loaded.get("current_page", 0)) % PAGES

    def cycle_rotation(self):
        with self.lock:
            idx = VALID_ROTATIONS.index(self.rotation)
            self.rotation = VALID_ROTATIONS[(idx + 1) % len(VALID_ROTATIONS)]
        self.dirty.set()
        self._save()

    def toggle_screen(self):
        with self.lock:
            self.screen_on = not self.screen_on
        self.dirty.set()
        self._save()

    def cycle_page(self):
        with self.lock:
            self.current_page = (self.current_page + 1) % PAGES
        self.dirty.set()
        self._save()

    def snapshot(self):
        with self.lock:
            return self.rotation, self.screen_on, self.current_page

    def _save(self):
        with self.lock:
            payload = {
                "rotation": self.rotation,
                "screen_on": self.screen_on,
                "current_page": self.current_page,
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self.path)
        except OSError:
            pass


def primary_ip(iface_prefix: str) -> str | None:
    for name, addrs in psutil.net_if_addrs().items():
        if not name.startswith(iface_prefix):
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                return addr.address
    return None


def cpu_temp_c() -> float | None:
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return int(raw) / 1000.0
    except (OSError, ValueError):
        return None


def cpu_freq_mhz() -> float | None:
    try:
        freq = psutil.cpu_freq()
        return freq.current if freq else None
    except Exception:
        return None


def ntp_synced() -> bool:
    return NTP_SYNC_PATH.exists()


def loadavg() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return (0.0, 0.0, 0.0)


def process_counts() -> dict[str, int]:
    counts = {"total": 0, "running": 0, "sleeping": 0, "zombie": 0, "stopped": 0}
    sleeping_set = {
        psutil.STATUS_SLEEPING,
        psutil.STATUS_DISK_SLEEP,
        getattr(psutil, "STATUS_IDLE", "idle"),
        getattr(psutil, "STATUS_WAITING", "waiting"),
        getattr(psutil, "STATUS_WAKING", "waking"),
        getattr(psutil, "STATUS_PARKED", "parked"),
    }
    stopped_set = {
        psutil.STATUS_STOPPED,
        getattr(psutil, "STATUS_TRACING_STOP", "tracing-stop"),
    }
    for p in psutil.process_iter(["status"]):
        counts["total"] += 1
        status = p.info.get("status")
        if status == psutil.STATUS_RUNNING:
            counts["running"] += 1
        elif status in sleeping_set:
            counts["sleeping"] += 1
        elif status == psutil.STATUS_ZOMBIE:
            counts["zombie"] += 1
        elif status in stopped_set:
            counts["stopped"] += 1
    return counts


def net_rate_bytes() -> tuple[float, float]:
    """Aggregate rx/tx bytes per second across physical interfaces. Skips
    loopback and common virtual bridges. Uses a function-attribute cache
    for the previous sample so the first call returns (0, 0) and primes."""
    now = time.monotonic()
    counters = psutil.net_io_counters(pernic=True)
    total_rx = 0
    total_tx = 0
    for iface, c in counters.items():
        if iface == "lo" or iface.startswith(("docker", "veth", "br-")):
            continue
        total_rx += c.bytes_recv
        total_tx += c.bytes_sent

    prev = getattr(net_rate_bytes, "_prev", None)
    net_rate_bytes._prev = (total_rx, total_tx, now)
    if prev is None:
        return 0.0, 0.0
    prev_rx, prev_tx, prev_now = prev
    dt = now - prev_now
    if dt <= 0:
        return 0.0, 0.0
    return max(0, total_rx - prev_rx) / dt, max(0, total_tx - prev_tx) / dt


def format_rate(bytes_per_sec: float) -> str:
    """1.2KB/s, 3.4MB/s — fixed-width fields so the row doesn't jitter."""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:4.0f}B/s"
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec/1024:4.1f}KB/s"
    if bytes_per_sec < 1024 * 1024 * 1024:
        return f"{bytes_per_sec/(1024*1024):4.1f}MB/s"
    return f"{bytes_per_sec/(1024**3):4.1f}GB/s"


def throttle_state() -> tuple[str, tuple[int, int, int]] | None:
    fake = os.environ.get("POD_STATUS_FAKE_THROTTLED")
    if fake:
        try:
            bits = int(fake, 0)
        except ValueError:
            return None
    else:
        try:
            result = subprocess.run(
                [VCGENCMD, "get_throttled"],
                capture_output=True, text=True, timeout=2,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        try:
            _, hex_val = result.stdout.strip().split("=", 1)
            bits = int(hex_val, 16)
        except (ValueError, IndexError):
            return None
    if bits & 0x1:
        return "UV", BAD
    if bits & 0x4:
        return "THR", BAD
    if bits & 0x2 or bits & 0x8:
        return "CAP", WARN
    if bits & 0xF0000:
        return "△", WARN
    return None


def uptime_str() -> str:
    secs = int(time.time() - psutil.boot_time())
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def pi_model() -> str:
    try:
        raw = Path("/proc/device-tree/model").read_text().rstrip("\x00\n").strip()
    except OSError:
        return "—"
    if " Rev " in raw:
        raw = raw.split(" Rev ")[0]
    return raw


def os_info() -> tuple[str, str]:
    name, version = "—", "—"
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return name, version
    for line in text.splitlines():
        key, _, val = line.partition("=")
        val = val.strip().strip('"')
        if key == "PRETTY_NAME":
            name = val
        elif key == "VERSION":
            version = val
    return name, version


def kernel_release() -> str:
    try:
        return os.uname().release
    except OSError:
        return "—"


def services_status(services: list[str]) -> dict[str, str]:
    """One systemctl invocation for all services — is-active prints one
    status per line in argument order regardless of overall exit code."""
    try:
        result = subprocess.run(
            [SYSTEMCTL, "is-active", *services],
            capture_output=True, text=True, timeout=3,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return {s: "unknown" for s in services}
    lines = result.stdout.strip().split("\n")
    return {s: (lines[i] if i < len(lines) else "unknown")
            for i, s in enumerate(services)}


def load_background(device_mode: str) -> Image.Image | None:
    """Load /opt/pod-status/background.png if present, resize to panel size,
    and pre-darken so it stays subtle behind the foreground text. Passed
    to canvas() as the starting image each frame."""
    if not BACKGROUND_PATH.exists():
        return None
    try:
        img = Image.open(BACKGROUND_PATH).convert(device_mode)
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT))
        black = Image.new(device_mode, img.size, "black")
        return Image.blend(img, black, alpha=BACKGROUND_DIM_ALPHA)
    except (OSError, ValueError):
        return None


def draw_bar(draw, x, y, w, h, frac, label, value, font):
    frac = max(0.0, min(1.0, frac))
    draw.rectangle((x, y, x + w, y + h), fill=BAR_BG)
    draw.rectangle((x, y, x + int(w * frac), y + h), fill=BAR_FG)
    draw.text((x - 42, y - 2), label, font=font, fill=WHITE)
    draw.text((x + w + 6, y - 2), value, font=font, fill=WHITE)


def render_header(draw, fonts):
    f_small, _, f_big = fonts
    hostname = socket.gethostname()
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")

    draw.text((4, 2), hostname, font=f_big, fill=ACCENT)
    draw.text((WIDTH - 108, 4), f"{now} UTC", font=f_small, fill=WHITE)
    draw.line((4, 30, WIDTH - 4, 30), fill=DIM)


def render_footer(draw, fonts, page):
    f_small = fonts[0]
    y = HEIGHT - 16
    draw.text((4, y), f"up {uptime_str()}", font=f_small, fill=DIM)

    throttle = throttle_state()
    if throttle is not None:
        label, color = throttle
        draw.text((WIDTH - 86, y), label, font=f_small, fill=color)

    draw.text((WIDTH - 36, y), f"{page + 1}/{PAGES}", font=f_small, fill=DIM)


def render_stats(device, fonts, background):
    f_small, f_med, _ = fonts

    wlan_ip = primary_ip("wlan") or "—"
    eth_ip = primary_ip("eth") or primary_ip("en")
    cpu_pct = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    temp = cpu_temp_c()
    freq = cpu_freq_mhz()
    load = loadavg()
    procs = process_counts()
    rx, tx = net_rate_bytes()
    ncpu = psutil.cpu_count(logical=True) or 4

    with canvas(device, background=background) as draw:
        render_header(draw, fonts)

        y = 36
        draw.text((4, y), "wlan0", font=f_small, fill=DIM)
        draw.text((68, y), wlan_ip, font=f_med, fill=WHITE)
        y += 22
        if eth_ip:
            draw.text((4, y), "eth0", font=f_small, fill=DIM)
            draw.text((68, y), eth_ip, font=f_med, fill=WHITE)
            y += 22

        y = max(y, 84)
        draw.line((4, y, WIDTH - 4, y), fill=DIM)
        y += 8

        bar_x, bar_w, bar_h = 52, 100, 10
        right_x = bar_x + bar_w + 64

        draw_bar(draw, bar_x, y, bar_w, bar_h, cpu_pct / 100.0,
                 "CPU", f"{cpu_pct:5.1f}%", f_small)
        if freq is None:
            freq_str = "—"
        elif freq < 1000:
            freq_str = f"{freq:.0f}MHz"
        else:
            freq_str = f"{freq/1000:.1f}GHz"
        temp_color = WARN if (temp or 0) >= 70 else WHITE
        draw.text((right_x, y - 2), freq_str, font=f_small, fill=WHITE)
        if temp is not None:
            draw.text((WIDTH - 40, y - 2), f"{temp:.0f}°C",
                      font=f_small, fill=temp_color)
        y += 20

        draw_bar(draw, bar_x, y, bar_w, bar_h, ram.percent / 100.0,
                 "RAM", f"{ram.percent:5.1f}%", f_small)
        draw.text((right_x, y - 2),
                  f"{ram.used // 1024 // 1024}/{ram.total // 1024 // 1024}M",
                  font=f_small, fill=DIM)
        y += 20

        draw_bar(draw, bar_x, y, bar_w, bar_h, swap.percent / 100.0,
                 "Swap", f"{swap.percent:5.1f}%", f_small)
        if swap.total > 0:
            draw.text((right_x, y - 2),
                      f"{swap.used // 1024 // 1024}/{swap.total // 1024 // 1024}M",
                      font=f_small, fill=DIM)
        else:
            draw.text((right_x, y - 2), "off", font=f_small, fill=DIM)
        y += 20

        draw_bar(draw, bar_x, y, bar_w, bar_h, disk.percent / 100.0,
                 "Disk", f"{disk.percent:5.1f}%", f_small)
        draw.text((right_x, y - 2),
                  f"{disk.used // (1024**3)}/{disk.total // (1024**3)}G",
                  font=f_small, fill=DIM)
        y += 22

        load1_color = WARN if load[0] >= ncpu else WHITE
        draw.text((4, y), "Load", font=f_small, fill=DIM)
        draw.text((52, y), f"{load[0]:.2f}", font=f_small, fill=load1_color)
        draw.text((104, y), f"{load[1]:.2f}", font=f_small, fill=WHITE)
        draw.text((156, y), f"{load[2]:.2f}", font=f_small, fill=WHITE)
        y += 18

        draw.text((4, y), "Procs", font=f_small, fill=DIM)
        z_color = WARN if procs["zombie"] > 0 else WHITE
        t_color = WARN if procs["stopped"] > 0 else WHITE
        draw.text((52, y), f"{procs['total']}t", font=f_small, fill=WHITE)
        draw.text((104, y), f"{procs['running']}R", font=f_small, fill=WHITE)
        draw.text((150, y), f"{procs['sleeping']}S", font=f_small, fill=WHITE)
        draw.text((204, y), f"{procs['zombie']}Z", font=f_small, fill=z_color)
        draw.text((248, y), f"{procs['stopped']}T", font=f_small, fill=t_color)
        y += 16

        draw.text((4, y), "Net", font=f_small, fill=DIM)
        draw.text((52, y), "↓", font=f_small, fill=ACCENT)
        draw.text((68, y), format_rate(rx), font=f_small, fill=WHITE)
        draw.text((164, y), "↑", font=f_small, fill=ACCENT)
        draw.text((180, y), format_rate(tx), font=f_small, fill=WHITE)

        render_footer(draw, fonts, page=0)


def render_system(device, fonts, background):
    f_small = fonts[0]

    model = pi_model()
    os_name, os_version = os_info()
    kernel = kernel_release()
    statuses = services_status(TRACKED_SERVICES)
    synced = ntp_synced()

    with canvas(device, background=background) as draw:
        render_header(draw, fonts)

        y = 38
        rows = [
            ("Model", model),
            ("OS", os_name),
            ("Ver", os_version),
            ("Kernel", kernel),
        ]
        for label, value in rows:
            draw.text((4, y), label, font=f_small, fill=DIM)
            draw.text((76, y), value, font=f_small, fill=WHITE)
            y += 20

        draw.line((4, y + 2, WIDTH - 4, y + 2), fill=DIM)
        y += 10

        service_rows = [
            ("SSH", statuses.get("ssh", "unknown"), "active"),
            ("Connect", statuses.get("rpi-connect", "unknown"), "active"),
            ("NTP", "synced" if synced else "not synced", "synced"),
        ]
        for label, value, good_value in service_rows:
            color = GOOD if value == good_value else DIM
            draw.text((4, y), label, font=f_small, fill=DIM)
            draw.text((76, y), value, font=f_small, fill=color)
            y += 20

        draw.line((4, y + 2, WIDTH - 4, y + 2), fill=DIM)
        y += 10

        legend = [
            ("▶", "next", 8),
            ("↻", "rotate", 108),
            ("☀☾", "on/off", 208),
        ]
        for icon, text, x in legend:
            draw.text((x, y), icon, font=f_small, fill=ACCENT)
            icon_w = 12 if len(icon) == 1 else 22
            draw.text((x + icon_w, y), text, font=f_small, fill=DIM)

        render_footer(draw, fonts, page=1)


def render_page(device, fonts, background, page):
    if page == 1:
        render_system(device, fonts, background)
    else:
        render_stats(device, fonts, background)


def render_blank(device):
    blank = Image.new(device.mode, device.size, "black")
    device.display(blank)


def make_device(rotation: int):
    serial = spi(port=SPI_PORT, device=SPI_DEVICE, gpio_DC=GPIO_DC,
                 gpio_RST=GPIO_RST, bus_speed_hz=SPI_HZ)
    return ili9341(serial, width=WIDTH, height=HEIGHT, rotate=rotation)


def main():
    state = State(STATE_PATH)

    fonts = (
        ImageFont.truetype(FONT_REGULAR, 14),
        ImageFont.truetype(FONT_REGULAR, 18),
        ImageFont.truetype(FONT_BOLD, 24),
    )

    btn_page = Button(BTN_PAGE, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    btn_rotate = Button(BTN_ROTATE, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    btn_toggle = Button(BTN_TOGGLE, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    btn_page.when_pressed = state.cycle_page
    btn_rotate.when_pressed = state.cycle_rotation
    btn_toggle.when_pressed = state.toggle_screen

    psutil.cpu_percent(interval=None)

    current_rotation, current_on, current_page = state.snapshot()
    device = make_device(current_rotation)
    background = load_background(device.mode)
    if not current_on:
        render_blank(device)

    while True:
        if state.dirty.is_set():
            state.dirty.clear()
            new_rotation, new_on, new_page = state.snapshot()
            if new_rotation != current_rotation:
                device = make_device(new_rotation)
                current_rotation = new_rotation
            current_page = new_page
            if new_on != current_on:
                current_on = new_on
                if not current_on:
                    render_blank(device)

        if current_on:
            render_page(device, fonts, background, current_page)

        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
