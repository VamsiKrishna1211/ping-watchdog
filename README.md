# ping-watchdog

A lightweight Python daemon that continuously pings a target IP address and automatically reboots the system when the target becomes unreachable. Runs as a `systemd` service and starts on every boot.

---

## How It Works

```
boot
 └─> systemd starts ping-watchdog (after network is online)
       └─> pings TARGET_IP every PING_INTERVAL seconds
             ├─ success → reset failure counter, wait, repeat
             └─ failure → increment counter
                           └─ counter >= FAILURE_THRESHOLD
                                 └─> systemctl reboot
```

- A single successful ping resets the consecutive failure counter to zero.
- The service restarts itself automatically if it crashes (`Restart=on-failure`).
- All activity is written to `/var/log/ping-watchdog.log` **and** the systemd journal.

---

## Requirements

| Requirement | Notes |
|---|---|
| Linux with systemd | Tested on Ubuntu 22.04 / Debian 12 |
| Python ≥ 3.11 | Managed by uv |
| [uv](https://github.com/astral-sh/uv) | Installed automatically by `install.sh` |
| Root privileges | Needed to reboot and write to `/var/log` |

No third-party Python packages are required — the script uses only the standard library.

---

## Project Structure

```
ping-watchdog/
├── ping_watchdog.py        # Main watchdog script
├── pyproject.toml          # uv project definition
├── ping-watchdog.service   # systemd unit file
├── install.sh              # One-shot installer script
└── README.md
```

---

## Configuration

All settings are controlled by environment variables. The defaults are defined in `ping-watchdog.service` and can be changed there without touching the Python code.

| Environment Variable | Default | Description |
|---|---|---|
| `WATCHDOG_TARGET_IP` | `8.8.8.8` | IP address to ping |
| `WATCHDOG_PING_INTERVAL` | `5` | Seconds to wait between pings |
| `WATCHDOG_FAILURE_THRESHOLD` | `5` | Consecutive failures before reboot |
| `WATCHDOG_PING_TIMEOUT` | `4` | Per-ping timeout in seconds |
| `WATCHDOG_LOG_FILE` | `/var/log/ping-watchdog.log` | Path to the log file |

**Worst-case time to reboot** = `PING_INTERVAL × FAILURE_THRESHOLD` + `PING_TIMEOUT`  
With defaults: `5 × 5 + 4 = 29 seconds`

---

## Installation

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### 2. Clone / download the project

```bash
git clone https://github.com/your-repo/ping-watchdog.git
cd ping-watchdog
```

### 3. (Optional) Set your target IP

Edit `ping-watchdog.service` and change:

```ini
Environment=WATCHDOG_TARGET_IP=8.8.8.8
```

Replace `8.8.8.8` with the IP you want to monitor — typically your router, gateway, or an upstream server.

You can also adjust the other `Environment=` lines to tune timing and thresholds.

### 4. Run the installer

```bash
sudo bash install.sh
```

The installer will:
1. Check for root permissions
2. Install `uv` under `/root/.local/bin` if not already present
3. Copy `ping_watchdog.py` and `pyproject.toml` to `/opt/ping-watchdog`
4. Run `uv sync` to create the virtual environment
5. Copy the service file to `/etc/systemd/system/`
6. Run `systemctl daemon-reload`, `enable`, and `restart`

---

## Manual Installation (step by step)

If you prefer to install without the script:

```bash
# 1. Install uv as root
sudo curl -LsSf https://astral.sh/uv/install.sh | sudo sh

# 2. Deploy files
sudo mkdir -p /opt/ping-watchdog
sudo cp ping_watchdog.py pyproject.toml /opt/ping-watchdog/

# 3. Create the virtual environment
cd /opt/ping-watchdog
sudo /root/.local/bin/uv sync

# 4. Install the service
sudo cp ping-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Enable (auto-start on boot) and start now
sudo systemctl enable ping-watchdog
sudo systemctl start ping-watchdog
```

---

## Usage

### Check service status

```bash
systemctl status ping-watchdog
```

### Watch live logs

```bash
# From the systemd journal
journalctl -u ping-watchdog -f

# From the log file
tail -f /var/log/ping-watchdog.log
```

### Sample log output

```
2026-04-25 10:00:01 [INFO] ============================================================
2026-04-25 10:00:01 [INFO] Ping watchdog starting up
2026-04-25 10:00:01 [INFO]   Target IP         : 8.8.8.8
2026-04-25 10:00:01 [INFO]   Ping interval     : 5s
2026-04-25 10:00:01 [INFO]   Failure threshold : 5 consecutive failures
2026-04-25 10:00:01 [INFO]   Ping timeout      : 4s
2026-04-25 10:00:01 [INFO] ============================================================
2026-04-25 10:00:06 [INFO] Ping OK -> 8.8.8.8
2026-04-25 10:00:11 [INFO] Ping OK -> 8.8.8.8
2026-04-25 10:01:00 [WARNING] Ping FAILED -> 8.8.8.8  (1/5 consecutive failures)
2026-04-25 10:01:09 [WARNING] Ping FAILED -> 8.8.8.8  (2/5 consecutive failures)
2026-04-25 10:01:18 [WARNING] Ping FAILED -> 8.8.8.8  (3/5 consecutive failures)
2026-04-25 10:01:27 [WARNING] Ping FAILED -> 8.8.8.8  (4/5 consecutive failures)
2026-04-25 10:01:36 [WARNING] Ping FAILED -> 8.8.8.8  (5/5 consecutive failures)
2026-04-25 10:01:36 [CRITICAL] WATCHDOG: ping threshold reached — triggering system reboot now.
```

### Stop the service

```bash
sudo systemctl stop ping-watchdog
```

### Temporarily disable auto-start

```bash
sudo systemctl disable ping-watchdog
```

### Re-enable auto-start

```bash
sudo systemctl enable ping-watchdog
```

### Apply configuration changes

After editing `Environment=` lines in `/etc/systemd/system/ping-watchdog.service`:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ping-watchdog
```

---

## Uninstall

```bash
sudo systemctl stop ping-watchdog
sudo systemctl disable ping-watchdog
sudo rm /etc/systemd/system/ping-watchdog.service
sudo rm -rf /opt/ping-watchdog
sudo rm -f /var/log/ping-watchdog.log
sudo systemctl daemon-reload
```

---

## Troubleshooting

### Service fails to start

Check the journal for errors:

```bash
journalctl -u ping-watchdog -n 50 --no-pager
```

**Common causes:**

| Symptom | Fix |
|---|---|
| `uv: command not found` | Run `sudo /root/.local/bin/uv sync` from `/opt/ping-watchdog` |
| `ping: permission denied` | Ensure the service runs as `User=root` in the service file |
| `No module named ...` | Re-run `sudo /root/.local/bin/uv sync` in `/opt/ping-watchdog` |
| Service starts before network | Confirm `After=network-online.target` and that `systemd-networkd-wait-online` or equivalent is enabled |

### Verify the network-online target is active

```bash
systemctl is-active network-online.target
systemctl status systemd-networkd-wait-online.service
```

On some minimal installs (e.g. Ubuntu Server with NetworkManager) you may need:

```bash
sudo systemctl enable NetworkManager-wait-online.service
```

### Test the script manually before deploying

```bash
cd /opt/ping-watchdog
sudo WATCHDOG_TARGET_IP=8.8.8.8 WATCHDOG_FAILURE_THRESHOLD=2 \
  /root/.local/bin/uv run python ping_watchdog.py
```

Remove `sudo` and set `WATCHDOG_LOG_FILE=/tmp/watchdog.log` if testing as a non-root user (reboot will fail, but pinging will work).

---

## Security Notes

- The service runs as **root** because issuing a system reboot requires root privileges.
- The `ping` binary is invoked via an explicit argument list — no shell expansion, no injection risk.
- No inbound network ports are opened; this is a purely outbound monitoring tool.
- If you want to reduce the blast radius, you can grant only `CAP_NET_RAW` (for ping) and `shutdown` capability instead of full root, but that requires additional systemd hardening (`AmbientCapabilities`, `ExecStartPost` wrappers, etc.).

---

## License

MIT
