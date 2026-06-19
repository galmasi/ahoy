#!/usr/bin/env python3

import curses
import subprocess
import threading
import time
import json
import os
import sys
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from typing import Optional

# ── data model ────────────────────────────────────────────────────────

@dataclass
class ToggleItem:
    label: str
    description: str
    check_cmd: str                 # shell cmd: exit 0 → ON,  non-zero → OFF
    on_cmd: str                    # shell cmd: executed to turn ON
    off_cmd: str                   # shell cmd: executed to turn OFF
    desired: Optional[bool] = None # None = unset (before startup)
    actual: Optional[bool] = None  # None = not yet queried
    message: str = ""              # output from an error

# Edit this list to add your own toggles.
ITEMS: list[ToggleItem] = []

_CONFIG_PATHS = [
    os.path.expanduser("~/.config/ahoy/config.json"),
    os.path.expanduser("~/Library/Application Support/ahoy/config.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
]

_CHECK_SSHOPTS_DEFAULT="-oBatchMode=yes -oPasswordAuthentication=no -oUserKnownHostsFile=/dev/null -oStrictHostKeyChecking=no -oConnectTimeout=1"
_CONNECT_SSHOPTS_DEFAULT="-oUserKnownHostsFile=/dev/null -oStrictHostKeyChecking=no -oBatchMode=yes -oPasswordAuthentication=no -oConnectTimeout=20"
_SSHUTTLECMD_DEFAULT="sshuttle --disable-ipv6 --dns --python python3"

# ###############################
# global configuration read
# ###############################

def _load_config() -> dict:
    for path in _CONFIG_PATHS:
        if os.path.exists(path):
            with open(path, "rb") as fp:
                return json.load(fp)
    print(
        "ahoy: config not found.\n"
        "Copy config.example.json to ~/.config/ahoy/config.json and edit it.",
        file=sys.stderr,
    )
    sys.exit(1)

def _process_config() -> None:
    d = _load_config()
    check_sshopts = _CHECK_SSHOPTS_DEFAULT
    if "checksshopts" in d: check_sshopts = d['checksshopts']
    connect_sshopts  = _CONNECT_SSHOPTS_DEFAULT
    if "connectsshopts" in d: connect_sshopts = d['connectsshopts']
    sshuttlecmd = _SSHUTTLECMD_DEFAULT
    if "sshuttlecmd" in d: sshuttlecmd = d['sshuttlecmd']
    sshkey = None
    if "sshkey" in d: sshkey = d['sshkey']
    defaultuser = os.environ['USER']
    if "user" in d: defaultuser = d['user']

    for netname in d['networks'].keys():
        network=d['networks'][netname]
        label = netname
        user  = defaultuser
        if 'user' in network.keys(): user = network['user']
        
        description = 'Selected: %s: %s'%(netname,str(network['nets']))
        
        check_cmd = "test -f /tmp/sshuttle.%s.pid &&"%(netname)
        check_cmd += "ssh " + check_sshopts + " "
        if sshkey is not None: check_cmd += " -i " + sshkey + " "
        check_cmd += user + "@" + network["gateway"] + " true"
        
        off_cmd = "if test -f /tmp/sshuttle.%s.pid ; "%(netname)
        off_cmd += "then"
        off_cmd += "  kill -9 $(cat /tmp/sshuttle.%s.pid) ; "%(netname)
        off_cmd += "  rm -f /tmp/sshuttle.%s.pid ; "%(netname)
        off_cmd += "fi"
        
        on_cmd = off_cmd + "; "
        on_cmd += sshuttlecmd + " --daemon --pidfile /tmp/sshuttle.%s.pid "%(netname)
        on_cmd += "-e 'ssh " + connect_sshopts
        if sshkey is not None: on_cmd += " -i " + sshkey
        on_cmd += "' -r " + user + "@" + network["jumphost"] + " "
        for cidr in network["nets"]: on_cmd += cidr + " "

        item = ToggleItem(label, description, check_cmd, on_cmd, off_cmd)
        ITEMS.append(item)

# ── model ──────────────────────────────────────────────────

# #####################################
# model_update_loop runs forever and checks/adjusts the actual states.
# for each entry the actual state of the entry (connected or disconnected)
# is verified by running the entry's "check_cmd"
# #####################################

def model_update_loop() -> None:
    while True:
        for item in ITEMS:
            item.actual  = model_check_state(item)
            if item.desired is None:
                item.desired = item.actual
            if item.actual != item.desired:
                model_apply_item(item)
        time.sleep(5)

def model_check_state(item: ToggleItem) -> bool:
    """Return True (ON) if check_cmd exits 0, False otherwise."""
    retval = (_run(item.check_cmd) == 0)
    #_command_log_extend([item.label])
    #_command_log_extend([item.check_cmd])
    return retval

def _run(cmd: str) -> int:
    return subprocess.call(
        cmd, shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

# #####################################
# model_apply_item is called when a change needs to be made.
# #####################################
        
def model_apply_item(item: ToggleItem) -> None:
    """Run on_cmd or off_cmd to reach desired state (apply path is logged)."""
    _run_toggle_apply(item)
    item.actual = model_check_state(item)

def _run_toggle_apply(item: ToggleItem) -> int:
    """Run on_cmd or off_cmd per `item.desired`; capture output into `_command_log` and file."""
    turning_on = bool(item.desired)
    cmd = item.on_cmd if turning_on else item.off_cmd
    phase = "ON" if turning_on else "OFF"
    ts = time.strftime("%H:%M:%S")
    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            input="",
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError as exc:
        _command_log_extend(
            [
                f"[{ts}] {item.label} → {phase}  (failed to run: {exc})",
                f"  $ {cmd.strip()[:MAX_CMD_LOG_CHARS]}",
            ]
        )
        return 127

    rc = completed.returncode
    out = (completed.stdout or "") + (completed.stderr or "")
    header = f"[{ts}] {item.label} → {phase}  exit {rc}"
    entries = [header]
    _command_log_extend(entries)
    return rc


# ###############################
# logging
# ###############################

LOG_MAX_LINES = 400
MAX_CMD_LOG_CHARS = 400
MAX_LOG_LINE_CHARS = 512

COMMAND_LOG_PATH = os.path.join(
    os.path.expanduser("~/.local/state/ahoy"),
    "command.log",
)

_command_log: deque[str] = deque(maxlen=LOG_MAX_LINES)
_command_log_lock = threading.Lock()
_command_log_file_warned = False


def command_log_snapshot() -> list[str]:
    with _command_log_lock:
        return list(_command_log)

def _persist_command_log_lines(lines: list[str]) -> None:
    """Append log lines to disk (same content as the on-screen deque)."""
    global _command_log_file_warned
    if not lines:
        return
    path = COMMAND_LOG_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fp:
            for line in lines:
                fp.write(line + "\n")
            fp.flush()
    except OSError as exc:
        if not _command_log_file_warned:
            print(
                f"ahoy: cannot write command log to {path}: {exc}",
                file=sys.stderr,
            )
            _command_log_file_warned = True

def _command_log_extend(entries: list[str]) -> None:
    with _command_log_lock:
        for line in entries:
            _command_log.append(line)
    _persist_command_log_lines(entries)


# ── colour pair indices ────────────────────────────────────────────────

CP_ON     = 1   # green  — ON
CP_OFF    = 2   # red    — OFF
CP_UNK    = 3   # yellow — unknown / not yet checked
CP_SYNC   = 4   # green  — desired matches actual
CP_NOSYNC = 5   # red    — desired differs from actual

# ── layout constants ──────────────────────────────────────────────────

COL_LABEL   =  2
COL_DESIRED = 24
COL_ACTUAL  = 32
COL_SYNC    = 40
TABLE_MIN_W = 50
LOG_MIN_H   =  5   # minimum height (incl. border) for the command log panel
ROW_ITEMS   =  2   # first data row inside the table window

# ── drawing ───────────────────────────────────────────────────────────

def _badge(state: Optional[bool]) -> str:
    if state is None:
        return "[ ?? ]"
    return "[ ON ]" if state else "[OFF ]"


def _badge_attr(state: Optional[bool], base: int, use_colors: bool) -> int:
    if not use_colors:
        return base | curses.A_BOLD
    cp = CP_UNK if state is None else (CP_ON if state else CP_OFF)
    return base | curses.color_pair(cp) | curses.A_BOLD


def draw_item(win, row: int, item: ToggleItem,
              highlight: bool, use_colors: bool) -> None:
    _, w = win.getmaxyx()
    base = curses.A_REVERSE if highlight else curses.A_NORMAL
    try:
        # Flood-fill the row so the highlight bar is solid.
        win.addstr(row, 1, " " * (w - 2), base)

        win.addstr(row, COL_LABEL,   f"{item.label:<20}", base)
        win.addstr(row, COL_DESIRED, _badge(item.desired),
                   _badge_attr(item.desired, base, use_colors))
        win.addstr(row, COL_ACTUAL,  _badge(item.actual),
                   _badge_attr(item.actual,  base, use_colors))

        if item.actual is None or item.desired is None:
            sync_s = " ?  "
            sync_a = _badge_attr(None, base, use_colors)
        elif item.desired == item.actual:
            sync_s = " ✓  "
            sync_a = base | (curses.color_pair(CP_SYNC)   | curses.A_BOLD
                             if use_colors else curses.A_NORMAL)
        else:
            sync_s = " ✗  "
            sync_a = base | (curses.color_pair(CP_NOSYNC) | curses.A_BOLD
                             if use_colors else curses.A_BOLD)

        win.addstr(row, COL_SYNC, sync_s, sync_a)
    except curses.error:
        pass


def draw_table(win, highlight: int, use_colors: bool) -> None:
    win.erase()
    win.box()
    win.addstr(0, 3, " Toggle Menu ", curses.A_BOLD)
    try:
        win.addstr(1, COL_LABEL,   "Label",   curses.A_UNDERLINE)
        win.addstr(1, COL_DESIRED, "Desired", curses.A_UNDERLINE)
        win.addstr(1, COL_ACTUAL,  "Actual",  curses.A_UNDERLINE)
        win.addstr(1, COL_SYNC,    "Sync",    curses.A_UNDERLINE)
    except curses.error:
        pass
    for i, item in enumerate(ITEMS):
        draw_item(win, i + ROW_ITEMS, item, i == highlight, use_colors)
    win.refresh()


def draw_info(win, highlight: int, log: str) -> None:
    _, w = win.getmaxyx()
    win.erase()
    win.box()
    win.addstr(0, 3, " Info ", curses.A_BOLD)
    try:
        win.addstr(1, 2, ITEMS[highlight].description[:w - 4])
        win.addstr(2, 2, log[:w - 4], curses.A_DIM)
    except curses.error:
        pass
    win.refresh()


def draw_log(win, lines: list[str]) -> None:
    """Bordered panel for captured command output (body filled by `lines`)."""
    h, w = win.getmaxyx()
    win.erase()
    win.box()
    win.addstr(0, 3, " Command log ", curses.A_BOLD)
    body_rows = max(0, h - 2)
    if body_rows == 0:
        win.refresh()
        return
    display = lines if lines else ["(no output yet)"]
    try:
        for i in range(min(len(display), body_rows)):
            win.addstr(1 + i, 2, display[i][: max(0, w - 4)], curses.A_DIM)
    except curses.error:
        pass
    win.refresh()


def draw_header(stdscr, cols: int) -> None:
    title = "Ahoy! number, please"
    hint  = ("UP/DOWN to select; SPACE/ENTER to toggle; q to quit")
    try:
        stdscr.addstr(0, max(0, (cols - len(title)) // 2), title,
                      curses.A_BOLD | curses.A_UNDERLINE)
        stdscr.addstr(1, 2, hint[:cols - 4])
    except curses.error:
        pass
    stdscr.refresh()


# ── main ──────────────────────────────────────────────────────────────

def main(stdscr) -> None:

    _process_config()
    
    # start the status updater
    thread = threading.Thread(target=model_update_loop, args=(), daemon=True)
    thread.start()

    # draw the window
    curses.curs_set(0)
    stdscr.clear()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)

    use_colors = curses.has_colors()
    if use_colors:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(CP_ON,     curses.COLOR_GREEN,  -1)
        curses.init_pair(CP_OFF,    curses.COLOR_RED,    -1)
        curses.init_pair(CP_UNK,    curses.COLOR_YELLOW, -1)
        curses.init_pair(CP_SYNC,   curses.COLOR_GREEN,  -1)
        curses.init_pair(CP_NOSYNC, curses.COLOR_RED,    -1)

    rows, cols = stdscr.getmaxyx()

    table_h      = len(ITEMS) + ROW_ITEMS + 1
    table_w      = min(max(TABLE_MIN_W, cols - 4), cols - 2)
    info_h       = 4
    table_start  = 2
    info_start   = table_start + table_h + 1
    log_y        = info_start + info_h + 1
    avail        = rows - log_y
    log_h        = min(max(LOG_MIN_H, avail - 1), avail) if avail > 0 else 0
    if log_h > 0 and log_y + log_h > rows:
        log_h = rows - log_y

    table_win = curses.newwin(table_h, table_w, table_start, 2)
    info_win  = curses.newwin(info_h,  table_w, info_start,  2)
    log_win   = (
        curses.newwin(log_h, table_w, log_y, 2) if log_h >= 3 else None
    )
    table_win.keypad(True)
    table_win.timeout(100)   # getch() returns -1 after 100 ms with no key
    POLL_INTERVAL = 2        # seconds between automatic display redraws

    highlight = 0
    log       = "Initializing…"
    draw_header(stdscr, cols)
    draw_table(table_win, highlight, use_colors)
    draw_info(info_win, highlight, log)
    if log_win is not None:
        draw_log(log_win, command_log_snapshot())

    last_poll = time.monotonic()

    draw_table(table_win, highlight, use_colors)
    draw_info(info_win, highlight, log)
    if log_win is not None:
        draw_log(log_win, command_log_snapshot())

    while True:
        ch = table_win.getch()   # returns -1 on timeout

        # ── periodic display auto-refresh ──────────────────────────────────────
        now = time.monotonic()
        if now - last_poll >= POLL_INTERVAL:
            last_poll = now
            log = f"Auto-refreshed  ({time.strftime('%H:%M:%S')})"
            draw_table(table_win, highlight, use_colors)
            draw_info(info_win, highlight, log)
            if log_win is not None:
                draw_log(log_win, command_log_snapshot())

        if ch == -1:   # timeout tick — nothing more to do
            continue

        if ch in (curses.KEY_UP, ord('k')):
            highlight = (highlight - 1) % len(ITEMS)

        elif ch in (curses.KEY_DOWN, ord('j')):
            highlight = (highlight + 1) % len(ITEMS)

        elif ch in (ord(' '), 10, 13, curses.KEY_ENTER):
            ITEMS[highlight].desired = not ITEMS[highlight].desired
            state = "ON" if ITEMS[highlight].desired else "OFF"
            log = (f"Desired: '{ITEMS[highlight].label}' → {state}")

        elif ch in (ord('q'), ord('Q')):
            break

        draw_table(table_win, highlight, use_colors)
        draw_info(info_win, highlight, log)
        if log_win is not None:
            draw_log(log_win, command_log_snapshot())


if __name__ == "__main__":
    curses.wrapper(main)
