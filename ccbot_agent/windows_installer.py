import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

from ccbot_agent import __version__
from ccbot_agent.main import enroll, run_loop


APP_NAME = "CCBot Agent"
DEFAULT_PLATFORM_URL = "https://cybercareai.io"
UPDATE_MANIFEST_URL = os.environ.get(
    "CCBOT_UPDATE_MANIFEST_URL",
    "https://cybercareai.io/static/downloads/ccbot-agent-latest.json",
)
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
APP_DIR = PROGRAM_DATA / "CCBotAgent"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
UPDATE_DIR = APP_DIR / "updates"
TASK_NAME = "CCBot Agent"
RUN_KEY_PATH = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_MANIFEST_HOSTS = {"cybercareai.io", "www.cybercareai.io"}
UPDATE_DOWNLOAD_HOSTS = {
    "cybercareai.io",
    "www.cybercareai.io",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

TERMS_TEXT = """CCBot Agent will enroll this Windows device with CyberCare AI and start continuous monitoring for security hygiene and system health signals.

By continuing, you confirm that:

1. You own this device or have permission to monitor it.
2. You understand that CCBot collects operational evidence such as hostname, operating system details, disk usage, listening ports, update hints, and service health signals.
3. CCBot does not intentionally read personal documents in this preview, but operational data can include sensitive names, paths, services, package names, usernames, and process metadata.
4. You are responsible for reviewing alerts, recommendations, and any future remediation steps before applying changes.
5. A valid CyberCare AI plan and one-time install token are required for activation.

Only continue if you understand and agree to these conditions."""


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base_path / relative_path


def configure_window_identity(root):
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CyberCareAI.CCBotAgent")
        except Exception:
            pass

    icon_path = resource_path("assets/ccbot.ico")
    image_path = resource_path("assets/ccbot.png")
    try:
        if icon_path.exists():
            root.iconbitmap(default=str(icon_path))
    except Exception:
        pass
    try:
        if image_path.exists():
            icon_image = tk.PhotoImage(file=str(image_path))
            root.iconphoto(True, icon_image)
            root._ccbot_icon_image = icon_image
    except Exception:
        pass


def display_version(version):
    value = str(version or "").strip()
    return value if value.lower().startswith("v") else f"v{value}"


def parse_version(value):
    numbers = [int(part) for part in re.findall(r"\d+", str(value or ""))[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def is_newer_version(latest_version, current_version=__version__):
    return parse_version(latest_version) > parse_version(current_version)


def is_enrollment_token_error(message):
    text = str(message or "").lower()
    return any(
        marker in text
        for marker in (
            "invalid_token",
            "token is invalid",
            "token is expired",
            "token has expired",
            "expired",
            "used",
            "revoked",
        )
    )


def validate_update_url(url, allowed_hosts):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in allowed_hosts:
        raise ValueError(f"Unsupported update URL: {url}")
    return parsed.geturl()


def update_request(url):
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
            "User-Agent": f"CCBot-Windows-Installer/{__version__} (+https://cybercareai.io)",
        },
    )


def fetch_latest_update():
    manifest_url = validate_update_url(UPDATE_MANIFEST_URL, UPDATE_MANIFEST_HOSTS)
    try:
        with urllib.request.urlopen(update_request(manifest_url), timeout=20) as response:
            payload = json.loads(response.read(128 * 1024).decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not check for updates: {exc}") from exc

    latest_version = str(payload.get("version") or payload.get("tag") or "").strip().lstrip("vV")
    download_url = str(payload.get("windows_installer_url") or payload.get("download_url") or "").strip()
    release_notes_url = str(payload.get("release_notes_url") or "").strip()
    if not latest_version or not download_url:
        raise RuntimeError("The update manifest is missing version or Windows installer URL.")

    download_url = validate_update_url(download_url, UPDATE_DOWNLOAD_HOSTS)
    if release_notes_url:
        release_notes_url = validate_update_url(release_notes_url, UPDATE_DOWNLOAD_HOSTS)

    if not is_newer_version(latest_version):
        return None

    return {
        "version": latest_version,
        "display_version": display_version(latest_version),
        "download_url": download_url,
        "release_notes_url": release_notes_url,
        "notes": str(payload.get("notes") or "").strip(),
    }


def download_update_installer(update_info, status_callback, progress_callback, log_callback):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    version_label = display_version(update_info["version"])
    target = UPDATE_DIR / f"CCBot-Windows-Installer-{version_label}.exe"
    temporary = target.with_suffix(".download")

    status_callback(f"Downloading CCBot Agent {version_label}...")
    log_callback(f"Downloading update from {update_info['download_url']}")
    progress_callback(4)

    try:
        with urllib.request.urlopen(update_request(update_info["download_url"]), timeout=120) as response:
            validate_update_url(response.geturl(), UPDATE_DOWNLOAD_HOSTS)
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        progress_callback(min(92, 8 + int((downloaded / total) * 84)))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise RuntimeError(f"Could not download the update: {exc}") from exc

    if temporary.stat().st_size < 1024 * 1024:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise RuntimeError("The downloaded update file is unexpectedly small.")

    temporary.replace(target)
    progress_callback(96)
    log_callback(f"Update downloaded to {target}")
    return target


def write_config(platform_url, enrollment_token):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(
            {
                "platform_url": platform_url.rstrip("/"),
                "enrollment_token": enrollment_token.strip(),
                "heartbeat_seconds": 300,
                "report_every_seconds": 86400,
                "state_path": str(STATE_PATH).replace("\\", "/"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_hidden(command, **kwargs):
    kwargs.setdefault("check", False)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("text", True)
    if sys.platform.startswith("win"):
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(command, **kwargs)


def wait_for_pid_exit(pid, timeout=20):
    if not pid or not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(pid))
        if handle:
            try:
                ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        time.sleep(min(timeout, 2))


def stop_existing_agent_processes(target):
    if not sys.platform.startswith("win"):
        return
    run_hidden(["schtasks", "/End", "/TN", TASK_NAME], timeout=10)
    target_text = str(target.resolve()).replace("'", "''")
    current_pid = os.getpid()
    script = (
        f"$target = '{target_text}'; "
        f"$currentPid = {current_pid}; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ExecutablePath -and "
        "(([System.IO.Path]::GetFullPath($_.ExecutablePath)) -ieq $target) -and "
        "($_.ProcessId -ne $currentPid) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    try:
        run_hidden(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=15,
        )
    except FileNotFoundError:
        pass
    time.sleep(1)


def copy_executable_with_retries(source, target, attempts=12):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for _attempt in range(attempts):
        try:
            shutil.copy2(source, target)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Could not replace the installed CCBot executable: {last_error}") from last_error


def current_executable_target():
    if getattr(sys, "frozen", False):
        target = APP_DIR / "CCBot-Windows-Installer.exe"
        if Path(sys.executable).resolve() != target.resolve():
            stop_existing_agent_processes(target)
            copy_executable_with_retries(sys.executable, target)
        return target
    return Path(sys.executable)


def quoted_agent_command(executable):
    return f'"{executable}" --agent-run --config "{CONFIG_PATH}"'


def create_scheduled_task(command):
    completed = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONLOGON",
            "/TR",
            command,
            "/F",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode == 0:
        return "Windows scheduled task"
    detail = completed.stderr.strip() or completed.stdout.strip() or "Windows did not return a detailed error."
    raise RuntimeError(detail)


def create_current_user_run_key(command):
    completed = subprocess.run(
        [
            "reg",
            "add",
            RUN_KEY_PATH,
            "/v",
            TASK_NAME,
            "/t",
            "REG_SZ",
            "/d",
            command,
            "/f",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode == 0:
        return "current-user Windows startup"
    detail = completed.stderr.strip() or completed.stdout.strip() or "Windows did not return a detailed error."
    raise RuntimeError(detail)


def create_startup_entry(executable):
    command = quoted_agent_command(executable)
    try:
        return create_scheduled_task(command)
    except RuntimeError as scheduled_task_error:
        try:
            method = create_current_user_run_key(command)
        except RuntimeError as run_key_error:
            raise RuntimeError(
                "Could not register CCBot to start with Windows. "
                f"Scheduled task error: {scheduled_task_error}. "
                f"Current-user startup error: {run_key_error}."
            ) from run_key_error
        return f"{method} (scheduled task was blocked: {scheduled_task_error})"


def start_agent(executable):
    subprocess.Popen(
        [str(executable), "--agent-run", "--config", str(CONFIG_PATH)],
        cwd=str(APP_DIR),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def write_failure_log(error_text):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log_path = APP_DIR / "install-error.log"
        log_path.write_text(error_text, encoding="utf-8")
        return log_path
    except Exception:
        return None


def show_update_message(title, message, kind="info"):
    root = tk.Tk()
    root.withdraw()
    configure_window_identity(root)
    try:
        if kind == "error":
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def apply_self_update(config_path, parent_pid=0):
    target = APP_DIR / "CCBot-Windows-Installer.exe"
    try:
        wait_for_pid_exit(parent_pid)
        stop_existing_agent_processes(target)
        copy_executable_with_retries(sys.executable, target)
        startup_method = create_startup_entry(target)
        if Path(config_path).exists():
            start_agent(target)
        show_update_message(
            "CCBot update complete",
            (
                f"CCBot Agent {display_version(__version__)} has been installed.\n\n"
                f"Startup method: {startup_method}"
            ),
        )
        return 0
    except BaseException as exc:
        message = str(exc) or exc.__class__.__name__
        error_text = f"Update failed: {message}\n\nTraceback:\n{traceback.format_exc()}"
        log_path = write_failure_log(error_text)
        if log_path:
            error_text = f"{error_text}\n\nSaved log file:\n{log_path}"
        show_update_message("CCBot update failed", error_text, kind="error")
        return 1


def install(platform_url, enrollment_token, status_callback, progress_callback, log_callback):
    if not enrollment_token.strip():
        raise ValueError("Paste the one-time install token from CyberCare AI.")

    def step(percent, message):
        status_callback(message)
        progress_callback(percent)
        log_callback(message)

    step(8, "Checking installer inputs...")
    platform_url = platform_url.strip() or DEFAULT_PLATFORM_URL
    if not platform_url.startswith(("http://", "https://")):
        raise ValueError("Platform URL must start with https:// or http://.")

    step(20, "Writing local configuration...")
    write_config(platform_url, enrollment_token)
    step(45, "Enrolling this Windows device with CyberCare AI...")
    try:
        enroll(str(CONFIG_PATH))
    except BaseException as exc:
        message = str(exc) or exc.__class__.__name__
        raise RuntimeError(message) from exc

    step(65, "Preparing Windows startup...")
    executable = current_executable_target()
    startup_method = create_startup_entry(executable)
    log_callback(f"Startup registered with {startup_method}.")

    step(82, "Starting CCBot in the background...")
    start_agent(executable)
    step(100, "Installation complete. CCBot is running. You can close this window.")


def launch_gui():
    root = tk.Tk()
    root.title(APP_NAME)
    configure_window_identity(root)
    root.geometry("760x790")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    header = ttk.Frame(frame)
    header.pack(fill="x")
    header_copy = ttk.Frame(header)
    header_copy.pack(side="left", fill="x", expand=True)
    ttk.Label(header_copy, text="Install CCBot for Windows", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(header_copy, text=f"Current version: {display_version(__version__)}").pack(anchor="w", pady=(4, 0))
    update_header = ttk.Frame(header)
    update_header.pack(side="right", anchor="ne")
    check_update_button = ttk.Button(update_header, text="Check for updates", width=18)
    check_update_button.pack(anchor="e")
    ttk.Label(
        frame,
        text="Paste the one-time install token from CyberCare AI. The installer will enroll this device and start monitoring.",
        wraplength=620,
    ).pack(anchor="w", pady=(10, 18))

    ttk.Label(frame, text="Platform URL").pack(anchor="w")
    platform_var = tk.StringVar(value=DEFAULT_PLATFORM_URL)
    platform_entry = ttk.Entry(frame, textvariable=platform_var)
    platform_entry.pack(fill="x", pady=(4, 14))

    ttk.Label(frame, text="Install token").pack(anchor="w")
    token_var = tk.StringVar()
    token_row = ttk.Frame(frame)
    token_row.pack(fill="x", pady=(4, 14))
    token_entry = ttk.Entry(token_row, textvariable=token_var, show="*")
    token_entry.pack(side="left", fill="x", expand=True)
    paste_button = ttk.Button(token_row, text="Paste", width=10)
    paste_button.pack(side="left", padx=(8, 0))

    def paste_from_clipboard(entry):
        try:
            entry.delete(0, "end")
            entry.insert(0, root.clipboard_get().strip())
        except tk.TclError:
            pass
        refresh_install_button()
        return "break"

    def attach_entry_menu(entry):
        def copy_selection():
            try:
                selected_text = entry.selection_get()
            except tk.TclError:
                return
            root.clipboard_clear()
            root.clipboard_append(selected_text)

        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Paste", command=lambda: paste_from_clipboard(entry))
        menu.add_command(label="Copy", command=copy_selection)
        menu.add_command(label="Select all", command=lambda: (entry.select_range(0, "end"), entry.icursor("end")))

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        entry.bind("<Button-3>", show_menu)
        entry.bind("<Control-v>", lambda _event: paste_from_clipboard(entry))
        entry.bind("<Control-V>", lambda _event: paste_from_clipboard(entry))
        entry.bind("<Shift-Insert>", lambda _event: paste_from_clipboard(entry))

    attach_entry_menu(platform_entry)
    attach_entry_menu(token_entry)
    paste_button.configure(command=lambda: paste_from_clipboard(token_entry))

    terms_box = ttk.LabelFrame(frame, text="Terms and responsibility")
    terms_box.pack(fill="x", pady=(0, 12))

    terms_content = ttk.Frame(terms_box)
    terms_content.pack(fill="x", padx=10, pady=(8, 6))
    terms_scrollbar = ttk.Scrollbar(terms_content, orient="vertical")
    terms_text = tk.Text(
        terms_content,
        height=7,
        wrap="word",
        relief="flat",
        padx=8,
        pady=8,
        yscrollcommand=terms_scrollbar.set,
    )
    terms_scrollbar.config(command=terms_text.yview)
    terms_text.insert("1.0", TERMS_TEXT)
    terms_text.configure(state="disabled")
    terms_text.pack(side="left", fill="both", expand=True)
    terms_scrollbar.pack(side="right", fill="y")

    accepted_var = tk.BooleanVar(value=False)
    terms_check = ttk.Checkbutton(
        terms_box,
        text="I have read and agree to these terms.",
        variable=accepted_var,
    )
    terms_check.pack(anchor="w", padx=10, pady=(0, 10))

    status_var = tk.StringVar(value="Ready")
    ttk.Label(frame, textvariable=status_var, wraplength=630).pack(anchor="w", pady=(0, 8))

    progress_var = tk.IntVar(value=0)
    progress = ttk.Progressbar(frame, maximum=100, variable=progress_var)
    progress.pack(fill="x", pady=(0, 12))

    actions = ttk.Frame(frame)
    actions.pack(fill="x", pady=(0, 14))

    install_button = ttk.Button(actions, text="Install and start CCBot", state="disabled")
    install_button.pack(side="left")
    copy_log_button = ttk.Button(actions, text="Copy log", command=lambda: copy_log())
    copy_log_button.pack(side="left", padx=(8, 0))
    ttk.Label(
        actions,
        text="The install button activates after the token is pasted and the terms are accepted.",
        wraplength=500,
    ).pack(
        side="left",
        padx=(12, 0),
    )

    log_label = ttk.Label(frame, text="Installation log")
    log_label.pack(anchor="w")
    log_frame = ttk.Frame(frame)
    log_frame.pack(fill="both", expand=True, pady=(4, 14))
    log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical")
    log_text = tk.Text(
        log_frame,
        height=8,
        wrap="word",
        relief="solid",
        borderwidth=1,
        padx=8,
        pady=8,
        bg="#0f172a",
        fg="#e5eefc",
        insertbackground="#e5eefc",
        yscrollcommand=log_scrollbar.set,
    )
    log_scrollbar.config(command=log_text.yview)
    initial_log = "Ready. Paste your token, review the terms, then start installation."
    log_messages = [initial_log]
    log_text.insert("1.0", f"{initial_log}\n")
    log_text.configure(state="disabled")
    log_text.pack(side="left", fill="both", expand=True)
    log_scrollbar.pack(side="right", fill="y")

    def copy_text(text):
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()

    def current_log_text():
        return "\n".join(log_messages).strip()

    def show_error_dialog(title, message, *, technical_details=""):
        dialog = tk.Toplevel(root)
        dialog.title(title)
        configure_window_identity(dialog)
        dialog.geometry("660x260" if not technical_details else "660x430")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text=message,
            wraplength=600,
        ).pack(anchor="w", pady=(6, 12))

        if technical_details:
            error_frame = ttk.Frame(body)
            error_frame.pack(fill="both", expand=True)
            error_scrollbar = ttk.Scrollbar(error_frame, orient="vertical")
            error_box = tk.Text(
                error_frame,
                height=10,
                wrap="word",
                relief="solid",
                borderwidth=1,
                padx=8,
                pady=8,
                bg="#0f172a",
                fg="#e5eefc",
                insertbackground="#e5eefc",
                yscrollcommand=error_scrollbar.set,
            )
            error_scrollbar.config(command=error_box.yview)
            error_box.insert("1.0", technical_details)
            error_box.configure(state="disabled")
            error_box.pack(side="left", fill="both", expand=True)
            error_scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        if technical_details:
            ttk.Button(buttons, text="Copy technical details", command=lambda: copy_text(technical_details)).pack(side="left")
        ttk.Button(buttons, text="Try again", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Exit installer", command=root.destroy).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.wait_window()

    def copy_log():
        text = current_log_text()
        if text:
            copy_text(text)

    def set_status(message):
        root.after(0, lambda: status_var.set(message))

    def set_progress(value):
        root.after(0, lambda: progress_var.set(value))

    def append_log(message):
        log_messages.append(message)

        def update():
            log_text.configure(state="normal")
            log_text.insert("end", f"{message}\n")
            log_text.see("end")
            log_text.configure(state="disabled")

        root.after(0, update)

    def inputs_valid():
        return bool(token_var.get().strip()) and accepted_var.get()

    def refresh_install_button(*_args):
        install_button.configure(state="normal" if inputs_valid() else "disabled")

    token_var.trace_add("write", refresh_install_button)
    accepted_var.trace_add("write", refresh_install_button)

    def set_inputs_state(state):
        terms_check.configure(state=state)
        paste_button.configure(state=state)
        platform_entry.configure(state=state)
        token_entry.configure(state=state)

    def launch_downloaded_update(installer_path):
        subprocess.Popen(
            [
                str(installer_path),
                "--apply-update",
                "--config",
                str(CONFIG_PATH),
                "--parent-pid",
                str(os.getpid()),
            ],
            cwd=str(installer_path.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def run_update(update_info):
        root.after(0, lambda: set_inputs_state("disabled"))
        root.after(0, lambda: install_button.configure(state="disabled"))
        root.after(0, lambda: check_update_button.configure(state="disabled"))
        set_progress(0)
        try:
            installer_path = download_update_installer(update_info, set_status, set_progress, append_log)
            set_status("Launching the updated CCBot installer...")
            append_log("Starting the self-update helper.")
            launch_downloaded_update(installer_path)
            root.after(350, root.destroy)
        except BaseException as exc:
            message = str(exc) or exc.__class__.__name__
            error_text = f"{message}\n\nInstaller log:\n{current_log_text()}\n\nTraceback:\n{traceback.format_exc()}"
            log_path = write_failure_log(error_text)
            if log_path:
                error_text = f"{error_text}\n\nSaved log file:\n{log_path}"
            set_status("Update failed. Review the error, then try again.")
            set_progress(0)
            append_log(f"UPDATE ERROR: {message}")
            root.after(
                0,
                lambda: show_error_dialog(
                    "CCBot update failed",
                    "CCBot could not finish the update. Please try again. If it fails again, copy the technical details and contact support.",
                    technical_details=error_text,
                ),
            )
            root.after(0, lambda: set_inputs_state("normal"))
            root.after(0, refresh_install_button)
            root.after(0, lambda: check_update_button.configure(state="normal"))

    def prompt_for_update(update_info):
        notes = f"\n\n{update_info['notes']}" if update_info.get("notes") else ""
        if messagebox.askokcancel(
            "CCBot update available",
            (
                f"CCBot Agent {update_info['display_version']} is available.\n"
                f"Your current version is {display_version(__version__)}.\n\n"
                "Click OK to download and update now."
                f"{notes}"
            ),
            parent=root,
        ):
            threading.Thread(target=lambda: run_update(update_info), daemon=True).start()

    def check_for_updates(show_latest_message=True):
        def worker():
            root.after(0, lambda: check_update_button.configure(state="disabled"))
            try:
                update_info = fetch_latest_update()
            except BaseException as exc:
                message = str(exc) or exc.__class__.__name__
                append_log(f"Update check failed: {message}")
                if show_latest_message:
                    root.after(
                        0,
                        lambda: messagebox.showerror(
                            "CCBot update check failed",
                            f"Could not check for updates.\n\n{message}",
                            parent=root,
                        ),
                    )
            else:
                if update_info:
                    append_log(f"Update available: {update_info['display_version']}")
                    root.after(0, lambda: prompt_for_update(update_info))
                elif show_latest_message:
                    root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "CCBot is up to date",
                            f"You are already using {display_version(__version__)}.",
                            parent=root,
                        ),
                    )
            finally:
                root.after(0, lambda: check_update_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    check_update_button.configure(command=lambda: check_for_updates(show_latest_message=True))

    def finish():
        root.destroy()

    def run_install():
        root.after(0, lambda: set_inputs_state("disabled"))
        root.after(0, lambda: install_button.configure(state="disabled"))
        set_progress(0)
        try:
            install(platform_var.get(), token_var.get(), set_status, set_progress, append_log)
        except BaseException as exc:
            message = str(exc) or exc.__class__.__name__
            error_text = f"{message}\n\nInstaller log:\n{current_log_text()}\n\nTraceback:\n{traceback.format_exc()}"
            log_path = write_failure_log(error_text)
            if log_path:
                error_text = f"{error_text}\n\nSaved log file:\n{log_path}"
            set_progress(0)
            token_error = is_enrollment_token_error(message)

            def recover_after_error():
                if token_error:
                    token_var.set("")
                    set_status("Create a fresh install token in CyberCare AI, paste it here, then try again.")
                    append_log("The install token was not accepted. Create a fresh token in CyberCare AI and try again.")
                    show_error_dialog(
                        "Install token needs to be replaced",
                        (
                            "This install token is no longer valid. It may be expired, already used, or revoked.\n\n"
                            "Go back to the CyberCare AI website, create a new install token, copy it, paste it here, "
                            "and click Try again."
                        ),
                    )
                else:
                    set_status("Installation failed. You can try again or copy the technical details for support.")
                    append_log(f"ERROR: {message}")
                    show_error_dialog(
                        "CCBot installation failed",
                        (
                            "CCBot could not finish installation. Please try again. If it fails again, "
                            "copy the technical details and contact support."
                        ),
                        technical_details=error_text,
                    )
                set_inputs_state("normal")
                check_update_button.configure(state="normal")
                refresh_install_button()
                token_entry.focus_set()

            root.after(0, recover_after_error)
        else:
            root.after(0, lambda: install_button.configure(text="Finish", state="normal", command=finish))

    install_button.configure(command=lambda: threading.Thread(target=run_install, daemon=True).start())
    root.after(900, lambda: check_for_updates(show_latest_message=False))
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="CCBot Windows Installer")
    parser.add_argument("--agent-run", action="store_true")
    parser.add_argument("--apply-update", action="store_true")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args(argv)
    if args.apply_update:
        raise SystemExit(apply_self_update(args.config, parent_pid=args.parent_pid))
    elif args.agent_run:
        run_loop(args.config)
    else:
        launch_gui()


if __name__ == "__main__":
    main()
