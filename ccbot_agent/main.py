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
    __version__ = "0.1.18"


DEFAULT_CONFIG = Path("/etc/ccbot-agent/config.json")
DEFAULT_STATE = Path("/var/lib/ccbot-agent/state.json")
AUDIT_CHECKLIST_VERSION = "2026.05.23"

AUDIT_CHECKLIST_ITEMS = (
    ("device_identity", "Device identity", ("observed_at", "hostname", "platform")),
    ("resource_posture", "CPU, load, memory, and storage posture", ("load_average", "memory", "disk")),
    ("listening_services", "Listening services and exposed ports", ("listening_ports",)),
    ("service_health", "Failed or unhealthy services", ("systemd_failed", "windows_services")),
    ("patch_posture", "Operating system and package update hints", ("package_updates",)),
    ("certificate_posture", "Certificate inventory and expiry hints", ("certificates",)),
    ("gpu_posture", "GPU and accelerator driver health", ("gpu",)),
    ("firewall_posture", "Host firewall posture", ("firewall",)),
    ("authentication_posture", "Authentication and remote access policy", ("auth_policy",)),
    ("privileged_accounts", "Privileged local accounts and admin groups", ("local_accounts",)),
    ("scheduled_work", "Scheduled jobs, timers, and automation", ("scheduled_tasks",)),
    ("container_runtime", "Container runtime exposure", ("containers",)),
    ("security_logs", "Recent high-severity system/security logs", ("security_logs",)),
    ("time_sync", "Clock and time synchronization", ("time_sync",)),
    ("backup_signals", "Backup tooling and scheduling signals", ("backup_hints",)),
    ("kernel_network_policy", "Kernel and network hardening policy", ("kernel_network_policy",)),
    ("endpoint_protection", "Endpoint protection and audit service signals", ("endpoint_protection",)),
)


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


def command_available(name):
    return shutil.which(name) is not None


def checklist_evidence_status(checks, keys):
    present = []
    review = []
    unavailable = []
    for key in keys:
        value = checks.get(key)
        if value in (None, "", [], {}):
            unavailable.append(key)
            continue
        present.append(key)
        if isinstance(value, dict):
            status = str(value.get("status") or "").lower()
            stderr = str(value.get("stderr") or "")
            exit_code = value.get("exit_code")
            if status in {"driver_error", "driver_unavailable", "not_supported", "limited", "error"}:
                review.append(key)
            elif exit_code not in (None, 0) and stderr:
                review.append(key)
        elif key == "certificates" and isinstance(value, list):
            for cert in value:
                if isinstance(cert, dict) and cert.get("error"):
                    review.append(key)
                    break
    if present and review:
        status = "needs_review"
    elif present:
        status = "checked"
    else:
        status = "not_collected"
    return status, present, review, unavailable


def build_audit_checklist(checks):
    items = []
    counts = {"checked": 0, "needs_review": 0, "not_collected": 0}
    for item_id, title, evidence_keys in AUDIT_CHECKLIST_ITEMS:
        status, present, review, unavailable = checklist_evidence_status(checks, evidence_keys)
        counts[status] = counts.get(status, 0) + 1
        items.append(
            {
                "id": item_id,
                "title": title,
                "status": status,
                "evidence": present,
                "review_evidence": review,
                "missing_evidence": unavailable,
            }
        )
    return {
        "version": AUDIT_CHECKLIST_VERSION,
        "generated_at": utc_now(),
        "counts": counts,
        "items": items,
        "legal_note": (
            "This checklist is an audit trail of collected signals, not an absolute guarantee. "
            "Items marked not_collected or needs_review identify areas that require access, configuration, "
            "a supported operating system feature, or human review."
        ),
    }


def post_json(url, payload, token=None, timeout=20):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"CCBot-Agent/{__version__} (+https://cybercareai.io)",
    }
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
        if payload.get("error_code") == 1010:
            payload["error"] = (
                "Cloudflare blocked this CCBot request before it reached CyberCare AI "
                "(Error 1010: Access denied). The /api/agents/ endpoints need to allow "
                "CCBot Agent traffic."
            )
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return 0, {
            "ok": False,
            "code": "network_unreachable",
            "error": (
                "CCBot Agent could not reach the CyberCare AI platform. It will retry "
                "automatically. Check DNS, internet access, firewall, proxy, or the "
                "configured platform URL."
            ),
            "detail": str(reason),
            "url": url,
        }


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
        "gpu": collect_gpu_checks(),
        "firewall": collect_firewall_posture(),
        "auth_policy": collect_auth_policy(),
        "local_accounts": collect_local_accounts(),
        "scheduled_tasks": collect_scheduled_tasks(),
        "containers": collect_container_posture(),
        "security_logs": collect_security_logs(),
        "time_sync": collect_time_sync(),
        "backup_hints": collect_backup_hints(),
        "kernel_network_policy": collect_kernel_network_policy(),
        "endpoint_protection": collect_endpoint_protection(),
    }
    checks["audit_checklist"] = build_audit_checklist(checks)
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
        "gpu": collect_windows_gpu_checks(),
        "windows_services": collect_windows_service_health(),
        "firewall": collect_windows_firewall_posture(),
        "auth_policy": collect_windows_auth_policy(),
        "local_accounts": collect_windows_local_accounts(),
        "scheduled_tasks": collect_windows_scheduled_tasks(),
        "containers": collect_windows_container_posture(),
        "security_logs": collect_windows_security_logs(),
        "time_sync": collect_windows_time_sync(),
        "backup_hints": collect_windows_backup_hints(),
        "kernel_network_policy": {
            "status": "not_supported",
            "stdout": "",
            "stderr": "Kernel sysctl collection is Linux-specific.",
        },
        "endpoint_protection": collect_windows_endpoint_protection(),
    }
    checks["audit_checklist"] = build_audit_checklist(checks)
    checks["summary"] = summarize_checks(checks)
    return checks


def parse_nvidia_smi_csv(output):
    devices = []
    for row in str(output or "").splitlines():
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 6:
            continue
        device = {
            "name": parts[0],
            "driver_version": parts[1],
            "utilization_gpu": parts[2],
            "memory_used_mib": parts[3],
            "memory_total_mib": parts[4],
            "temperature_c": parts[5],
        }
        devices.append(device)
    return devices


def collect_gpu_checks():
    lspci = (
        run_command("lspci | grep -Ei 'vga|3d|display|nvidia|amd/ati' | head -n 20", timeout=6)
        if shutil.which("lspci")
        else {"command": "lspci", "exit_code": 127, "stdout": "", "stderr": "lspci is not installed."}
    )
    has_nvidia_hardware = "nvidia" in f"{lspci.get('stdout', '')} {lspci.get('stderr', '')}".lower()
    nvidia_smi_path = shutil.which("nvidia-smi")
    nvidia_smi = None
    devices = []
    status = "not_detected"
    diagnostic = ""

    if nvidia_smi_path:
        nvidia_smi = run_command(
            "nvidia-smi --query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu "
            "--format=csv,noheader,nounits",
            timeout=10,
        )
        devices = parse_nvidia_smi_csv(nvidia_smi.get("stdout", ""))
        if nvidia_smi.get("exit_code") == 0:
            status = "ok" if devices else "no_nvidia_gpu_reported"
        else:
            status = "driver_error"
            diagnostic = (nvidia_smi.get("stderr") or nvidia_smi.get("stdout") or "nvidia-smi failed.").strip()
    elif has_nvidia_hardware:
        status = "driver_unavailable"
        diagnostic = "NVIDIA hardware was detected, but nvidia-smi is not available in PATH."
    elif lspci.get("stdout"):
        status = "gpu_detected"

    return {
        "status": status,
        "devices": devices,
        "diagnostic": diagnostic[-2000:],
        "nvidia_smi": nvidia_smi,
        "pci_display": lspci,
    }


def collect_windows_gpu_checks():
    video_controllers = run_command(
        'powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | '
        'Select-Object Name,DriverVersion,AdapterRAM,Status | ConvertTo-Json -Compress"',
        timeout=12,
    )
    nvidia_smi = run_command(
        'powershell -NoProfile -Command "if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { '
        'nvidia-smi --query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu '
        '--format=csv,noheader,nounits }"',
        timeout=12,
    )
    devices = parse_nvidia_smi_csv(nvidia_smi.get("stdout", ""))
    status = "ok" if devices else ("collected" if video_controllers.get("stdout") else "not_detected")
    diagnostic = ""
    if nvidia_smi.get("exit_code") not in (0, None) and nvidia_smi.get("stderr"):
        status = "driver_error"
        diagnostic = nvidia_smi.get("stderr", "").strip()
    return {
        "status": status,
        "devices": devices,
        "diagnostic": diagnostic[-2000:],
        "nvidia_smi": nvidia_smi,
        "video_controllers": video_controllers,
    }


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


def collect_firewall_posture():
    commands = []
    if command_available("ufw"):
        commands.append("ufw status verbose")
    if command_available("firewall-cmd"):
        commands.append("firewall-cmd --state; firewall-cmd --list-all")
    if command_available("nft"):
        commands.append("nft list ruleset | head -n 140")
    if command_available("iptables"):
        commands.append("iptables -S | head -n 140")
    if not commands:
        return {"status": "not_collected", "stdout": "", "stderr": "No supported firewall tool found."}
    return run_command(" ; ".join(f"( {command} )" for command in commands), timeout=15)


def collect_auth_policy():
    command = (
        "if command -v sshd >/dev/null 2>&1; then "
        "sshd -T 2>/dev/null | grep -Ei "
        "'^(permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|maxauthtries|permitemptypasswords|allowusers|allowgroups)' ; "
        "else "
        "grep -RhsEi '^\\s*(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|KbdInteractiveAuthentication|MaxAuthTries|PermitEmptyPasswords|AllowUsers|AllowGroups)' "
        "/etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null ; "
        "fi"
    )
    return run_command(command, timeout=8)


def collect_local_accounts():
    command = (
        "getent passwd | awk -F: '($3==0 || $3>=1000){print $1 \":\" $3 \":\" $7}' | head -n 120; "
        "getent group sudo wheel admin 2>/dev/null"
    )
    return run_command(command, timeout=8)


def collect_scheduled_tasks():
    command = (
        "systemctl list-timers --all --no-pager --plain 2>/dev/null | head -n 120; "
        "ls -la /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly /etc/cron.monthly 2>/dev/null"
    )
    return run_command(command, timeout=10)


def collect_container_posture():
    commands = []
    if command_available("docker"):
        commands.append("docker ps --format 'docker {{.Names}} {{.Image}} {{.Ports}} {{.Status}}' 2>/dev/null | head -n 80")
    if command_available("podman"):
        commands.append("podman ps --format 'podman {{.Names}} {{.Image}} {{.Ports}} {{.Status}}' 2>/dev/null | head -n 80")
    if not commands:
        return {"status": "not_collected", "stdout": "", "stderr": "No supported container runtime found."}
    return run_command(" ; ".join(commands), timeout=12)


def collect_security_logs():
    if command_available("journalctl"):
        return run_command("journalctl -p warning..alert -n 80 --no-pager 2>/dev/null", timeout=12)
    return {"status": "not_collected", "stdout": "", "stderr": "journalctl is not available."}


def collect_time_sync():
    if command_available("timedatectl"):
        return run_command("timedatectl status", timeout=8)
    return run_command("date -u", timeout=5)


def collect_backup_hints():
    command = (
        "systemctl list-timers --all --no-pager --plain 2>/dev/null | grep -Ei 'backup|borg|restic|rsnapshot|duplicity|timeshift|rclone' || true; "
        "for tool in borg restic rsnapshot duplicity timeshift rclone; do command -v \"$tool\" >/dev/null 2>&1 && echo \"tool:$tool\"; done"
    )
    return run_command(command, timeout=10)


def collect_kernel_network_policy():
    keys = (
        "net.ipv4.ip_forward "
        "net.ipv4.conf.all.accept_redirects "
        "net.ipv4.conf.default.accept_redirects "
        "net.ipv4.conf.all.send_redirects "
        "net.ipv4.conf.all.rp_filter "
        "net.ipv4.tcp_syncookies "
        "net.ipv6.conf.all.accept_redirects"
    )
    return run_command(f"sysctl {keys}", timeout=8)


def collect_endpoint_protection():
    command = (
        "systemctl is-active auditd 2>/dev/null | sed 's/^/auditd:/' || true; "
        "systemctl is-active clamav-daemon 2>/dev/null | sed 's/^/clamav-daemon:/' || true; "
        "command -v clamscan >/dev/null 2>&1 && clamscan --version | head -n 1 || true"
    )
    return run_command(command, timeout=8)


def collect_windows_service_health():
    return run_command(
        'powershell -NoProfile -Command "Get-CimInstance Win32_Service | '
        "Where-Object {$_.StartMode -eq 'Auto' -and $_.State -ne 'Running'} | "
        'Select-Object -First 40 Name,DisplayName,State,StartMode | ConvertTo-Json -Compress"',
        timeout=14,
    )


def collect_windows_firewall_posture():
    return run_command(
        'powershell -NoProfile -Command "Get-NetFirewallProfile | '
        'Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction | ConvertTo-Json -Compress"',
        timeout=12,
    )


def collect_windows_auth_policy():
    return run_command("net accounts", timeout=10)


def collect_windows_local_accounts():
    return run_command("net user && net localgroup administrators", timeout=12)


def collect_windows_scheduled_tasks():
    return run_command(
        'powershell -NoProfile -Command "Get-ScheduledTask | '
        'Select-Object -First 80 TaskName,State,TaskPath | ConvertTo-Json -Compress"',
        timeout=14,
    )


def collect_windows_container_posture():
    return run_command(
        'powershell -NoProfile -Command "if (Get-Command docker -ErrorAction SilentlyContinue) { '
        "docker ps --format '{{.Names}} {{.Image}} {{.Ports}} {{.Status}}' }\"",
        timeout=12,
    )


def collect_windows_security_logs():
    return run_command(
        'powershell -NoProfile -Command "Get-WinEvent -LogName System -MaxEvents 40 | '
        "Where-Object {$_.LevelDisplayName -in @('Critical','Error','Warning')} | "
        'Select-Object TimeCreated,ProviderName,LevelDisplayName,Id,Message | ConvertTo-Json -Compress"',
        timeout=16,
    )


def collect_windows_time_sync():
    return run_command("w32tm /query /status", timeout=10)


def collect_windows_backup_hints():
    return run_command(
        'powershell -NoProfile -Command "Get-ScheduledTask | '
        "Where-Object {$_.TaskName -match 'backup|restore|history|sync'} | "
        'Select-Object TaskName,State,TaskPath | ConvertTo-Json -Compress"',
        timeout=12,
    )


def collect_windows_endpoint_protection():
    return run_command(
        'powershell -NoProfile -Command "if (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) { '
        'Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled,AntispywareEnabled,NISEnabled | ConvertTo-Json -Compress }"',
        timeout=12,
    )


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
    gpu = checks.get("gpu") or {}
    if gpu.get("status") in {"driver_error", "driver_unavailable"}:
        detail = gpu.get("diagnostic") or gpu.get("status")
        warnings.append(f"GPU driver diagnostics need review: {detail[:180]}.")
    for device in gpu.get("devices") or []:
        try:
            utilization = int(float(str(device.get("utilization_gpu", "0")).rstrip("%")))
            temperature = int(float(str(device.get("temperature_c", "0")).rstrip("C")))
        except (TypeError, ValueError):
            continue
        if utilization >= 92 or temperature >= 82:
            warnings.append(
                f"GPU {device.get('name', 'device')} is at {utilization}% utilization and {temperature}C."
            )
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
        code = payload.get("code")
        if code in {"invalid_token", "token_already_used", "token_revoked", "token_expired"}:
            detail = payload.get("error") or "The enrollment token could not be accepted."
            raise SystemExit(
                f"{detail}\n\n"
                "Open CyberCare AI > CCBot install, create a new install token, copy it once, "
                "and paste that fresh token into this installer."
            )
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
        try:
            status, payload = send_heartbeat(config, state)
            if status == 0 or status >= 400:
                print(f"Heartbeat failed: {payload}", file=sys.stderr)
            now = time.time()
            if now - last_report >= report_every:
                status, payload = send_report(config, state, period="daily")
                if 200 <= status < 400:
                    state["last_report_ts"] = now
                    write_json(config.get("state_path", str(DEFAULT_STATE)), state)
                    last_report = now
                else:
                    print(f"Report failed: {payload}", file=sys.stderr)
        except Exception as exc:
            print(f"CCBot Agent runtime error: {exc}", file=sys.stderr)
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
