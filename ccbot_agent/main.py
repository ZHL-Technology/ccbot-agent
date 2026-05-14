import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from ccbot_agent import __version__
except ImportError:
    __version__ = "0.1.5"


DEFAULT_CONFIG = Path("/etc/ccbot-agent/config.json")
DEFAULT_STATE = Path("/var/lib/ccbot-agent/state.json")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def write_json(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp_path, mode)
    tmp_path.replace(path)


def machine_id():
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        path = Path(candidate)
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return socket.gethostname()


def run_command(command, timeout=8):
    try:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            timeout=timeout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-2000:],
        }
    except Exception as exc:
        return {"command": command, "exit_code": -1, "stdout": "", "stderr": str(exc)}


def post_json(url, payload, token=None, timeout=20):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {"error": str(exc)}
        return exc.code, payload


def platform_url(config):
    return config["platform_url"].rstrip("/")


def collect_checks():
    if platform.system().lower() == "windows":
        return collect_windows_checks()

    disk_rows = []
    for row in run_command("df -P -x tmpfs -x devtmpfs", timeout=10)["stdout"].splitlines()[1:]:
        parts = row.split()
        if len(parts) >= 6:
            disk_rows.append(
                {
                    "filesystem": parts[0],
                    "used_percent": parts[4],
                    "mount": parts[5],
                }
            )

    meminfo = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = value.strip()
    except Exception:
        pass

    checks = {
        "observed_at": utc_now(),
        "hostname": socket.gethostname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "load_average": os.getloadavg() if hasattr(os, "getloadavg") else [],
        "disk": disk_rows,
        "memory": {
            "mem_total": meminfo.get("MemTotal", ""),
            "mem_available": meminfo.get("MemAvailable", ""),
            "swap_total": meminfo.get("SwapTotal", ""),
            "swap_free": meminfo.get("SwapFree", ""),
        },
        "systemd_failed": run_command("systemctl --failed --no-pager --plain", timeout=10),
        "listening_ports": run_command("ss -tulpen 2>/dev/null | head -n 80", timeout=10),
        "package_updates": collect_package_updates(),
        "certificates": collect_certificate_hints(),
    }
    checks["summary"] = summarize_checks(checks)
    return checks


def collect_windows_checks():
    disk_rows = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if not Path(root).exists():
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        used_percent = round(((usage.total - usage.free) / usage.total) * 100) if usage.total else 0
        disk_rows.append({"filesystem": root, "used_percent": f"{used_percent}%", "mount": root})

    checks = {
        "observed_at": utc_now(),
        "hostname": socket.gethostname(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "load_average": [],
        "disk": disk_rows,
        "memory": run_command(
            'powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json"',
            timeout=12,
        ),
        "systemd_failed": {"command": "Windows service failure collection", "exit_code": 0, "stdout": "", "stderr": ""},
        "listening_ports": run_command("netstat -ano | findstr LISTENING", timeout=12),
        "package_updates": {
            "command": "Windows Update",
            "exit_code": 0,
            "stdout": "",
            "stderr": "Windows Update collection is not enabled in this preview.",
        },
        "certificates": [],
    }
    checks["summary"] = summarize_checks(checks)
    return checks


def collect_package_updates():
    if shutil.which("apt-get"):
        return run_command("apt-get -s upgrade | grep '^Inst ' | head -n 50", timeout=15)
    if shutil.which("dnf"):
        return run_command("dnf check-update --quiet | head -n 50", timeout=20)
    if shutil.which("yum"):
        return run_command("yum check-update --quiet | head -n 50", timeout=20)
    if shutil.which("zypper"):
        return run_command("zypper list-updates | head -n 50", timeout=20)
    if shutil.which("pacman"):
        return run_command("pacman -Qu | head -n 50", timeout=20)
    return {"command": "package manager detection", "exit_code": 0, "stdout": "", "stderr": "No supported package manager found."}


def collect_certificate_hints():
    letsencrypt = Path("/etc/letsencrypt/live")
    if not letsencrypt.exists():
        return []
    certs = []
    for cert in letsencrypt.glob("*/fullchain.pem"):
        result = run_command(f"openssl x509 -enddate -noout -in {cert}", timeout=6)
        certs.append({"path": str(cert), "enddate": result["stdout"].strip(), "error": result["stderr"].strip()})
    return certs[:50]


def summarize_checks(checks):
    warnings = []
    for row in checks.get("disk", []):
        try:
            used = int(str(row.get("used_percent", "0")).rstrip("%"))
        except ValueError:
            used = 0
        if used >= 85:
            warnings.append(f"Disk {row.get('mount')} is {used}% full.")
    failed_output = checks.get("systemd_failed", {}).get("stdout", "")
    if failed_output and "0 loaded units listed" not in failed_output:
        warnings.append("Failed systemd services were reported.")
    return "No urgent issue detected." if not warnings else " ".join(warnings)


def enroll(config_path):
    config = read_json(config_path, {})
    token = config.get("enrollment_token", "").strip()
    if not token:
        raise SystemExit("Missing enrollment_token in config.")
    status, payload = post_json(
        f"{platform_url(config)}/api/agents/enroll/",
        {
            "enrollment_token": token,
            "hostname": socket.gethostname(),
            "machine_id": machine_id(),
            "agent_version": __version__,
        },
    )
    if status not in (200, 201) or not payload.get("ok"):
        raise SystemExit(f"Enrollment failed: {payload}")
    state = read_json(config.get("state_path", str(DEFAULT_STATE)), {})
    state.update(
        {
            "agent_id": payload["agent_id"],
            "agent_token": payload["agent_token"],
            "heartbeat_url": payload["heartbeat_url"],
            "report_url": payload["report_url"],
            "enrolled_at": utc_now(),
        }
    )
    write_json(config.get("state_path", str(DEFAULT_STATE)), state)
    config.pop("enrollment_token", None)
    write_json(config_path, config)
    print("CCBot agent enrolled.")


def ensure_enrolled(config_path):
    config = read_json(config_path, {})
    state = read_json(config.get("state_path", str(DEFAULT_STATE)), {})
    if state.get("agent_token"):
        return config, state
    enroll(config_path)
    config = read_json(config_path, {})
    state = read_json(config.get("state_path", str(DEFAULT_STATE)), {})
    return config, state


def send_heartbeat(config, state):
    checks = collect_checks()
    payload = {
        "hostname": socket.gethostname(),
        "machine_id": machine_id(),
        "agent_version": __version__,
        "checks": checks,
    }
    return post_json(state["heartbeat_url"], payload, token=state["agent_token"])


def send_report(config, state, period="daily"):
    checks = collect_checks()
    severity = "warning" if checks["summary"] != "No urgent issue detected." else "info"
    payload = {
        "period": period,
        "severity": severity,
        "summary": checks["summary"],
        "checks": checks,
        "agent_version": __version__,
    }
    return post_json(state["report_url"], payload, token=state["agent_token"])


def run_loop(config_path):
    config, state = ensure_enrolled(config_path)
    interval = int(config.get("heartbeat_seconds", 300))
    report_every = int(config.get("report_every_seconds", 86400))
    last_report = float(state.get("last_report_ts", 0))
    while True:
        status, payload = send_heartbeat(config, state)
        if status >= 400:
            print(f"Heartbeat failed: {payload}", file=sys.stderr)
        now = time.time()
        if now - last_report >= report_every:
            status, payload = send_report(config, state, period="daily")
            if status < 400:
                state["last_report_ts"] = now
                write_json(config.get("state_path", str(DEFAULT_STATE)), state)
                last_report = now
            else:
                print(f"Report failed: {payload}", file=sys.stderr)
        time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description="CCBot Agent")
    parser.add_argument("--version", action="version", version=f"CCBot Agent {__version__}")
    parser.add_argument("command", choices=["collect", "enroll", "run"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)

    if args.command == "collect":
        print(json.dumps(collect_checks(), indent=2))
    elif args.command == "enroll":
        enroll(args.config)
    elif args.command == "run":
        run_loop(args.config)


if __name__ == "__main__":
    main()
