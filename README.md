# Raspberry Pi 5 -- System & (Software‑Reported) Power Monitor

A lightweight Python tool to log **CPU, memory, disk, network,
temperatures**, and **software‑reported power/voltage/current** on
Raspberry Pi 5. It combines standard system stats with Raspberry Pi
firmware (`vcgencmd`) and generic Linux **hwmon** sensors.

> ⚠️ Software‑reported power excludes 5 V input/USB peripheral loads.
> For research‑grade energy measurements, align logs with an **external
> power meter**.

------------------------------------------------------------------------

## Features

-   CPU% / freq / load, RAM & swap usage
-   Disk usage + I/O, Network TX/RX
-   Thermal zones from `/sys/class/thermal`
-   Firmware metrics via `vcgencmd` (clocks, volts, temperature, and
    Pi 5 power rails if supported)
-   Auto‑discovers `/sys/class/hwmon` sensors for
    **power/voltage/current/temperature**
-   Streams to CSV with a stable header; prints a compact one‑line
    status

------------------------------------------------------------------------

## Requirements

-   **Raspberry Pi OS (Bookworm or later)** on **Raspberry Pi 5**
-   Python 3.11+ (default on Pi OS Bookworm)
-   Packages: `psutil` and `vcgencmd` (vcgencmd ships with Pi OS)

Install dependencies:

``` bash
sudo apt update && sudo apt install -y python3-psutil
```

------------------------------------------------------------------------

## File Layout

-   `main.py` -- the monitor script
-   `metrics.csv` -- default output (configurable via `--out`)

> If you already have the script as another filename, rename it:

``` bash
mv rpi5_system_power_monitor.py main.py
chmod +x main.py
```

------------------------------------------------------------------------

## Quick Start

Run with defaults (1 s interval, writes to `rpi5_metrics.csv` in current
dir):

``` bash
python3 main.py
```

Write to home folder:

``` bash
python3 main.py --out ~/metrics.csv
```

Higher sampling (0.5 s) for 5 minutes:

``` bash
python3 main.py --interval 0.5 --duration 300
```

Disable `vcgencmd` (only system + hwmon):

``` bash
python3 main.py --no-vcgencmd
```

Run in background for 24 h, log to `/var/log`:

``` bash
nohup python3 main.py --interval 1 --duration $((24*3600)) --out /var/log/rpi5_metrics.csv >/var/log/rpi5_monitor.out 2>&1 &
```

------------------------------------------------------------------------

## Command‑line Options

``` text
--interval <float>   Sample interval in seconds (default: 1.0)
--duration <float>   Stop after N seconds (0 = run until Ctrl+C)
--out <path>         CSV output path (default: ./rpi5_metrics.csv)
--no-vcgencmd        Skip firmware metrics
```

------------------------------------------------------------------------

## What gets logged?

-   `cpu_user_pct`, `cpu_system_pct`, `cpu_idle_pct`
-   `cpu_freq_current_mhz`, `cpu_load_1m`
-   Memory: `mem_total_mb`, `mem_used_mb`, `mem_used_pct`, `swap_*`
-   Disk I/O: `disk_root_used_pct`, `disk_read_mb`, `disk_write_mb`,
    `*_count`
-   Network: `net_bytes_sent_mb`, `net_bytes_recv_mb`, packets
-   Thermal: `therm_<zone>_c`
-   Firmware (when available): `vc_temp_c`, `vc_clk_<domain>_hz`,
    `vc_volt_*_v`, `vc_power_<rail>_mw`, `vc_curr_<rail>_ma`
-   HWMON (discovered): `hwmon_<chip>_<label>_mw|_v|_ma|_c`

Console prints each sample like:

    2025-09-22T10:12:30+02:00 | CPU 23.1% | Temp 52.0C | Power(mW) 1450 | rows-> rpi5_metrics.csv

------------------------------------------------------------------------

## Permissions & Tips

-   If `vcgencmd` fails with permissions, either run with `sudo` **or**
    add your user to `video`:

    ``` bash
    sudo usermod -aG video $USER
    # log out/in or reboot
    ```

-   Temperature units vary by source: thermal zones usually report
    **milli‑°C**; the script converts to °C.

-   HWMON units differ by driver; the script heuristically converts
    common milli/micro units.

------------------------------------------------------------------------

## Validation Workflow (recommended)

1.  Start an **external power meter** on the 5 V input.
2.  Run `main.py` with your chosen interval.
3.  Apply controlled workloads (e.g., `stress-ng --cpu 8`).
4.  Align timestamps and compare external power with software‑visible
    rail totals.

------------------------------------------------------------------------

## Troubleshooting

-   **No power rails in CSV**: Your firmware may not expose
    `measure_power`. Update Pi firmware/OS and retry, or rely on
    hwmon/external meter.
-   **No hwmon values**: The board/kernel may not expose sensors for
    your accessory HAT/PMIC; check `/sys/class/hwmon/*` for files.
-   **CSV header changes**: The script probes once at startup to
    stabilize columns. Restart after adding new sensors/firmware.

------------------------------------------------------------------------

## License

Zealand and RUC (Nilma & Maja)
