#!/usr/bin/env python3
"""Vortex HAGS Selector - Hardware-Accelerated GPU Scheduling, decided per game.

Vortex Optimizer turns HAGS on or off from the game you tell it you are about to
play. This tool does the same thing standing up: it watches which game is in
front, applies the same rule, and shows you the reason every time.

The rule is not reimplemented here. It is hags_policy.py, the same file the
Optimizer and the Presentation Governor call, so all three cannot disagree.

USAGE
    Vortex_HAGS_Selector.exe                  the window
    Vortex_HAGS_Selector.exe --watch          start with the watcher already on
    Vortex_HAGS_Selector.exe --report         write hags_report.txt beside the exe
    Vortex_HAGS_Selector.exe --selftest       headless checks, exit 0/1
    Vortex_HAGS_Selector.exe --smoke          build the window, exercise it, tear it down

RUN FROM SOURCE
    python3 vortex_hags_selector.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext

import game_processes as gp
import hags_host as host
import hags_policy as P

APP_NAME = "Vortex HAGS Selector"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------- theme
# same palette as the rest of the suite
C_BG = "#0b0e14"
C_PANEL = "#121722"
C_CARD = "#161c2b"
C_BORDER = "#212b3d"
C_CYAN = "#00e5ff"
C_TEXT = "#e2e8f0"
C_MUTED = "#8290a6"
C_GREEN = "#10b981"
C_RED = "#f43f5e"
C_AMBER = "#f59e0b"
C_CONSOLE = "#06090e"

WATCH_INTERVAL_MS = 2000


# --------------------------------------------------------------------- report

def build_report() -> str:
    """The full verdict as text, for --report and for the COPY button."""
    gpu = host.gpu_name_from_registry()
    vram = P.detect_vram_mb()
    mode, on, why = P.hags_mode_for("", vram) if not gpu else P.hags_mode_for(gpu, vram)
    cur = host.read_hags()
    L = []
    L.append(APP_NAME + " " + APP_VERSION)
    L.append("=" * 60)
    L.append("GPU           : " + (gpu or "(not reported)"))
    L.append("VRAM          : " + (str(vram) + " MB" if vram else "(not reported)"))
    L.append("HwSchMode now : " + host.hags_state_word(cur))
    L.append("Verdict       : " + ("HAGS ON (mode 2)" if on else "HAGS OFF (mode 1)"))
    L.append("Reason        : " + why)
    L.append("Administrator : " + ("yes" if host.is_admin() else "no - writing will be refused"))
    L.append("")
    L.append("Catalogue: " + str(len(P.GAMES) - 1) + " titles, "
             + str(gp.TOTAL_MAPPED) + " with a known executable")
    L.append("")
    L.append("Baseline (no specific title)")
    L.append("-" * 60)
    L.append("  HAGS " + ("ON " if on else "off") + "  "
             + P.GAMES["none"][0].ljust(36)[:36] + " " + why)
    for cat, label in P.GAME_CATEGORIES:
        L.append("")
        L.append(label)
        L.append("-" * 60)
        for key, name, need in P.games_in(cat):
            m, o, _ = P.hags_mode_for_game(gpu, vram, key)
            mark = "ON " if o else "off"
            short = "needs " + str(need) + " MB" if vram and vram < need else "fits"
            L.append("  HAGS " + mark + "  " + name.ljust(36)[:36] + " " + short)
    L.append("")
    return "\n".join(L)


# ------------------------------------------------------------------ selftest

def selftest() -> int:
    """Headless checks. Touches no registry value - this must stay safe to run."""
    passed = failed = 0

    def check(name, cond, extra=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print("  PASS  " + name)
        else:
            failed += 1
            print("  FAIL  " + name + ("   -> " + str(extra) if extra else ""))

    print("")
    print("  ==== VORTEX HAGS SELECTOR :: SELFTEST ====")
    print("")

    # the shared rule is what must be in play, not a copy of it
    check("the shared policy module is the one being used",
          hasattr(P, "hags_mode_for_game") and hasattr(P, "GAMES"),
          getattr(P, "__file__", "?"))
    check("catalogue has real titles", len(P.GAMES) > 20, len(P.GAMES))

    # the map must only name games that exist
    keys = set(P.GAMES)
    bad = [k for k in gp.GAME_PROCESSES if k not in keys]
    check("every mapped executable points at a real catalogue key", not bad, bad)

    # reverse map, including the tie rule
    rm = gp.reverse_map()
    check("reverse map is populated", len(rm) > 20, len(rm))
    check("a shared executable resolves to the larger requirement",
          rm.get("cyberpunk2077.exe") == "cyberpunk_rt", rm.get("cyberpunk2077.exe"))
    check("looking up a game by its executable works",
          gp.game_for_process("cs2.exe") == "cs2")
    check("a launcher is not mistaken for a game",
          gp.game_for_process("steam.exe") is None)
    check("an unknown executable is not guessed at",
          gp.game_for_process("notagame.exe") is None)

    # a title with no reliable executable must not be in the map
    check("no guessed executable names for titles we do not know",
          all(k not in gp.GAME_PROCESSES for k in gp.UNMAPPED),
          [k for k in gp.UNMAPPED if k in gp.GAME_PROCESSES])
    check("the unmapped list only names real catalogue keys",
          all(k in keys for k in gp.UNMAPPED), gp.UNMAPPED)

    # the decision path, with a fake card so the result does not depend on this PC
    m, on, why = P.hags_mode_for_game("NVIDIA GeForce GTX 1650", 4096, "cyberpunk")
    check("a 4 GB card is refused HAGS for a 6 GB title", m == P.HAGS_OFF and not on, why)
    m, on, why = P.hags_mode_for_game("NVIDIA GeForce GTX 1650", 4096, "valorant")
    check("the same card gets HAGS for a 2 GB title", m == P.HAGS_ON and on is True, why)

    # the host layer must answer without raising, even with no game in front
    try:
        exe, pid = host.foreground_exe()
        check("the foreground probe answers without raising", True, f"{exe} pid={pid}")
    except Exception as e:
        check("the foreground probe answers without raising", False, e)

    try:
        check("the GPU probe answers without raising", True,
              host.gpu_name_from_registry() or "(none reported)")
    except Exception as e:
        check("the GPU probe answers without raising", False, e)

    # the real local verdict, printed for the record but never asserted on -
    # the result depends on the machine, and this test must pass on any of them
    gpu = host.gpu_name_from_registry()
    vram = P.detect_vram_mb()
    m, on, why = P.hags_mode_for("", vram) if not gpu else P.hags_mode_for(gpu, vram)
    print("")
    print("  local: " + (gpu or "(no gpu reported)") + " / "
          + (str(vram) + " MB" if vram else "vram unknown"))
    print("  local: HwSchMode now = " + host.hags_state_word(host.read_hags()))
    print("  local: verdict = " + ("ON" if on else "OFF") + " - " + why)
    print("")
    print("  RESULT  passes=" + str(passed) + "  fails=" + str(failed))
    print("")
    return 1 if failed else 0


# ------------------------------------------------------------------- the app

class HagsApp(tk.Tk):

    def __init__(self, watch_on_start=False):
        super().__init__()
        self.title(APP_NAME + "  " + APP_VERSION)
        self.configure(bg=C_BG)
        self.geometry("980x720")
        self.minsize(880, 640)

        self.gpu = ""
        self.vram = None
        self.selected = "none"
        self.watching = bool(watch_on_start)
        self.active_game = None      # the catalogue key the watcher last applied
        self._last_written = None    # mode we last wrote, to avoid pointless rewrites

        self._load_icon()
        self._build_header()
        self._build_hardware_card()
        self._build_middle()
        self._build_command_deck()
        self._build_console()

        self.refresh_hardware()
        self.rebuild_game_list()
        self.select_game("none")
        if self.watching:
            self._set_watch(True, quiet=True)
        self.after(600, self._watch_tick)

    # ------------------------------------------------------------- chrome

    def _load_icon(self):
        ico = Path(__file__).resolve().parent / "app_icon.ico"
        try:
            if ico.exists():
                self.iconbitmap(default=str(ico))
        except Exception:
            pass

    def _build_header(self):
        head = tk.Frame(self, bg=C_BG)
        head.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(head, text="VORTEX", font=("Segoe UI", 17, "bold"),
                 fg=C_CYAN, bg=C_BG).pack(side=tk.LEFT)
        tk.Label(head, text="  HAGS SELECTOR", font=("Segoe UI", 17),
                 fg=C_TEXT, bg=C_BG).pack(side=tk.LEFT)
        tk.Label(head, text="hardware-accelerated GPU scheduling, decided per game",
                 font=("Consolas", 8), fg=C_MUTED, bg=C_BG).pack(side=tk.LEFT, padx=14)
        self.admin_tag = tk.Label(head, text="CHECKING RIGHTS", font=("Segoe UI", 8, "bold"),
                                  fg="#021016", bg=C_AMBER, padx=7, pady=2)
        self.admin_tag.pack(side=tk.RIGHT)

    def _build_hardware_card(self):
        card = tk.Frame(self, bg=C_PANEL, highlightthickness=1,
                        highlightbackground=C_BORDER, padx=14, pady=10)
        card.pack(fill=tk.X, padx=16, pady=(0, 8))

        left = tk.Frame(card, bg=C_PANEL)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_gpu = tk.Label(left, text="-", font=("Segoe UI", 11, "bold"),
                                fg=C_TEXT, bg=C_PANEL, anchor=tk.W)
        self.lbl_gpu.pack(anchor=tk.W)
        self.lbl_vram = tk.Label(left, text="-", font=("Consolas", 8),
                                 fg=C_MUTED, bg=C_PANEL, anchor=tk.W)
        self.lbl_vram.pack(anchor=tk.W)

        right = tk.Frame(card, bg=C_PANEL)
        right.pack(side=tk.RIGHT)
        self.lbl_verdict = tk.Label(right, text="-", font=("Segoe UI", 13, "bold"),
                                    fg=C_MUTED, bg=C_PANEL, anchor=tk.E)
        self.lbl_verdict.pack(anchor=tk.E)
        self.lbl_current = tk.Label(right, text="-", font=("Consolas", 8),
                                    fg=C_MUTED, bg=C_PANEL, anchor=tk.E)
        self.lbl_current.pack(anchor=tk.E)

    def _build_middle(self):
        mid = tk.Frame(self, bg=C_BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=16)

        # -------- left: the picker
        lp = tk.Frame(mid, bg=C_PANEL, highlightthickness=1,
                      highlightbackground=C_BORDER)
        lp.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        bar = tk.Frame(lp, bg=C_PANEL, padx=10, pady=8)
        bar.pack(fill=tk.X)
        tk.Label(bar, text="TITLE", font=("Segoe UI", 8, "bold"),
                 fg=C_MUTED, bg=C_PANEL).pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.rebuild_game_list())
        ent = tk.Entry(bar, textvariable=self.filter_var, font=("Consolas", 9),
                       bg=C_CONSOLE, fg=C_TEXT, insertbackground=C_CYAN,
                       relief=tk.FLAT, highlightthickness=1,
                       highlightbackground=C_BORDER)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, ipady=3)

        cats = tk.Frame(lp, bg=C_PANEL, padx=10)
        cats.pack(fill=tk.X)
        self.cat_var = tk.StringVar(value="all")
        for key, label in [("all", "All")] + list(P.GAME_CATEGORIES):
            tk.Radiobutton(cats, text=label, value=key, variable=self.cat_var,
                           command=self.rebuild_game_list, font=("Segoe UI", 8),
                           fg=C_TEXT, bg=C_PANEL, selectcolor=C_CONSOLE,
                           activebackground=C_PANEL, activeforeground=C_CYAN,
                           highlightthickness=0, bd=0).pack(side=tk.LEFT, padx=(0, 10))

        wrap = tk.Frame(lp, bg=C_PANEL, padx=10, pady=6)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.lst = tk.Listbox(wrap, bg=C_CONSOLE, fg=C_TEXT, font=("Consolas", 9),
                              selectbackground="#1e273d", selectforeground=C_CYAN,
                              highlightthickness=1, highlightbackground=C_BORDER,
                              relief=tk.FLAT, activestyle="none")
        self.lst.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(wrap, command=self.lst.yview, bg=C_PANEL,
                          troughcolor=C_CONSOLE, relief=tk.FLAT, width=10)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst.config(yscrollcommand=sb.set)
        self.lst.bind("<<ListboxSelect>>", self._on_pick)

        # -------- right: the verdict for the selection
        rp = tk.Frame(mid, bg=C_PANEL, highlightthickness=1,
                      highlightbackground=C_BORDER, width=390)
        rp.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(8, 0))
        rp.pack_propagate(False)

        tk.Label(rp, text="DECISION", font=("Segoe UI", 8, "bold"),
                 fg=C_MUTED, bg=C_PANEL, anchor=tk.W).pack(fill=tk.X, padx=12, pady=(10, 2))
        self.lbl_sel = tk.Label(rp, text="-", font=("Segoe UI", 13, "bold"),
                                fg=C_TEXT, bg=C_PANEL, anchor=tk.W, wraplength=350,
                                justify=tk.LEFT)
        self.lbl_sel.pack(fill=tk.X, padx=12)
        self.lbl_need = tk.Label(rp, text="-", font=("Consolas", 8),
                                 fg=C_MUTED, bg=C_PANEL, anchor=tk.W, wraplength=350,
                                 justify=tk.LEFT)
        self.lbl_need.pack(fill=tk.X, padx=12, pady=(2, 8))

        self.card_decision = tk.Frame(rp, bg=C_CARD, highlightthickness=1,
                                      highlightbackground=C_BORDER, padx=12, pady=10)
        self.card_decision.pack(fill=tk.X, padx=12)
        self.lbl_action = tk.Label(self.card_decision, text="-",
                                   font=("Segoe UI", 12, "bold"), fg=C_MUTED,
                                   bg=C_CARD, anchor=tk.W)
        self.lbl_action.pack(fill=tk.X)
        self.lbl_reason = tk.Label(self.card_decision, text="-", font=("Consolas", 8),
                                   fg=C_MUTED, bg=C_CARD, anchor=tk.W, wraplength=330,
                                   justify=tk.LEFT)
        self.lbl_reason.pack(fill=tk.X, pady=(4, 0))

        tk.Label(rp, text="IN FRONT NOW", font=("Segoe UI", 8, "bold"),
                 fg=C_MUTED, bg=C_PANEL, anchor=tk.W).pack(fill=tk.X, padx=12, pady=(12, 2))
        self.lbl_front = tk.Label(rp, text="-", font=("Consolas", 9),
                                  fg=C_TEXT, bg=C_PANEL, anchor=tk.W, wraplength=350,
                                  justify=tk.LEFT)
        self.lbl_front.pack(fill=tk.X, padx=12)

        self.btn_map = tk.Button(rp, text="ASSIGN THIS PROCESS TO THE SELECTED TITLE",
                                 font=("Segoe UI", 8, "bold"), bg="#1e293b", fg=C_TEXT,
                                 activebackground="#334155", relief=tk.FLAT, cursor="hand2",
                                 padx=8, pady=7, command=self.assign_process,
                                 wraplength=330)
        self.btn_map.pack(fill=tk.X, padx=12, pady=(10, 12))

        # -------- console spans the bottom of the middle
    def _build_command_deck(self):
        deck = tk.Frame(self, bg=C_BG)
        deck.pack(fill=tk.X, padx=16, pady=(10, 6))

        self.btn_apply = tk.Button(deck, text="APPLY FOR THIS TITLE", font=("Segoe UI", 10, "bold"),
                                   bg=C_CYAN, fg="#021016", activebackground="#00b4cc",
                                   relief=tk.FLAT, cursor="hand2", padx=16, pady=9,
                                   command=self.apply_now)
        self.btn_apply.pack(side=tk.LEFT)

        for text, cmd, bg, fg in [
            ("FORCE OFF", self.force_off, "#1e293b", C_TEXT),
            ("RESTORE PREVIOUS", self.restore, "#1e293b", C_TEXT),
            ("EXPORT .REG", self.export_reg, "#1e293b", C_TEXT),
            ("COPY REPORT", self.copy_report, "#1e293b", C_TEXT),
        ]:
            tk.Button(deck, text=text, font=("Segoe UI", 9, "bold"), bg=bg, fg=fg,
                      activebackground="#334155", relief=tk.FLAT, cursor="hand2",
                      padx=12, pady=9, command=cmd).pack(side=tk.LEFT, padx=6)

        self.btn_watch = tk.Button(deck, text="WATCHER: OFF", font=("Segoe UI", 9, "bold"),
                                   bg="#4c0519", fg="#fecdd3", activebackground="#881337",
                                   relief=tk.FLAT, cursor="hand2", padx=14, pady=9,
                                   command=lambda: self._set_watch(not self.watching))
        self.btn_watch.pack(side=tk.RIGHT)

    def _build_console(self):
        wrap = tk.Frame(self, bg=C_BG)
        wrap.pack(fill=tk.BOTH, expand=False, padx=16, pady=(0, 14))
        hdr = tk.Frame(wrap, bg=C_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="CONSOLE", font=("Consolas", 7, "bold"),
                 fg=C_MUTED, bg=C_BG, anchor=tk.W).pack(side=tk.LEFT)
        tk.Button(hdr, text="Clear", font=("Consolas", 7), bg="#1e293b", fg=C_MUTED,
                  activebackground="#334155", relief=tk.FLAT, padx=6, pady=1,
                  command=lambda: self.log_box.delete("1.0", tk.END)).pack(side=tk.RIGHT)
        self.log_box = scrolledtext.ScrolledText(
            wrap, height=9, bg=C_CONSOLE, fg=C_TEXT, font=("Consolas", 8),
            relief=tk.FLAT, highlightthickness=1, highlightbackground=C_BORDER,
            insertbackground=C_CYAN, wrap=tk.WORD)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.tag_config("info", foreground=C_MUTED)
        self.log_box.tag_config("ok", foreground=C_GREEN)
        self.log_box.tag_config("warn", foreground=C_AMBER)
        self.log_box.tag_config("err", foreground=C_RED)
        self.log_box.tag_config("head", foreground=C_CYAN)
        self.log_box.configure(state=tk.DISABLED)

    def log(self, msg, kind="info"):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, time.strftime("[%H:%M:%S] ") + msg + "\n", kind)
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    # ------------------------------------------------------------ hardware

    def refresh_hardware(self):
        self.gpu = host.gpu_name_from_registry()
        self.vram = P.detect_vram_mb()
        self.lbl_gpu.config(text=self.gpu or "(no discrete GPU reported)")
        self.lbl_vram.config(text=("video memory: " + str(self.vram) + " MB (read from the "
                                   "display class registry, not WMI)") if self.vram
                             else "video memory: not reported")
        _, on, why = P.hags_mode_for(self.gpu, self.vram)
        self.lbl_verdict.config(text=("HAGS SUPPORTED" if on else "HAGS NOT FOR THIS CARD"),
                                fg=(C_GREEN if on else C_RED))
        self.lbl_current.config(text="now: " + host.hags_state_word(host.read_hags()))
        if host.is_admin():
            self.admin_tag.config(text="ADMINISTRATOR", bg=C_GREEN)
        else:
            self.admin_tag.config(text="NOT ELEVATED", bg=C_RED)

    # -------------------------------------------------------------- picker

    def rebuild_game_list(self):
        q = self.filter_var.get().strip().lower()
        cat = self.cat_var.get()
        self.lst.delete(0, tk.END)
        self._visible = []
        rows = [("none", P.GAMES["none"][0], P.GAMES["none"][1])]
        for c, _label in P.GAME_CATEGORIES:
            if cat in ("all", c):
                rows += P.games_in(c)
        for key, name, need in rows:
            if q and q not in name.lower() and q not in key:
                continue
            mark = "  "
            if key in gp.GAME_PROCESSES:
                mark = "* "
            self.lst.insert(tk.END, mark + name.ljust(34)[:34] + (f"{need:>6} MB" if need else "       -"))
            self._visible.append(key)
        # keep the selection if it is still visible
        if self.selected in self._visible:
            i = self._visible.index(self.selected)
            self.lst.selection_clear(0, tk.END)
            self.lst.selection_set(i)
            self.lst.see(i)

    def _on_pick(self, _evt=None):
        sel = self.lst.curselection()
        if not sel:
            return
        key = self._visible[sel[0]]
        self.select_game(key)

    def select_game(self, key):
        self.selected = key
        name, need, cat = P.game_choice(key)
        self.lbl_sel.config(text=name)
        self.lbl_need.config(text=("needs about " + str(need) + " MB at 1080p"
                                   if need else "no title-specific requirement")
                             + "   |   category: " + (cat or "n/a"))
        mode, on, why = P.hags_mode_for_game(self.gpu, self.vram, key)
        self.lbl_action.config(text=("HAGS ON  -  mode 2" if on else "HAGS OFF  -  mode 1"),
                               fg=(C_GREEN if on else C_AMBER))
        self.lbl_reason.config(text=why)
        exe, pid = host.foreground_exe()
        if exe:
            known = gp.game_for_process(exe)
            self.lbl_front.config(
                text=exe + (("  ->  " + P.game_choice(known)[0]) if known
                            else "  (not a title we know)"))
        else:
            self.lbl_front.config(text="(none readable)")

    # ------------------------------------------------------------- actions

    def apply_now(self):
        name, _need, _c = P.game_choice(self.selected)
        mode, on, why = P.hags_mode_for_game(self.gpu, self.vram, self.selected)
        self._write(mode, f"{name}: {why}")

    def force_off(self):
        self._write(P.HAGS_OFF, "forced off by hand")

    def _write(self, mode, why):
        ok, msg = host.apply_hags(mode)
        if ok:
            self._last_written = mode
            self.log("HAGS " + ("ENABLED" if mode == P.HAGS_ON else "DISABLED")
                     + " - " + msg, "ok")
            self.log("    reason: " + why, "info")
        else:
            self.log("WRITE FAILED - " + msg, "err")
            messagebox.showerror(APP_NAME, msg)
        self.refresh_hardware()

    def restore(self):
        ok, msg = host.restore_previous()
        self.log(("RESTORE - " if ok else "RESTORE FAILED - ") + msg, "ok" if ok else "err")
        self.refresh_hardware()

    def export_reg(self):
        mode = host.read_hags()
        if mode is None:
            mode = P.HAGS_OFF
        p = host.export_restore_reg(mode, "state at export time")
        self.log("wrote " + p.name + " - double-click it to set HwSchMode back to "
                 + str(mode) + ".", "ok")

    def copy_report(self):
        txt = build_report()
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.log("report copied to the clipboard (" + str(len(txt)) + " chars).", "ok")
        except tk.TclError as e:
            self.log("clipboard refused: " + str(e), "err")

    def assign_process(self):
        exe, _pid = host.foreground_exe()
        if not exe:
            self.log("no foreground process was readable, so there is nothing to assign.", "warn")
            return
        if gp.game_for_process(exe):
            self.log(exe + " is already assigned to "
                     + P.game_choice(gp.game_for_process(exe))[0] + ".", "warn")
            return
        if gp.save_user_mapping(exe, self.selected):
            self.log(exe + " -> " + P.game_choice(self.selected)[0]
                     + "  (saved to games_user.json; this overrides the built-in map).", "ok")
        else:
            self.log("could not save the mapping - the folder may be read-only.", "err")

    # ------------------------------------------------------------- watcher

    def _set_watch(self, on, quiet=False):
        self.watching = bool(on)
        if self.watching:
            self.btn_watch.config(text="WATCHER: ON", bg=C_GREEN, fg="#021016",
                                  activebackground="#0d9668")
            if not quiet:
                self.log("watcher on - every " + str(WATCH_INTERVAL_MS // 1000)
                         + "s the title in front is read and the rule is applied when it "
                           "changes. Leaving a game does not revert it; only entering one "
                           "changes the setting.", "head")
        else:
            self.btn_watch.config(text="WATCHER: OFF", bg="#4c0519", fg="#fecdd3",
                                  activebackground="#881337")
            if not quiet:
                self.log("watcher off - the setting now only changes when you press a button.",
                         "info")

    def _watch_tick(self):
        if self.watching:
            try:
                self._watch_step()
            except Exception as e:
                self.log("watcher error: " + str(e), "err")
        self.after(WATCH_INTERVAL_MS, self._watch_tick)

    def _watch_step(self, exe=None):
        if exe is None:
            exe, _pid = host.foreground_exe()
        if not exe:
            return
        key = gp.game_for_process(exe)
        if key is None:
            self.lbl_front.config(text=exe + "  (not a title we know)")
            return
        name = P.game_choice(key)[0]
        self.lbl_front.config(text=exe + "  ->  " + name)
        if key == self.active_game:
            return
        self.active_game = key
        mode, on, why = P.hags_mode_for_game(self.gpu, self.vram, key)
        if mode == self._last_written and mode == host.read_hags():
            self.log(name + " started - HAGS already " + ("on" if on else "off")
                     + " for this title, nothing written.", "info")
            return
        self.log(name + " started - applying the rule.", "head")
        self._write(mode, why)


def smoke() -> int:
    """Build the whole window, map it, tear it down. No mainloop, no interaction.

    This is the check that catches a bad widget option - a tuple passed to a
    constructor rather than to pack(), for instance - which a headless test of the
    logic alone will never see.
    """
    print("")
    print("  ==== VORTEX HAGS SELECTOR :: SMOKE ====")
    app = None
    try:
        app = HagsApp()
        app.update_idletasks()
        app.update()
        title = app.title()
        n_items = app.lst.size()
        gpu = app.lbl_gpu.cget("text")
        verdict = app.lbl_verdict.cget("text")
        print("  window title : " + title)
        print("  listbox rows : " + str(n_items))
        print("  gpu label    : " + str(gpu))
        print("  verdict label: " + str(verdict))
        ok = n_items >= len(P.GAMES) and bool(title)

        # the picker must actually filter
        app.filter_var.set("valor")
        app.update_idletasks()
        filtered = app.lst.size()
        print("  filter 'valor' -> " + str(filtered) + " row(s)")
        ok = ok and filtered == 1
        app.filter_var.set("")
        app.cat_var.set("esports")
        app.rebuild_game_list()
        app.update_idletasks()
        cat_rows = app.lst.size()
        print("  category esports -> " + str(cat_rows) + " row(s)")
        ok = ok and cat_rows == len(P.games_in("esports")) + 1
        app.cat_var.set("all")
        app.rebuild_game_list()

        # selecting a title must move the verdict panel, and must agree with the rule
        for key in ("valorant", "cyberpunk_rt"):
            app.select_game(key)
            app.update_idletasks()
            want_mode, want_on, _why = P.hags_mode_for_game(app.gpu, app.vram, key)
            shown = app.lbl_action.cget("text")
            agrees = ("ON" in shown) == bool(want_on)
            print("  " + key.ljust(13) + " -> " + shown
                  + "   (rule says mode " + str(want_mode) + ")")
            ok = ok and agrees

        # the watcher's decision path, with the write intercepted
        applied = []
        app._write = lambda mode, why: applied.append((mode, why))
        app._last_written = None
        app.active_game = None
        for exe, expect_key in (("cs2.exe", "cs2"),
                                ("cyberpunk2077.exe", "cyberpunk_rt"),
                                ("steam.exe", None)):
            applied.clear()
            app.active_game = None
            app._watch_step(exe)
            if expect_key is None:
                good = not applied
            else:
                want = P.hags_mode_for_game(app.gpu, app.vram, expect_key)[0]
                good = len(applied) == 1 and applied[0][0] == want
            print("  watch " + exe.ljust(22) + " -> "
                  + ("nothing written (correct)" if not applied
                     else "mode " + str(applied[0][0])))
            ok = ok and good

        print("")
        print("  RESULT  " + ("passes" if ok else "FAILS"))
        return 0 if ok else 1
    except Exception as e:
        print("  FAIL  the window did not build: " + repr(e))
        return 1
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:
                pass


# ----------------------------------------------------------------------- main

def main(argv):
    if "--selftest" in argv:
        return selftest()

    if "--smoke" in argv:
        return smoke()

    if "--report" in argv:
        txt = build_report()
        out = host.app_dir() / "hags_report.txt"
        try:
            out.write_text(txt, encoding="utf-8")
            print(txt)
            print("  written to " + str(out))
            return 0
        except OSError as e:
            print("could not write the report: " + str(e))
            return 1

    app = HagsApp(watch_on_start="--watch" in argv)
    app.log(APP_NAME + " " + APP_VERSION + " - rule: hags_policy.py, shared with the "
           "rest of the suite.", "head")
    if not host.is_admin():
        app.log("NOT ELEVATED: Windows will refuse the HwSchMode write. Close this and "
                "run it as administrator, or use the .bat which asks for it.", "warn")
    app.log("press APPLY FOR THIS TITLE, or turn the watcher on and let it follow your "
            "games.", "info")
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
