#!/usr/bin/env python3
"""
Ping Watchdog — continuously pings a target IP and reboots the system
if the target becomes unreachable for too many consecutive attempts.
Exposes a status UI on WEB_PORT (default 8080).

Configuration is read from environment variables or falls back to defaults.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
TARGET_IP         = os.environ.get("WATCHDOG_TARGET_IP", "8.8.8.8")
PING_INTERVAL     = int(os.environ.get("WATCHDOG_PING_INTERVAL", "5"))
FAILURE_THRESHOLD = int(os.environ.get("WATCHDOG_FAILURE_THRESHOLD", "5"))
PING_TIMEOUT      = int(os.environ.get("WATCHDOG_PING_TIMEOUT", "4"))
LOG_FILE          = os.environ.get("WATCHDOG_LOG_FILE", "/var/log/ping-watchdog.log")
WEB_HOST          = os.environ.get("WATCHDOG_WEB_HOST", "0.0.0.0")
WEB_PORT          = int(os.environ.get("WATCHDOG_WEB_PORT", "8080"))

# ---------------------------------------------------------------------------
# Shared state (read by the HTTP handler, written by the watchdog loop)
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_state: dict = {
    "status": "starting",        # "starting" | "ok" | "failed"
    "consecutive_failures": 0,
    "failure_threshold": FAILURE_THRESHOLD,
    "target_ip": TARGET_IP,
    "last_check": None,          # ISO timestamp string
    "uptime_start": datetime.now().isoformat(timespec="seconds"),
}


def _update_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def _read_state() -> dict:
    with _state_lock:
        return dict(_state)


# ---------------------------------------------------------------------------
# Core watchdog logic (reused by both the loop and the UI's manual trigger)
# ---------------------------------------------------------------------------
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
        logging.critical("systemctl not found, falling back to 'reboot' command.")
        subprocess.run(["reboot"], check=False)


# ---------------------------------------------------------------------------
# Watchdog loop (runs in a daemon thread)
# ---------------------------------------------------------------------------
def watchdog_loop() -> None:
    logging.info("=" * 60)
    logging.info("Ping watchdog starting up")
    logging.info(f"  Target IP         : {TARGET_IP}")
    logging.info(f"  Ping interval     : {PING_INTERVAL}s")
    logging.info(f"  Failure threshold : {FAILURE_THRESHOLD} consecutive failures")
    logging.info(f"  Ping timeout      : {PING_TIMEOUT}s")
    logging.info(f"  Web UI            : http://{WEB_HOST}:{WEB_PORT}")
    logging.info("=" * 60)

    consecutive_failures = 0

    while True:
        success = ping(TARGET_IP, PING_TIMEOUT)
        now = datetime.now().isoformat(timespec="seconds")

        if success:
            if consecutive_failures > 0:
                logging.info(f"Ping restored after {consecutive_failures} consecutive failure(s).")
            consecutive_failures = 0
            logging.info(f"Ping OK -> {TARGET_IP}")
            _update_state(status="ok", consecutive_failures=0, last_check=now)
        else:
            consecutive_failures += 1
            logging.warning(
                f"Ping FAILED -> {TARGET_IP}  "
                f"({consecutive_failures}/{FAILURE_THRESHOLD} consecutive failures)"
            )
            _update_state(
                status="failed",
                consecutive_failures=consecutive_failures,
                last_check=now,
            )

            if consecutive_failures >= FAILURE_THRESHOLD:
                trigger_reboot()
                sys.exit(1)

        time.sleep(PING_INTERVAL)


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------
_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Ping Watchdog</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: system-ui, sans-serif;
      background: #0f1117;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 24px;
      padding: 24px;
    }

    h1 { font-size: 1.5rem; font-weight: 600; letter-spacing: 0.05em; }

    .card {
      background: #1e2130;
      border: 1px solid #2d3348;
      border-radius: 12px;
      padding: 28px 36px;
      width: 100%;
      max-width: 480px;
    }

    /* Status badge */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 0.85rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 24px;
    }
    .badge .dot {
      width: 10px; height: 10px;
      border-radius: 50%;
      animation: pulse 1.8s ease-in-out infinite;
    }
    .badge.ok    { background: #14532d44; color: #4ade80; }
    .badge.ok    .dot { background: #4ade80; }
    .badge.failed { background: #7f1d1d44; color: #f87171; }
    .badge.failed .dot { background: #f87171; }
    .badge.starting { background: #1e3a5f44; color: #60a5fa; }
    .badge.starting .dot { background: #60a5fa; }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.35; }
    }

    /* Stats grid */
    .stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 28px;
    }
    .stat-label {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #64748b;
      margin-bottom: 4px;
    }
    .stat-value {
      font-size: 1rem;
      font-weight: 600;
      color: #f1f5f9;
    }
    .stat-value.warn { color: #fb923c; }

    /* Failure bar */
    .bar-wrap {
      background: #2d3348;
      border-radius: 999px;
      height: 6px;
      overflow: hidden;
      margin-top: 6px;
    }
    .bar-fill {
      height: 100%;
      border-radius: 999px;
      background: #4ade80;
      transition: width 0.4s ease, background 0.4s ease;
    }

    /* Reboot button */
    .btn-reboot {
      width: 100%;
      padding: 12px;
      border: none;
      border-radius: 8px;
      background: #7f1d1d;
      color: #fca5a5;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      letter-spacing: 0.03em;
      transition: background 0.2s;
    }
    .btn-reboot:hover  { background: #991b1b; }
    .btn-reboot:active { background: #b91c1c; }

    .footer {
      font-size: 0.72rem;
      color: #475569;
    }
  </style>
</head>
<body>
  <h1>Ping Watchdog</h1>

  <div class="card">
    <div id="badge" class="badge starting">
      <span class="dot"></span>
      <span id="badge-text">Starting…</span>
    </div>

    <div class="stats">
      <div>
        <div class="stat-label">Target IP</div>
        <div class="stat-value" id="target-ip">—</div>
      </div>
      <div>
        <div class="stat-label">Last Check</div>
        <div class="stat-value" id="last-check">—</div>
      </div>
      <div>
        <div class="stat-label">Failures</div>
        <div class="stat-value" id="failures">—</div>
        <div class="bar-wrap">
          <div class="bar-fill" id="bar" style="width:0%"></div>
        </div>
      </div>
      <div>
        <div class="stat-label">Uptime Since</div>
        <div class="stat-value" id="uptime">—</div>
      </div>
    </div>

    <button class="btn-reboot" onclick="confirmReboot()">Trigger Reboot Now</button>
  </div>

  <div class="footer">Auto-refreshes every 3 s &nbsp;·&nbsp; /status for raw JSON</div>

  <script>
    async function fetchStatus() {
      try {
        const r = await fetch('/status');
        const d = await r.json();

        const badge = document.getElementById('badge');
        badge.className = 'badge ' + d.status;
        document.getElementById('badge-text').textContent =
          d.status === 'ok' ? 'Online' :
          d.status === 'failed' ? 'Unreachable' : 'Starting…';

        document.getElementById('target-ip').textContent = d.target_ip;
        document.getElementById('last-check').textContent = d.last_check
          ? d.last_check.split('T')[1] : '—';
        document.getElementById('uptime').textContent = d.uptime_start
          ? d.uptime_start.split('T')[1] : '—';

        const pct = Math.min(100, (d.consecutive_failures / d.failure_threshold) * 100);
        const failEl = document.getElementById('failures');
        failEl.textContent = d.consecutive_failures + ' / ' + d.failure_threshold;
        failEl.className = 'stat-value' + (d.consecutive_failures > 0 ? ' warn' : '');

        const bar = document.getElementById('bar');
        bar.style.width = pct + '%';
        bar.style.background = pct >= 80 ? '#f87171' : pct >= 40 ? '#fb923c' : '#4ade80';
      } catch (_) { /* server restarting */ }
    }

    async function confirmReboot() {
      if (!confirm('This will immediately reboot the system. Continue?')) return;
      await fetch('/reboot', { method: 'POST' });
      document.getElementById('badge-text').textContent = 'Rebooting…';
    }

    fetchStatus();
    setInterval(fetchStatus, 3000);
  </script>
</body>
</html>
"""


class _WatchdogHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass  # silence per-request stdout noise

    def do_GET(self):
        if self.path == "/":
            body = _HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/status":
            body = json.dumps(_read_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/reboot":
            self.send_response(204)
            self.end_headers()
            # Run in a thread so the HTTP response is flushed first
            threading.Thread(target=trigger_reboot, daemon=True).start()
        else:
            self.send_error(404)


def run_web_server() -> None:
    server = HTTPServer((WEB_HOST, WEB_PORT), _WatchdogHandler)
    logging.info(f"Web UI available at http://{WEB_HOST}:{WEB_PORT}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    setup_logging()

    watcher = threading.Thread(target=watchdog_loop, daemon=True, name="watchdog")
    watcher.start()

    run_web_server()  # blocks — runs in the main thread


if __name__ == "__main__":
    main()
