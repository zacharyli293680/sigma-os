#!/usr/bin/env python3
"""
remote.py — keeping the interface reachable from Zach's other devices.

Three things have to hold at once for `https://<node>.<tailnet>.ts.net` to
work, and each fails silently on its own:

  1. `sigma ui` is running on this machine. The logon task below starts it
     hidden at every sign-in, the same way the 06:00 review and the 09:00
     fleet are scheduled — a site that is up only when someone remembered to
     start it is a site that is down when you are on your phone.
  2. `tailscale serve` is proxying port 8787. Tailscale persists that itself
     (`--bg`), and this module only reads it back.
  3. `privacy.config.json` names the one `remote_login` the backend admits
     (`interface/backend/access.py`). Without it every proxied request is
     refused — correct, and also exactly the kind of quiet all-403 that a
     watchdog exists to surface.

`check(out)` is the doctor's view of all three. It stays quiet when Tailscale
is not installed at all: a machine with no proxy has no remote surface and
nothing to say about one.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "interface" / "backend"
TASK_NAME = "SigmaOS-Interface"
PORT = 8787
UI_LOG = HERE / "ui.log"
TAILSCALE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"


def venv_python() -> Path:
    return BACKEND / ".venv" / "Scripts" / "python.exe"


# --------------------------------------------------------------------------
# 1. the logon task
# --------------------------------------------------------------------------

# Start-Process with a hidden window is what keeps a console python.exe off the
# taskbar; the task itself runs interactively (AtLogOn, the signed-in user) so
# the process inherits the same profile — and the same Claude Code login — that
# `sigma ui` in a terminal would. Output goes to runtime/ui.log, overwritten per
# logon, because a hidden process with no log is a process that cannot explain
# why the site is down.
SCHEDULE_PS = (
    "$a = New-ScheduledTaskAction -Execute 'powershell.exe' "
    "-Argument '-NoProfile -WindowStyle Hidden -Command \"Start-Process "
    "-FilePath ''{py}'' -ArgumentList ''-m uvicorn app:app --host 127.0.0.1 "
    "--port {port}'' -WorkingDirectory ''{cwd}'' -WindowStyle Hidden "
    "-RedirectStandardError ''{log}''\"'; "
    "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
    "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
    "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0) "
    "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); "
    "Register-ScheduledTask -TaskName '{task}' -Action $a -Trigger $t -Settings $s "
    "-Description 'Sigma: the interface on 127.0.0.1:{port}, for tailscale serve' -Force"
)


def schedule_cmd(port: int = PORT) -> str:
    return SCHEDULE_PS.format(py=venv_python(), port=port, cwd=BACKEND,
                              log=UI_LOG, task=TASK_NAME)


def install_schedule(port: int = PORT) -> int:
    if not venv_python().exists():
        print("sigma: the interface venv is missing - nothing to schedule.\n"
              "       cd interface/backend && python -m venv .venv && "
              ".venv/Scripts/pip install -r requirements.txt", file=sys.stderr)
        return 2
    r = subprocess.run(["powershell", "-NoProfile", "-Command", schedule_cmd(port)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        print(f"installed '{TASK_NAME}' - at logon, hidden, port {port}")
        print(f"  log: {UI_LOG}")
        print(f"  start it now without signing out: schtasks /run /tn {TASK_NAME}")
    else:
        print(f"could not install: {(r.stderr or r.stdout).strip()}")
    return r.returncode


def task_installed() -> bool:
    try:
        return subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                              capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------
# 2. the proxy
# --------------------------------------------------------------------------

def serve_status() -> str | None:
    """`tailscale serve status` verbatim; None when Tailscale is not here."""
    if not TAILSCALE.exists():
        return None
    try:
        r = subprocess.run([str(TAILSCALE), "serve", "status"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def proxied_url(status: str, port: int = PORT) -> str | None:
    """The https URL Serve publishes for `port`, or None if it is not proxied.

        https://win-2mhekgnh77i.tailffbbc7.ts.net (tailnet only)
        |-- / proxy http://127.0.0.1:8787
    """
    url = None
    for line in (status or "").splitlines():
        s = line.strip()
        if s.startswith("https://"):
            url = s.split()[0]
        elif url and s.startswith("|--") and s.endswith(f"127.0.0.1:{port}"):
            return url
    return None


def funnel_on(status: str) -> bool:
    """Serve marks a public hostname `(Funnel on)`; tailnet-only ones say
    `(tailnet only)`. The public variant is the one this system must never
    run — the whole design leans on the device login being the wall."""
    return "(Funnel on)" in (status or "")


# --------------------------------------------------------------------------
# 3. the login, and the interface itself
# --------------------------------------------------------------------------

def remote_login() -> str:
    try:
        cfg = json.loads((HERE / "privacy.config.json").read_text(encoding="utf-8"))
        return str(cfg.get("remote_login", "")).strip()
    except Exception:
        return ""


def interface_up(port: int = PORT) -> bool:
    """Does anything answer on the port? `/` is the static index, cheap and
    never a model call — never `/api/health`, which runs the doctor that is
    asking."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def listening_pid(port: int = PORT) -> int | None:
    """The pid bound to 127.0.0.1:<port>, from netstat; None if nothing is."""
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                           text=True, timeout=20)
    except Exception:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                pass
    return None


def wait_up(port: int = PORT, seconds: float = 30.0) -> bool:
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if interface_up(port):
            return True
        time.sleep(0.5)
    return False


def restart(port: int = PORT) -> bool:
    """Stop whatever holds the port, start the interface through its logon
    task, and wait for it to answer. The task rather than a direct spawn, so
    a restart and a reboot start the same process the same way. True if the
    port answers within 30s."""
    pid = listening_pid(port)
    if pid:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20)
        import time
        for _ in range(40):                       # up to 20s for the socket to free
            if listening_pid(port) is None:
                break
            time.sleep(0.5)
    if not task_installed():
        print(f"sigma: '{TASK_NAME}' is not installed - sigma ui --install-schedule",
              file=sys.stderr)
        return False
    r = subprocess.run(["schtasks", "/run", "/tn", TASK_NAME], capture_output=True,
                       text=True, timeout=20)
    if r.returncode != 0:
        print(f"sigma: could not start '{TASK_NAME}': {(r.stderr or r.stdout).strip()}",
              file=sys.stderr)
        return False
    return wait_up(port)


def check(out):
    """The doctor's findings. Levels match doctor.py's: (level, what, fix)."""
    OK, TODO, ALERT, INFO = "ok", "todo", "alert", "info"
    status = serve_status()
    if status is None:
        return                                   # no Tailscale, no remote surface
    url = proxied_url(status)
    if not url:
        out.append((OK, "tailnet proxy off - the interface is local only", None))
        return
    if funnel_on(status):
        out.append((ALERT, f"tailscale funnel is ON for {url} - the interface is "
                           "reachable from the public internet",
                    f'"{TAILSCALE}" funnel --https=443 off'))
    if not remote_login():
        out.append((ALERT, f"tailnet proxy is up at {url} but no remote_login is "
                           "configured - every remote request is refused",
                    'add "remote_login": "<your tailscale login>" to '
                    'runtime/privacy.config.json, then restart sigma ui'))
    else:
        out.append((INFO, f"remote access: {url} admits {remote_login()} "
                          "(tailnet only)", None))
    if not task_installed():
        out.append((TODO, f"the interface is proxied but '{TASK_NAME}' is not "
                          "installed - the site is down after a reboot until "
                          "sigma ui is run by hand",
                    "sigma ui --install-schedule"))
    if not interface_up():
        out.append((TODO, f"nothing is answering on 127.0.0.1:{PORT} - the "
                          f"tailnet URL is up but empty",
                    f"sigma ui   (or: schtasks /run /tn {TASK_NAME})"))


if __name__ == "__main__":
    out = []
    check(out)
    for level, what, fix in out:
        print(f"{level:5}  {what}" + (f"\n       -> {fix}" if fix else ""))
