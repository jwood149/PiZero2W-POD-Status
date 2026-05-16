#!/usr/bin/env python3
"""Argon POD 2.8" TFT status panel for headless Pi Zero 2W."""

import json
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

BTN_ROTATE = 16
BTN_TOGGLE = 26

WIDTH = 320
HEIGHT = 240
REFRESH_SECONDS = 2
DEBOUNCE_SECONDS = 0.05

STATE_PATH = Path("/var/lib/pod-status/state.json")
DEFAULT_STATE = {"rotation": 0, "screen_on": True}

NTP_SYNC_PATH = Path("/run/systemd/timesync/synchronized")
VCGENCMD = "/usr/bin/vcgencmd"

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
        self.rotation = int(loaded.get("rotation", 0)) % 4
        self.screen_on = bool(loaded.get("screen_on", True))

    def cycle_rotation(self):
        with self.lock:
            self.rotation = (self.rotation + 1) % 4
        self.dirty.set()
        self._save()

    def toggle_screen(self):
        with self.lock:
            self.screen_on = not self.screen_on
        self.dirty.set()
        self._save()

    def snapshot(self):
        with self.lock:
            return self.rotation, self.screen_on

    def _save(self):
        with self.lock:
            payload = {"rotation": self.rotation, "screen_on": self.screen_on}
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


def throttle_state() -> tuple[str, tuple[int, int, int]] | None:
    """Parse `vcgencmd get_throttled` into a short status + color.
    Returns None when the Pi is clean (no current or sticky throttle bits)
    or when vcgencmd is unavailable.
    """
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


def draw_bar(draw, x, y, w, h, frac, label, value, font):
    frac = max(0.0, min(1.0, frac))
    draw.rectangle((x, y, x + w, y + h), fill=BAR_BG)
    draw.rectangle((x, y, x + int(w * frac), y + h), fill=BAR_FG)
    draw.text((x - 42, y - 2), label, font=font, fill=WHITE)
    draw.text((x + w + 6, y - 2), value, font=font, fill=WHITE)


def render_status(device, fonts):
    f_small, f_med, f_big = fonts

    hostname = socket.gethostname()
    wlan_ip = primary_ip("wlan") or "—"
    eth_ip = primary_ip("eth") or primary_ip("en")
    cpu_pct = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    temp = cpu_temp_c()
    freq = cpu_freq_mhz()
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    synced = ntp_synced()
    throttle = throttle_state()

    with canvas(device) as draw:
        draw.text((4, 2), hostname, font=f_big, fill=ACCENT)

        clock_text = f"{now} UTC"
        sync_mark = "OK" if synced else "NO"
        sync_color = GOOD if synced else BAD
        draw.text((WIDTH - 130, 4), sync_mark, font=f_small, fill=sync_color)
        draw.text((WIDTH - 108, 4), clock_text, font=f_small, fill=WHITE)

        draw.line((4, 30, WIDTH - 4, 30), fill=DIM)

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

        bar_x, bar_w, bar_h = 52, 150, 10
        draw_bar(draw, bar_x, y, bar_w, bar_h, cpu_pct / 100.0,
                 "CPU", f"{cpu_pct:5.1f}%", f_small)
        freq_str = f"{freq/1000:.2f}GHz" if freq else "—"
        temp_color = WARN if (temp or 0) >= 70 else WHITE
        draw.text((bar_x + bar_w + 60, y - 2), freq_str, font=f_small, fill=WHITE)
        if temp is not None:
            draw.text((WIDTH - 58, y - 2), f"{temp:4.1f}°C",
                      font=f_small, fill=temp_color)
        y += 20

        draw_bar(draw, bar_x, y, bar_w, bar_h, ram.percent / 100.0,
                 "RAM", f"{ram.percent:5.1f}%", f_small)
        draw.text((bar_x + bar_w + 60, y - 2),
                  f"{ram.used // 1024 // 1024}/{ram.total // 1024 // 1024}MB",
                  font=f_small, fill=DIM)
        y += 20

        swap_pct = swap.percent
        draw_bar(draw, bar_x, y, bar_w, bar_h, swap_pct / 100.0,
                 "Swap", f"{swap_pct:5.1f}%", f_small)
        if swap.total > 0:
            draw.text((bar_x + bar_w + 60, y - 2),
                      f"{swap.used // 1024 // 1024}/{swap.total // 1024 // 1024}MB",
                      font=f_small, fill=DIM)
        else:
            draw.text((bar_x + bar_w + 60, y - 2), "off",
                      font=f_small, fill=DIM)
        y += 20

        draw_bar(draw, bar_x, y, bar_w, bar_h, disk.percent / 100.0,
                 "Disk", f"{disk.percent:5.1f}%", f_small)
        draw.text((bar_x + bar_w + 60, y - 2),
                  f"{disk.used // (1024**3)}/{disk.total // (1024**3)}GB",
                  font=f_small, fill=DIM)
        y += 24

        draw.text((4, y), f"up {uptime_str()}", font=f_small, fill=DIM)
        if throttle is not None:
            label, color = throttle
            draw.text((WIDTH - 40, y), label, font=f_small, fill=color)


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

    btn_rotate = Button(BTN_ROTATE, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    btn_toggle = Button(BTN_TOGGLE, pull_up=True, bounce_time=DEBOUNCE_SECONDS)
    btn_rotate.when_pressed = state.cycle_rotation
    btn_toggle.when_pressed = state.toggle_screen

    psutil.cpu_percent(interval=None)

    current_rotation, current_on = state.snapshot()
    device = make_device(current_rotation)
    if not current_on:
        render_blank(device)

    while True:
        if state.dirty.is_set():
            state.dirty.clear()
            new_rotation, new_on = state.snapshot()
            if new_rotation != current_rotation:
                device = make_device(new_rotation)
                current_rotation = new_rotation
            if new_on != current_on:
                current_on = new_on
                if not current_on:
                    render_blank(device)

        if current_on:
            render_status(device, fonts)

        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
