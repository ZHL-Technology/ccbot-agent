import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ccbot_agent.main import enroll, run_loop


APP_NAME = "CCBot Agent"
DEFAULT_PLATFORM_URL = "https://cybercareai.io"
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
APP_DIR = PROGRAM_DATA / "CCBotAgent"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
TASK_NAME = "CCBot Agent"


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


def current_executable_target():
    if getattr(sys, "frozen", False):
        target = APP_DIR / "CCBot-Windows-Installer.exe"
        if Path(sys.executable).resolve() != target.resolve():
            shutil.copy2(sys.executable, target)
        return target
    return Path(sys.executable)


def create_startup_task(executable):
    command = f'"{executable}" --agent-run --config "{CONFIG_PATH}"'
    subprocess.run(
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


def start_agent(executable):
    subprocess.Popen(
        [str(executable), "--agent-run", "--config", str(CONFIG_PATH)],
        cwd=str(APP_DIR),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def install(platform_url, enrollment_token, status_callback):
    if not enrollment_token.strip():
        raise ValueError("Paste the one-time install token from CyberCare AI.")
    status_callback("Writing local configuration...")
    write_config(platform_url, enrollment_token)
    status_callback("Enrolling this Windows device...")
    enroll(str(CONFIG_PATH))
    status_callback("Preparing startup task...")
    executable = current_executable_target()
    create_startup_task(executable)
    status_callback("Starting CCBot...")
    start_agent(executable)
    status_callback("CCBot is running. Check the dashboard after the first heartbeat.")


def launch_gui():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("520x360")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Install CCBot for Windows", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Paste the one-time install token from CyberCare AI. The installer will enroll this device and start monitoring.",
        wraplength=460,
    ).pack(anchor="w", pady=(8, 18))

    ttk.Label(frame, text="Platform URL").pack(anchor="w")
    platform_var = tk.StringVar(value=DEFAULT_PLATFORM_URL)
    ttk.Entry(frame, textvariable=platform_var).pack(fill="x", pady=(4, 14))

    ttk.Label(frame, text="Install token").pack(anchor="w")
    token_var = tk.StringVar()
    ttk.Entry(frame, textvariable=token_var, show="*").pack(fill="x", pady=(4, 14))

    status_var = tk.StringVar(value="Ready")
    ttk.Label(frame, textvariable=status_var, wraplength=460).pack(anchor="w", pady=(0, 14))

    install_button = ttk.Button(frame, text="Install and start CCBot")
    install_button.pack(anchor="w")

    def set_status(message):
        root.after(0, lambda: status_var.set(message))

    def run_install():
        install_button.configure(state="disabled")
        try:
            install(platform_var.get(), token_var.get(), set_status)
        except Exception as exc:
            set_status("Installation failed.")
            root.after(0, lambda: messagebox.showerror(APP_NAME, str(exc)))
        else:
            root.after(0, lambda: messagebox.showinfo(APP_NAME, "CCBot was installed and started."))
        finally:
            root.after(0, lambda: install_button.configure(state="normal"))

    install_button.configure(command=lambda: threading.Thread(target=run_install, daemon=True).start())
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="CCBot Windows Installer")
    parser.add_argument("--agent-run", action="store_true")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args(argv)
    if args.agent_run:
        run_loop(args.config)
    else:
        launch_gui()


if __name__ == "__main__":
    main()
