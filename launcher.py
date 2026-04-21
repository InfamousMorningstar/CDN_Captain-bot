"""
CDN_Captain Installer / Updater
---------------------------------
Double-click to install OR update CDN_Captain.

First run:
  - Choose install location
  - Enter Discord Bot Token + Anthropic API Key
  - Installer handles Python, all dependencies, Playwright, and launch

Subsequent runs:
  - Detects existing install automatically
  - "Start Bot" to launch, or "Update to Latest" to pull new files from GitHub
  - Credentials are never asked again — already saved to .env
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import os
import threading
import urllib.request
import json

# ── GitHub source ─────────────────────────────────────────────────────────────
GITHUB_USER   = "InfamousMorningstar"
GITHUB_REPO   = "CDN_Captain-bot"
GITHUB_BRANCH = "main"
RAW_BASE      = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
BOT_FILES     = ["bot.py", "watchdog.py", "requirements.txt"]
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_INSTALL_DIR  = os.path.join(os.path.expanduser("~"), "CDN_Captain")
APPDATA_CONFIG_DIR   = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "CDN_Captain")
CONFIG_FILE          = os.path.join(APPDATA_CONFIG_DIR, "config.json")
PYTHON_URL           = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
PYTHON_INSTALLER_TMP = os.path.join(os.path.expanduser("~"), "_cdn_py_install_tmp.exe")

# Windows flag: launch subprocess without a console window
CREATE_NO_WINDOW = 0x08000000

BRAND_COLOR  = "#5865F2"
BG_COLOR     = "#1e1e2e"
TEXT_COLOR   = "#cdd6f4"
GREEN        = "#a6e3a1"
RED          = "#f38ba8"
FONT         = "Segoe UI"


# ── Config helpers ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> None:
    os.makedirs(APPDATA_CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_existing_install() -> str | None:
    """Return the saved install directory if it still has a valid .env, else None."""
    cfg = load_config()
    d = cfg.get("install_dir", "")
    if d and os.path.exists(os.path.join(d, ".env")):
        return d
    return None


# ── Python detection ───────────────────────────────────────────────────────────
def find_python() -> str | None:
    import shutil
    # Skip sys.executable when running from a PyInstaller bundle — it points back
    # to the installer .exe, not a real Python interpreter.
    candidates: list[str] = []
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    candidates += ["python", "python3", "py"]

    # Add hard-coded fallback paths common on Windows (highest versions first)
    user_base = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                             "Programs", "Python")
    for ver in ("313", "312", "311", "310"):
        candidates.append(os.path.join(user_base, f"Python{ver}", "python.exe"))
        candidates.append(os.path.join(f"C:\\Python{ver}", "python.exe"))
        candidates.append(os.path.join("C:\\Program Files", f"Python{ver}", "python.exe"))

    for cmd in candidates:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            out = r.stdout.strip() or r.stderr.strip()   # py2 wrote to stderr
            if r.returncode == 0 and "Python 3." in out:
                ver_parts = out.split()[1].split(".")
                if int(ver_parts[0]) == 3 and int(ver_parts[1]) >= 10:
                    # Always resolve to a full absolute path — bare names like "py"
                    # or "python" can fail in a freshly spawned cmd.exe window due
                    # to Windows App Execution Aliases not being available there.
                    full_path = shutil.which(cmd) if not os.path.isabs(cmd) else cmd
                    return full_path if full_path else cmd
        except Exception:
            continue
    return None


# ── Main UI ────────────────────────────────────────────────────────────────────
class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._install_dir = DEFAULT_INSTALL_DIR
        self.root.title("CDN_Captain Installer")
        self.root.geometry("540x660")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self._center()
        self._build_ui()
        self.root.after(100, self._check_existing)

    def _center(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - 540) // 2
        y = (self.root.winfo_screenheight() - 660) // 2
        self.root.geometry(f"540x660+{x}+{y}")

    def _build_ui(self):
        tk.Label(self.root, text="🤖  CDN_Captain", font=(FONT, 20, "bold"),
                 bg=BG_COLOR, fg=BRAND_COLOR).pack(pady=(22, 2))
        tk.Label(self.root, text="Discord Bot Installer", font=(FONT, 10),
                 bg=BG_COLOR, fg="#6c7086").pack(pady=(0, 14))

        # ── Install form (hidden on update mode) ─────────────────────────────
        self.form = tk.Frame(self.root, bg=BG_COLOR)
        self.form.pack(fill="x", padx=40)

        # Install location
        tk.Label(self.form, text="Install Location",
                 font=(FONT, 10, "bold"), bg=BG_COLOR, fg=TEXT_COLOR).pack(anchor="w")
        tk.Label(self.form, text="Where to install bot files (created automatically)",
                 font=(FONT, 8), bg=BG_COLOR, fg="#6c7086").pack(anchor="w", pady=(0, 4))
        dir_row = tk.Frame(self.form, bg=BG_COLOR)
        dir_row.pack(fill="x", pady=(0, 10))
        self._dir_var = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        tk.Entry(dir_row, textvariable=self._dir_var, font=(FONT, 9),
                 bg="#313244", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                 relief="flat", bd=6).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(dir_row, text="Browse", font=(FONT, 8), bg="#45475a", fg=TEXT_COLOR,
                  relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
                  command=self._browse).pack(side="left", padx=(6, 0))

        # Discord Token
        tk.Label(self.form, text="Discord Bot Token",
                 font=(FONT, 10, "bold"), bg=BG_COLOR, fg=TEXT_COLOR).pack(anchor="w")
        tk.Label(self.form, text="discord.com/developers → Your App → Bot → Reset Token",
                 font=(FONT, 8), bg=BG_COLOR, fg="#6c7086").pack(anchor="w", pady=(0, 4))
        self._token_entry = self._entry(self.form)
        self._show_token_var = tk.BooleanVar(value=False)
        tkw = tk.Checkbutton(self.form, text="Show", variable=self._show_token_var,
                             command=lambda: self._token_entry.config(
                                 show="" if self._show_token_var.get() else "•"),
                             bg=BG_COLOR, fg="#6c7086", selectcolor=BG_COLOR,
                             activebackground=BG_COLOR, font=(FONT, 8))
        tkw.pack(anchor="e", pady=(2, 8))

        # Anthropic API Key
        tk.Label(self.form, text="Anthropic API Key",
                 font=(FONT, 10, "bold"), bg=BG_COLOR, fg=TEXT_COLOR).pack(anchor="w")
        tk.Label(self.form, text="console.anthropic.com → API Keys → Create Key",
                 font=(FONT, 8), bg=BG_COLOR, fg="#6c7086").pack(anchor="w", pady=(0, 4))
        self._api_entry = self._entry(self.form)
        self._show_api_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.form, text="Show", variable=self._show_api_var,
                       command=lambda: self._api_entry.config(
                           show="" if self._show_api_var.get() else "•"),
                       bg=BG_COLOR, fg="#6c7086", selectcolor=BG_COLOR,
                       activebackground=BG_COLOR, font=(FONT, 8)).pack(anchor="e", pady=(2, 0))

        # ── Status + progress ─────────────────────────────────────────────────
        prog_frame = tk.Frame(self.root, bg=BG_COLOR)
        prog_frame.pack(fill="x", padx=40, pady=(12, 0))
        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(prog_frame, textvariable=self._status_var, font=(FONT, 9),
                 bg=BG_COLOR, fg="#6c7086", wraplength=460, justify="left").pack(anchor="w")
        self._progress = ttk.Progressbar(prog_frame, mode="indeterminate", length=460)
        self._progress.pack(fill="x", pady=(4, 0))
        s = ttk.Style(); s.theme_use("clam")
        s.configure("TProgressbar", troughcolor="#313244", background=BRAND_COLOR, thickness=5)

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=BG_COLOR)
        log_frame.pack(fill="both", expand=True, padx=40, pady=(10, 0))
        self._log_widget = tk.Text(log_frame, height=4, font=("Consolas", 8),
                                   bg="#181825", fg="#a6adc8", relief="flat",
                                   state="disabled", wrap="word", bd=6)
        self._log_widget.pack(fill="both", expand=True)

        # ── Main button ───────────────────────────────────────────────────────
        self._btn = tk.Button(self.root, text="Install & Start Bot",
                              font=(FONT, 11, "bold"), bg=BRAND_COLOR, fg="white",
                              activebackground="#4752c4", relief="flat", bd=0,
                              padx=20, pady=10, cursor="hand2",
                              command=self._on_install)
        self._btn.pack(pady=14)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _entry(self, parent) -> tk.Entry:
        e = tk.Entry(parent, font=(FONT, 10), show="•",
                     bg="#313244", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                     relief="flat", bd=8)
        e.pack(fill="x", ipady=5)
        return e

    def _browse(self):
        d = filedialog.askdirectory(title="Choose install folder",
                                    initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(d)

    def _log(self, msg: str):
        self._log_widget.config(state="normal")
        self._log_widget.insert("end", msg + "\n")
        self._log_widget.config(state="disabled")
        self._log_widget.see("end")

    def _status(self, msg: str):
        self._status_var.set(msg)
        self.root.update_idletasks()

    # ── State detection ────────────────────────────────────────────────────────
    def _check_existing(self):
        install_dir = get_existing_install()
        if not install_dir:
            return  # Fresh install — show the form as-is

        # ── Update / re-launch mode ───────────────────────────────────────────
        self._install_dir = install_dir
        self.form.pack_forget()  # Hide credentials form
        self._btn.config(text="▶  Start Bot", command=self._start_only)
        self._status(f"Installed at: {install_dir}")
        self._log(f"✅ Installation found: {install_dir}")
        self._log("You can start the bot or update it to the latest version.")

        # "Update to Latest" button
        tk.Button(self.root, text="🔄  Update to Latest Version",
                  font=(FONT, 9, "bold"), bg="#313244", fg=TEXT_COLOR,
                  relief="flat", bd=0, padx=14, pady=8,
                  cursor="hand2", command=self._on_update).pack(pady=(0, 6))

    # ── Install flow ───────────────────────────────────────────────────────────
    def _on_install(self):
        token   = self._token_entry.get().strip()
        api_key = self._api_entry.get().strip()
        install_dir = self._dir_var.get().strip()

        if not token:
            messagebox.showerror("Missing Token",
                "Please enter your Discord Bot Token.\n"
                "Find it at discord.com/developers → Your App → Bot → Reset Token")
            return
        if not api_key:
            messagebox.showerror("Missing API Key",
                "Please enter your Anthropic API Key.\n"
                "Get one at console.anthropic.com → API Keys")
            return
        if not api_key.startswith("sk-"):
            if not messagebox.askyesno("Check API Key",
                    "Your Anthropic API key doesn't look right "
                    "(should start with 'sk-'). Continue anyway?"):
                return
        if not install_dir:
            messagebox.showerror("Missing Location", "Please choose an install folder.")
            return

        self._install_dir = install_dir
        self._btn.config(state="disabled")
        self._progress.start(10)
        threading.Thread(
            target=self._install_thread, args=(token, api_key, install_dir), daemon=True
        ).start()

    def _install_thread(self, token: str, api_key: str, install_dir: str):
        try:
            python = self._ensure_python()
            if not python:
                return
            self._download_files(install_dir)
            self._write_env(install_dir, token, api_key)
            self._pip_install(python, install_dir)
            self._playwright_install(python)
            save_config({"install_dir": install_dir})
            self._launch(python, install_dir)
            self._done_ok()
        except Exception as exc:
            self._log(f"❌ {exc}")
            self._done_err(str(exc))

    # ── Update flow ────────────────────────────────────────────────────────────
    def _on_update(self):
        self._btn.config(state="disabled")
        self._progress.start(10)
        threading.Thread(target=self._update_thread, daemon=True).start()

    def _update_thread(self):
        try:
            install_dir = self._install_dir
            self._log("🔄 Pulling latest files from GitHub...")
            self._download_files(install_dir)          # never touches .env
            python = find_python()
            if python:
                self._pip_install(python, install_dir) # pick up any new deps
            self._log("✅ Update complete — restarting bot...")
            if python:
                self._launch(python, install_dir)
            self._done_ok()
        except Exception as exc:
            self._log(f"❌ Update failed: {exc}")
            self._done_err(str(exc))
        finally:
            self.root.after(0, self._progress.stop)

    # ── Start only (already installed) ────────────────────────────────────────
    def _start_only(self):
        python = find_python()
        if not python:
            messagebox.showerror("Python Not Found",
                "Python 3.10+ is required. Install it from python.org")
            return
        self._launch(python, self._install_dir)
        self._done_ok()

    # ── Steps ──────────────────────────────────────────────────────────────────
    def _ensure_python(self) -> str | None:
        self._status("Checking for Python 3.10+...")
        self._log("🔍 Looking for Python...")
        python = find_python()
        if python:
            self._log(f"✅ Found: {python}")
            return python

        self._log("⚠️  Python not found — downloading Python 3.12 (~25 MB, one-time)...")
        self._status("Downloading Python 3.12...")
        try:
            def _prog(count, block, total):
                if total > 0:
                    self._status(f"Downloading Python 3.12... {min(int(count*block*100/total),100)}%")
            urllib.request.urlretrieve(PYTHON_URL, PYTHON_INSTALLER_TMP, _prog)
        except Exception as exc:
            self._done_err(f"Could not download Python: {exc}")
            return None

        self._status("Installing Python 3.12 silently...")
        self._log("⚙️  Installing Python 3.12...")
        result = subprocess.run(
            [PYTHON_INSTALLER_TMP, "/quiet",
             "InstallAllUsers=0", "PrependPath=1",
             "Include_test=0", "Include_launcher=1"],
            capture_output=True, text=True,
        )
        try:
            os.remove(PYTHON_INSTALLER_TMP)
        except Exception:
            pass

        if result.returncode != 0:
            self._done_err("Python installation failed. Please install from python.org")
            return None

        self._log("✅ Python 3.12 installed")
        python = find_python()
        if not python:
            # Fallback: look in the standard per-user install location
            fallback = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                                    "Programs", "Python", "Python312", "python.exe")
            if os.path.exists(fallback):
                python = fallback

        if not python:
            self._done_err(
                "Python installed but not detected in PATH.\n"
                "Please restart your PC, then run this installer again."
            )
            return None
        return python

    def _download_files(self, install_dir: str):
        self._status("Downloading bot files from GitHub...")
        os.makedirs(install_dir, exist_ok=True)
        for fname in BOT_FILES:
            self._log(f"⬇  {fname}")
            url  = f"{RAW_BASE}/{fname}"
            dest = os.path.join(install_dir, fname)
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "CDN-Captain-Installer/2.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                with open(dest, "wb") as f:
                    f.write(data)
            except Exception as exc:
                raise RuntimeError(f"Download failed for {fname}: {exc}")
        self._log("✅ Bot files ready")

    def _write_env(self, install_dir: str, token: str, api_key: str):
        """Write credentials to .env — only called on first install, never on update."""
        self._status("Saving credentials...")
        with open(os.path.join(install_dir, ".env"), "w") as f:
            f.write(f"DISCORD_TOKEN={token}\n")
            f.write(f"ANTHROPIC_API_KEY={api_key}\n")
        self._log("✅ Credentials saved to .env")

    def _pip_install(self, python: str, install_dir: str):
        self._status("Installing Python packages...")
        self._log("📦 Running pip install...")
        req = os.path.join(install_dir, "requirements.txt")
        r = subprocess.run(
            [python, "-m", "pip", "install", "-r", req, "--quiet"],
            capture_output=True, text=True, cwd=install_dir,
        )
        if r.returncode != 0:
            self._log(f"⚠️  pip warning: {r.stderr[:300]}")
        else:
            self._log("✅ Packages installed")

    def _playwright_install(self, python: str):
        self._status("Installing Playwright browser (one-time, ~150 MB)...")
        self._log("🎭 Downloading Chromium browser...")
        r = subprocess.run(
            [python, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self._log(f"⚠️  Playwright: {r.stderr[:300]}")
        else:
            self._log("✅ Chromium ready")

    def _kill_existing(self, install_dir: str) -> None:
        """Kill any running CDN_Captain instance — by stored cmd PID, then by watchdog PID."""
        # 1. Kill the cmd.exe console window by the PID we saved on last launch.
        #    This is the most reliable method — window-title matching does not work
        #    on Windows because taskkill sees all cmd titles as N/A.
        launcher_pid_file = os.path.join(install_dir, "launcher.pid")
        if os.path.exists(launcher_pid_file):
            try:
                with open(launcher_pid_file, "r") as f:
                    pid = int(f.read().strip())
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                )
                self._log(f"⏹  Closed existing window (PID {pid})")
            except Exception:
                pass
            try:
                os.remove(launcher_pid_file)
            except OSError:
                pass

        # 2. Also kill via watchdog.pid (Python process) as a fallback
        pid_file = os.path.join(install_dir, "watchdog.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                )
                self._log(f"⏹  Stopped existing bot (PID {pid})")
            except Exception:
                pass
            try:
                os.remove(pid_file)
            except OSError:
                pass

        # 3. Wmic fallback — catches any orphaned python processes from this install dir
        subprocess.run(
            ["wmic", "process", "where",
             f'CommandLine like "%{install_dir}%watchdog.py%"',
             "call", "terminate"],
            capture_output=True,
        )
        import time; time.sleep(1)

    def _launch(self, python: str, install_dir: str):
        self._status("Launching bot...")
        self._kill_existing(install_dir)
        watchdog = os.path.join(install_dir, "watchdog.py")
        # Launch cmd.exe directly (not via shell=True) so we get the real PID of the
        # console window — saved to launcher.pid for cleanup on next launch
        proc = subprocess.Popen(
            ["cmd", "/k", f'title CDN_Captain && "{python}" "{watchdog}"'],
            cwd=install_dir,
            creationflags=0x00000010,  # CREATE_NEW_CONSOLE
        )
        try:
            launcher_pid_path = os.path.join(install_dir, "launcher.pid")
            with open(launcher_pid_path, "w") as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        self._log("🚀 CDN_Captain is running!")

    # ── Completion ─────────────────────────────────────────────────────────────
    def _done_ok(self):
        def _apply():
            self._progress.stop()
            self._btn.config(state="normal", text="✅  Running",
                             bg=GREEN, fg="#1e1e2e", command=lambda: None)
            self._status("Bot is running — closing in 3 seconds...")
            self.root.after(3000, self.root.destroy)
        self.root.after(0, _apply)

    def _done_err(self, msg: str):
        def _apply():
            self._progress.stop()
            self._status(f"❌ {msg}")
            self._btn.config(state="normal")
            messagebox.showerror("Install Failed", msg)
        self.root.after(0, _apply)


if __name__ == "__main__":
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()

