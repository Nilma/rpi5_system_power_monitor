#!/usr/bin/env python3
"""
Raspberry Pi 5 – System & (Software-Reported) Power Monitor

This script collects various performance and power metrics from a Raspberry Pi 5.
It combines standard system monitoring (CPU, memory, disk, network, thermal) with
firmware and hardware monitoring interfaces like `vcgencmd` and `/sys/class/hwmon`.

Collected metrics:
- CPU usage, frequency, and load
- Memory usage (RAM and swap)
- Disk usage and I/O activity
- Network traffic stats
- Temperatures from thermal zones
- Power, voltage, and current readings from `vcgencmd` (if available)
- Power/voltage/current/temperature from `hwmon` sensors

All metrics are written into a CSV file with a timestamp and also printed
as a compact one-liner on the console.

Usage examples:
  python3 rpi5_system_power_monitor.py --interval 1 --out metrics.csv
  python3 rpi5_system_power_monitor.py --interval 0.5 --duration 300

Dependencies:
  sudo apt update && sudo apt install -y python3-psutil

Note: `vcgencmd` is included in Raspberry Pi OS. If it gives permission errors,
run the script with `sudo` or add your user to the 'video' group.
"""

from __future__ import annotations
import argparse
import csv
import datetime as dt
import pathlib
import re
import subprocess
import time
from typing import Dict, Any, List, Tuple

import psutil

# ---------------------------- helpers ----------------------------

def now_iso() -> str:
    """Return current timestamp in ISO format."""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    """Run a shell command safely and return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"missing: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)

# ---------------------------- vcgencmd ---------------------------

# Possible paths to vcgencmd binary
VCGEN_PATHS = ["/usr/bin/vcgencmd", "/bin/vcgencmd", "vcgencmd"]

def vcgencmd_available() -> str | None:
    """Check if vcgencmd is available and return its path if so."""
    for p in VCGEN_PATHS:
        rc, out, _ = run_cmd([p, "version"])
        if rc == 0 and out:
            return p
    return None

def parse_kv_pairs(s: str) -> Dict[str, float]:
    """Parse output like 'temp=52.3'C' into a dictionary {temp: 52.3}."""
    d: Dict[str, float] = {}
    if not s:
        return d
    for token in re.split(r"\s+|,", s.strip()):
        if "=" in token:
            k, v = token.split("=", 1)
            try:
                num = float(re.findall(r"[-+]?[0-9]*\.?[0-9]+", v)[0])
                d[k] = num
            except Exception:
                pass
    return d

def get_vcgencmd_metrics(vcpath: str) -> Dict[str, Any]:
    """Collect metrics from vcgencmd (temperature, voltage, clocks, power)."""
    m: Dict[str, Any] = {}

    # Temperature
    rc, out, _ = run_cmd([vcpath, "measure_temp"])
    if rc == 0:
        try:
            m["vc_temp_c"] = float(re.findall(r"([0-9]+\.?[0-9]*)", out)[0])
        except Exception:
            pass

    # Voltage domains (core and SDRAM)
    for dom in ["core", "sdram_c", "sdram_i", "sdram_p"]:
        rc, out, _ = run_cmd([vcpath, "measure_volts", dom])
        if rc == 0:
            vals = parse_kv_pairs(out.replace(dom, f"volt_{dom}"))
            m.update({f"vc_{k}_v": v for k, v in vals.items()})

    # Clock frequencies
    for clk in ["arm", "core", "v3d", "h264", "isp", "hevc", "emmc", "pixel"]:
        rc, out, _ = run_cmd([vcpath, "measure_clock", clk])
        if rc == 0:
            match = re.search(r"=([0-9]+)", out)
            if match:
                m[f"vc_clk_{clk}_hz"] = int(match.group(1))

    # Power readings (if supported by Pi 5 firmware)
    rc, out, _ = run_cmd([vcpath, "measure_power"])
    if rc == 0 and out:
        for line in out.splitlines():
            mline = re.match(r".*rail:\s*(\S+)\s+power:\s*([0-9.]+)mW\s+current:\s*([0-9.]+)mA\s+voltage:\s*([0-9.]+)V", line)
            if mline:
                rail = mline.group(1)
                try:
                    m[f"vc_power_{rail}_mw"] = float(mline.group(2))
                    m[f"vc_curr_{rail}_ma"] = float(mline.group(3))
                    m[f"vc_volt_{rail}_v"] = float(mline.group(4))
                except Exception:
                    pass
    return m

# ---------------------------- hwmon ------------------------------

HWMON_BASE = pathlib.Path("/sys/class/hwmon")

def read_number(path: pathlib.Path) -> float | None:
    """Read numeric value from a sysfs path, return as float."""
    try:
        raw = path.read_text().strip()
        return float(raw)
    except Exception:
        return None

def get_hwmon_metrics() -> Dict[str, Any]:
    """Read metrics from all hwmon devices (power, voltage, current, temp)."""
    m: Dict[str, Any] = {}
    if not HWMON_BASE.exists():
        return m
    for node in sorted(HWMON_BASE.glob("hwmon*")):
        name = (node / "name").read_text().strip() if (node / "name").exists() else node.name

        # Power sensors (µW or mW)
        for p in node.glob("power*_input"):
            base = p.stem
            label_file = node / (base.replace("_input", "_label"))
            label = label_file.read_text().strip() if label_file.exists() else base
            val = read_number(p)
            if val is not None:
                mw = val / 1000.0 if val > 1e4 else val
                m[f"hwmon_{name}_{label}_mw"] = mw

        # Voltage sensors (mV or V)
        for v in node.glob("in*_input"):
            base = v.stem
            label_file = node / (base.replace("_input", "_label"))
            label = label_file.read_text().strip() if label_file.exists() else base
            val = read_number(v)
            if val is not None:
                volts = val / 1000.0 if val > 10 else val
                m[f"hwmon_{name}_{label}_v"] = volts

        # Current sensors (mA)
        for c in node.glob("curr*_input"):
            base = c.stem
            label_file = node / (base.replace("_input", "_label"))
            label = label_file.read_text().strip() if label_file.exists() else base
            val = read_number(c)
            if val is not None:
                m[f"hwmon_{name}_{label}_ma"] = val

        # Temperature sensors (milli °C)
        for t in node.glob("temp*_input"):
            base = t.stem
            label_file = node / (base.replace("_input", "_label"))
            label = label_file.read_text().strip() if label_file.exists() else base
            val = read_number(t)
            if val is not None:
                c = val / 1000.0 if val > 200 else val
                m[f"hwmon_{name}_{label}_c"] = c
    return m

# ---------------------------- system metrics ---------------------

def get_cpu_metrics() -> Dict[str, Any]:
    """CPU usage %, frequency, and load averages."""
    cpu = psutil.cpu_times_percent(interval=None)
    freq = psutil.cpu_freq()
    return {
        "cpu_user_pct": getattr(cpu, "user", None),
        "cpu_system_pct": getattr(cpu, "system", None),
        "cpu_idle_pct": getattr(cpu, "idle", None),
        "cpu_freq_current_mhz": freq.current if freq else None,
        "cpu_freq_min_mhz": freq.min if freq else None,
        "cpu_freq_max_mhz": freq.max if freq else None,
        "cpu_load_1m": psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else None,
    }

def get_mem_metrics() -> Dict[str, Any]:
    """Memory and swap usage."""
    v = psutil.virtual_memory()
    s = psutil.swap_memory()
    return {
        "mem_total_mb": v.total / (1024**2),
        "mem_used_mb": v.used / (1024**2),
        "mem_free_mb": v.available / (1024**2),
        "mem_used_pct": v.percent,
        "swap_total_mb": s.total / (1024**2),
        "swap_used_mb": s.used / (1024**2),
        "swap_used_pct": s.percent,
    }

def get_disk_metrics() -> Dict[str, Any]:
    """Disk usage and I/O statistics."""
    du = psutil.disk_usage("/")
    dio = psutil.disk_io_counters()
    return {
        "disk_root_used_pct": du.percent,
        "disk_read_mb": (dio.read_bytes / (1024**2)) if dio else None,
        "disk_write_mb": (dio.write_bytes / (1024**2)) if dio else None,
        "disk_read_count": dio.read_count if dio else None,
        "disk_write_count": dio.write_count if dio else None,
    }

def get_net_metrics() -> Dict[str, Any]:
    """Network traffic counters."""
    n = psutil.net_io_counters()
    return {
        "net_bytes_sent_mb": (n.bytes_sent / (1024**2)) if n else None,
        "net_bytes_recv_mb": (n.bytes_recv / (1024**2)) if n else None,
        "net_packets_sent": n.packets_sent if n else None,
        "net_packets_recv": n.packets_recv if n else None,
    }

def get_thermal_metrics() -> Dict[str, Any]:
    """Temperatures from /sys/class/thermal zones."""
    out: Dict[str, Any] = {}
    zones = pathlib.Path("/sys/class/thermal").glob("thermal_zone*")
    for z in zones:
        tfile = z / "temp"
        tf = z / "type"
        if tfile.exists():
            try:
                raw = float(tfile.read_text().strip())
                c = raw / 1000.0 if raw > 200 else raw
                name = tf.read_text().strip() if tf.exists() else z.name
                key = f"therm_{name}_c".replace(" ", "_")
                out[key] = c
            except Exception:
                pass
    return out

# ---------------------------- CSV writer ------------------------

class CsvAppender:
    """Helper to append rows to CSV with header management."""
    def __init__(self, path: pathlib.Path, header: List[str]):
        self.path = path
        self.header = ["timestamp"] + header
        self._ensure_header()

    def _ensure_header(self):
        """Create file and write header if empty/new."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.header)
                writer.writeheader()

    def append(self, row: Dict[str, Any]):
        """Append one row of data."""
        with self.path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.header)
            writer.writerow(row)

# ---------------------------- main loop -------------------------

def main():
    """Main monitoring loop: sample metrics, write CSV, print summary."""
    ap = argparse.ArgumentParser(description="Raspberry Pi 5 – system & power monitor")
    ap.add_argument("--interval", type=float, default=1.0, help="sample interval seconds (default: 1.0)")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after N seconds (0 = run forever)")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("rpi5_metrics.csv"), help="CSV output path")
    ap.add_argument("--no-vcgencmd", action="store_true", help="disable vcgencmd queries")
    args = ap.parse_args()

    vcpath = vcgencmd_available() if not args.no_vcgencmd else None

    # Probe once to build stable CSV header
    base_metrics: Dict[str, Any] = {}
    base_metrics.update(get_cpu_metrics())
    base_metrics.update(get_mem_metrics())
    base_metrics.update(get_disk_metrics())
    base_metrics.update(get_net_metrics())
    base_metrics.update(get_thermal_metrics())
    base_metrics.update(get_hwmon_metrics())
    if vcpath:
        base_metrics.update(get_vcgencmd_metrics(vcpath))

    header = sorted(base_metrics.keys())
    csvw = CsvAppender(args.out, header)

    print("Starting monitor. Press Ctrl+C to stop.")
    start = time.time()

    try:
        while True:
            tstamp = now_iso()
            row: Dict[str, Any] = {k: None for k in header}

            # Collect all metrics
            row.update(get_cpu_metrics())
            row.update(get_mem_metrics())
            row.update(get_disk_metrics())
            row.update(get_net_metrics())
            row.update(get_thermal_metrics())
            row.update(get_hwmon_metrics())
            if vcpath:
                row.update(get_vcgencmd_metrics(vcpath))

            # Write row to CSV
            row_out = {"timestamp": tstamp}
            row_out.update({k: row.get(k) for k in header})
            csvw.append(row_out)

            # Print compact one-line summary
            cpu = row.get("cpu_user_pct")
            temp = row.get("vc_temp_c") or max([v for k, v in row.items() if k.startswith("therm_")], default=None)
            power_keys = [k for k in row.keys() if k.endswith("_mw") and (k.startswith("vc_power_") or k.startswith("hwmon_"))]
            total_mw = sum([row[k] for k in power_keys if isinstance(row[k], (int, float))]) if power_keys else None
            print(f"{tstamp} | CPU {cpu:.1f}% | Temp {temp:.1f}C | Power(mW) {total_mw if total_mw is not None else 'n/a'} | rows-> {args.out}")

            # Exit if duration reached
            if args.duration and (time.time() - start) >= args.duration:
                break
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
