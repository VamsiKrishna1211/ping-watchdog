#!/usr/bin/env python3
"""
Ping Watchdog — continuously pings a target IP and reboots the system
if the target becomes unreachable for too many consecutive attempts.

Configuration is read from environment variables or falls back to defaults.
"""

import os
import subprocess
import sys
import time
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
TARGET_IP         = os.environ.get("WATCHDOG_TARGET_IP", "8.8.8.8")
PING_INTERVAL     = int(os.environ.get("WATCHDOG_PING_INTERVAL", "5"))    # seconds
FAILURE_THRESHOLD = int(os.environ.get("WATCHDOG_FAILURE_THRESHOLD", "5")) # consecutive failures
PING_TIMEOUT      = int(os.environ.get("WATCHDOG_PING_TIMEOUT", "4"))     # seconds per ping
LOG_FILE          = os.environ.get("WATCHDOG_LOG_FILE", "/var/log/ping-watchdog.log")


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_path = Path(LOG_FILE)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE))
    except PermissionError:
        print(f"[warn] Cannot write to {LOG_FILE}, logging to stdout only.", file=sys.stderr)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def ping(host: str, timeout: int) -> bool:
    """Returns True if host responds to a single ping within *timeout* seconds."""
    result = subprocess.run(
        ["ping", "-c", "1", "-W", str(timeout), host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def trigger_reboot() -> None:
    logging.critical("WATCHDOG: ping threshold reached — triggering system reboot now.")
    try:
        subprocess.run(["systemctl", "reboot"], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback for systems without systemctl (e.g. testing on macOS)
        logging.critical("systemctl not found, falling back to 'reboot' command.")
        subprocess.run(["reboot"], check=False)


def main() -> None:
    setup_logging()

    logging.info("=" * 60)
    logging.info("Ping watchdog starting up")
    logging.info(f"  Target IP         : {TARGET_IP}")
    logging.info(f"  Ping interval     : {PING_INTERVAL}s")
    logging.info(f"  Failure threshold : {FAILURE_THRESHOLD} consecutive failures")
    logging.info(f"  Ping timeout      : {PING_TIMEOUT}s")
    logging.info("=" * 60)

    consecutive_failures = 0

    while True:
        success = ping(TARGET_IP, PING_TIMEOUT)

        if success:
            if consecutive_failures > 0:
                logging.info(f"Ping restored after {consecutive_failures} consecutive failure(s).")
            consecutive_failures = 0
            logging.info(f"Ping OK -> {TARGET_IP}")
        else:
            consecutive_failures += 1
            logging.warning(
                f"Ping FAILED -> {TARGET_IP}  "
                f"({consecutive_failures}/{FAILURE_THRESHOLD} consecutive failures)"
            )

            if consecutive_failures >= FAILURE_THRESHOLD:
                trigger_reboot()
                # If reboot call somehow returns, keep logging and exit so systemd can restart.
                sys.exit(1)

        time.sleep(PING_INTERVAL)


if __name__ == "__main__":
    main()
