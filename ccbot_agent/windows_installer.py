import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ccbot_agent.main import enroll, run_loop


APP_NAME = "CCBot Agent"
DEFAULT_PLATFORM_URL = "https://cybercareai.io"
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
APP_DIR = PROGRAM_DATA / "CCBotAgent"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
TASK_NAME = "CCBot Agent"

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
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Windows did not return a detailed error."
        raise RuntimeError(f"Could not create the Windows startup task. {detail}")


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

    step(65, "Preparing startup task...")
    executable = current_executable_target()
    create_startup_task(executable)

    step(82, "Starting CCBot in the background...")
    start_agent(executable)
    step(100, "Installation complete. CCBot is running. You can close this window.")


def launch_gui():
    root = tk.Tk()
    root.title(APP_NAME)
    configure_window_identity(root)
    root.geometry("760x760")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Install CCBot for Windows", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Paste the one-time install token from CyberCare AI. The installer will enroll this device and start monitoring.",
        wraplength=460,
    ).pack(anchor="w", pady=(8, 18))

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

    def show_error_dialog(error_text):
        dialog = tk.Toplevel(root)
        dialog.title("CCBot installation failed")
        configure_window_identity(dialog)
        dialog.geometry("660x430")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Installation failed", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text="CCBot could not finish installation. Copy the exact error below before closing this installer.",
            wraplength=600,
        ).pack(anchor="w", pady=(6, 12))

        error_frame = ttk.Frame(body)
        error_frame.pack(fill="both", expand=True)
        error_scrollbar = ttk.Scrollbar(error_frame, orient="vertical")
        error_box = tk.Text(
            error_frame,
            height=12,
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
        error_box.insert("1.0", error_text)
        error_box.pack(side="left", fill="both", expand=True)
        error_scrollbar.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Copy error", command=lambda: copy_text(error_text)).pack(side="left")
        ttk.Button(buttons, text="Exit installer", command=root.destroy).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", root.destroy)
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
            set_status("Installation failed. The installer will exit after you review the error.")
            set_progress(0)
            append_log(f"ERROR: {message}")
            root.after(0, lambda: show_error_dialog(error_text))
        else:
            root.after(0, lambda: install_button.configure(text="Finish", state="normal", command=finish))

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
