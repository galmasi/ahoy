#!/usr/bin/env python3

import curses
import subprocess
import threading
import time
import json
from dataclasses import dataclass
from typing import Optional

# ── colour pair indices ────────────────────────────────────────────────
CP_ON     = 1   # green  — ON
CP_OFF    = 2   # red    — OFF
CP_UNK    = 3   # yellow — unknown / not yet checked
CP_SYNC   = 4   # green  — desired matches actual
CP_NOSYNC = 5   # red    — desired differs from actual


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

fp = open('config.json', 'rb')
d = json.load(fp)
for netname in d['networks'].keys():
    network=d['networks'][netname]
    label = netname
    description = 'Connect to %s'%(netname)
    check_cmd = "test -f /tmp/sshuttle.%s.pid && /usr/bin/nc -z -G 1 -w 1 %s 22"%(netname, network["gateway"])
    on_cmd = d['sshuttlecmd']
    on_cmd += " --daemon --pidfile /tmp/sshuttle.%s.pid "%(netname)
    on_cmd += "-e 'ssh " + d['sshoptions'] + " -i " + d['sshkey'] + "' "
    on_cmd += "-r " + network["jumphost"] + " "
    for cidr in network["nets"]: on_cmd += cidr + " "
    off_cmd = "kill -9 $(cat /tmp/sshuttle.%s.pid)"%(netname)
    item = ToggleItem(label, description, check_cmd, on_cmd, off_cmd)
    ITEMS.append(item)

# ── model ──────────────────────────────────────────────────

def _run(cmd: str) -> int:
    return subprocess.call(
        cmd, shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def model_check_state(item: ToggleItem) -> bool:
    """Return True (ON) if check_cmd exits 0, False otherwise."""
    return _run(item.check_cmd) == 0

def model_update_loop() -> None:
    while True:
        for item in ITEMS:
            item.actual  = model_check_state(item)
            if item.desired is None:
                item.desired = item.actual
            if item.actual != item.desired:
                model_apply_item(item)
        time.sleep(1)
        
def model_apply_item(item: ToggleItem) -> str:
    """Run on_cmd or off_cmd to reach desired state; return a status string."""
    cmd = item.on_cmd if item.desired else item.off_cmd
    rc  = _run(cmd)
    item.actual = model_check_state(item)

# ── layout constants ──────────────────────────────────────────────────

COL_LABEL   =  2
COL_DESIRED = 24
COL_ACTUAL  = 32
COL_SYNC    = 40
TABLE_MIN_W = 50
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


def draw_header(stdscr, cols: int) -> None:
    title = "Ahoy! number, please"
    hint  = ("SPACE/ENTER: toggle desired q: quit")
    try:
        stdscr.addstr(0, max(0, (cols - len(title)) // 2), title,
                      curses.A_BOLD | curses.A_UNDERLINE)
        stdscr.addstr(1, 2, hint[:cols - 4])
    except curses.error:
        pass
    stdscr.refresh()


# ── main ──────────────────────────────────────────────────────────────

def main(stdscr) -> None:

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

    table_win = curses.newwin(table_h, table_w, table_start, 2)
    info_win  = curses.newwin(info_h,  table_w, info_start,  2)
    table_win.keypad(True)
    table_win.timeout(100)   # getch() returns -1 after 100 ms with no key
    POLL_INTERVAL = 2        # seconds between automatic display redraws

    highlight = 0
    log       = "Initializing…"
    draw_header(stdscr, cols)
    draw_table(table_win, highlight, use_colors)
    draw_info(info_win, highlight, log)

    last_poll = time.monotonic()

    draw_table(table_win, highlight, use_colors)
    draw_info(info_win, highlight, log)

    while True:
        ch = table_win.getch()   # returns -1 on timeout

        # ── periodic display auto-refresh ──────────────────────────────────────
        now = time.monotonic()
        if now - last_poll >= POLL_INTERVAL:
            last_poll = now
            log = f"Auto-refreshed  ({time.strftime('%H:%M:%S')})"
            draw_table(table_win, highlight, use_colors)
            draw_info(info_win, highlight, log)
            
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

        #elif ch == ord('a'):
        #    item = ITEMS[highlight]
        #    if item.actual == item.desired:
        #        log = f"'{item.label}' is already in the desired state."
        #    else:
        #        log = f"Applying '{item.label}'…"
        #        draw_info(info_win, highlight, log)
        #        log = apply_item(item)

        #elif ch == ord('A'):
        #    if all(i.actual == i.desired for i in ITEMS):
        #        log = "All items already in sync."
        #    else:
        #        log = "Applying all out-of-sync items…"
        #        draw_info(info_win, highlight, log)
        #        log = apply_all()

        #elif ch == ord('r'):
        #    log = "Refreshing actual states…"
        #    draw_info(info_win, highlight, log)
        #    refresh_all()
        #    log = "Actual states refreshed."

        elif ch in (ord('q'), ord('Q')):
            break

        draw_table(table_win, highlight, use_colors)
        draw_info(info_win, highlight, log)


if __name__ == "__main__":
    curses.wrapper(main)
