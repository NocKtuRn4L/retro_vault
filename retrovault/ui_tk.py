"""Tkinter UI for RetroVault.

Temporary home during the PySide6 migration — this module is removed
once the Qt UI reaches feature parity.
"""

import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from .core.config import (
    EMULATOR_PRESETS,
    SETUP_MODES,
    apply_recommended_emulator,
    get_recommended_emulator,
    is_emulator_configured,
    load_config,
    save_config,
)
from .core.launch import get_emulator_config, launch_rom
from .core.library import load_library, save_library, scan_roms
from .core.paths import CONFIG_FILE

COLORS = {
    "bg":        "#0d0d0d",
    "panel":     "#141414",
    "card":      "#1a1a1a",
    "border":    "#2a2a2a",
    "accent":    "#ff3c3c",
    "accent2":   "#ff8c00",
    "text":      "#f0f0f0",
    "subtext":   "#888888",
    "hover":     "#252525",
    "selected":  "#1f1f1f",
    "success":   "#00c853",
    "warning":   "#ffd600",
}

FONTS = {
    "title":   ("Courier New", 22, "bold"),
    "heading": ("Courier New", 13, "bold"),
    "body":    ("Courier New", 11),
    "small":   ("Courier New", 9),
    "tag":     ("Courier New", 8, "bold"),
}


class RetroVault(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RetroVault")
        self.geometry("1100x700")
        self.minsize(800, 550)
        self.configure(bg=COLORS["bg"])

        self.config_data = load_config()
        self.library = load_library()
        self.filtered_library = list(self.library)
        self.selected_system = "all"
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search)
        self.status_var = tk.StringVar(value="Welcome to RetroVault")

        self._build_ui()
        self._refresh_library_view()
        self.after(250, self._maybe_open_setup_wizard)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        topbar = tk.Frame(self, bg=COLORS["bg"], height=60)
        topbar.pack(fill=tk.X, padx=0, pady=0)
        topbar.pack_propagate(False)

        title_lbl = tk.Label(topbar, text="▶ RETROVAULT",
                             font=FONTS["title"], bg=COLORS["bg"],
                             fg=COLORS["accent"])
        title_lbl.pack(side=tk.LEFT, padx=20, pady=10)

        # Search
        search_frame = tk.Frame(topbar, bg=COLORS["border"], bd=0)
        search_frame.pack(side=tk.LEFT, padx=10, pady=14)
        tk.Label(search_frame, text=" 🔍 ", bg=COLORS["border"],
                 fg=COLORS["subtext"], font=FONTS["body"]).pack(side=tk.LEFT)
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                     bg=COLORS["border"], fg=COLORS["text"],
                                     insertbackground=COLORS["text"],
                                     relief=tk.FLAT, font=FONTS["body"], width=28,
                                     bd=4)
        self.search_entry.pack(side=tk.LEFT)

        # Buttons
        btn_frame = tk.Frame(topbar, bg=COLORS["bg"])
        btn_frame.pack(side=tk.RIGHT, padx=16)
        self._btn(btn_frame, "⟳ SCAN ROMS", self._scan_roms, accent=True).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "⚙ SETTINGS", self._open_settings).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "SETUP", self._open_setup_wizard).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "+ ADD ROM DIR", self._add_rom_dir).pack(side=tk.RIGHT, padx=4)

        # Divider
        tk.Frame(self, bg=COLORS["accent"], height=2).pack(fill=tk.X)

        # Main area
        main = tk.Frame(self, bg=COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True)

        # Left sidebar
        sidebar = tk.Frame(main, bg=COLORS["panel"], width=190)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="SYSTEMS", font=FONTS["tag"],
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 padx=16, pady=12).pack(anchor="w")

        self.sidebar_frame = tk.Frame(sidebar, bg=COLORS["panel"])
        self.sidebar_frame.pack(fill=tk.BOTH, expand=True)
        self._build_sidebar()

        # Separator
        tk.Frame(main, bg=COLORS["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Right: ROM list
        right = tk.Frame(main, bg=COLORS["bg"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Column headers
        header = tk.Frame(right, bg=COLORS["card"], height=32)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        for text, anchor, width in [("GAME", "w", 500), ("SYSTEM", "center", 120), ("EXT", "center", 70)]:
            tk.Label(header, text=text, font=FONTS["tag"], bg=COLORS["card"],
                     fg=COLORS["subtext"], anchor=anchor, width=width//8,
                     padx=16).pack(side=tk.LEFT)

        # Scrollable list
        list_frame = tk.Frame(right, bg=COLORS["bg"])
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, bg=COLORS["border"],
                                  troughcolor=COLORS["bg"],
                                  activebackground=COLORS["accent"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"],
                                 highlightthickness=0,
                                 yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.canvas.yview)

        self.rom_list_inner = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rom_list_inner, anchor="nw")

        self.rom_list_inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Status bar
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill=tk.X)
        statusbar = tk.Frame(self, bg=COLORS["panel"], height=28)
        statusbar.pack(fill=tk.X)
        statusbar.pack_propagate(False)
        self.status_lbl = tk.Label(statusbar, textvariable=self.status_var,
                                    font=FONTS["small"], bg=COLORS["panel"],
                                    fg=COLORS["subtext"], padx=16)
        self.status_lbl.pack(side=tk.LEFT, pady=4)

        self.count_lbl = tk.Label(statusbar, text="",
                                   font=FONTS["small"], bg=COLORS["panel"],
                                   fg=COLORS["subtext"], padx=16)
        self.count_lbl.pack(side=tk.RIGHT, pady=4)

    def _btn(self, parent, text, cmd, accent=False):
        bg = COLORS["accent"] if accent else COLORS["card"]
        fg = COLORS["bg"] if accent else COLORS["text"]
        b = tk.Label(parent, text=text, font=FONTS["tag"],
                     bg=bg, fg=fg, padx=12, pady=6, cursor="hand2",
                     relief=tk.FLAT)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["accent2"] if accent else COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _build_sidebar(self):
        for w in self.sidebar_frame.winfo_children():
            w.destroy()

        systems = self.config_data.get("systems", {})
        counts = {}
        for rom in self.library:
            counts[rom["system"]] = counts.get(rom["system"], 0) + 1

        entries = [("all", "🗂", "ALL GAMES", len(self.library))]
        for sid, sdef in systems.items():
            if counts.get(sid, 0) > 0:
                entries.append((sid, sdef["icon"], sdef["short"], counts.get(sid, 0)))

        for sid, icon, label, count in entries:
            is_sel = self.selected_system == sid
            row = tk.Frame(self.sidebar_frame,
                            bg=COLORS["accent"] if is_sel else COLORS["panel"],
                            cursor="hand2")
            row.pack(fill=tk.X, padx=8, pady=2)

            tk.Label(row, text=f"{icon} {label}", font=FONTS["body"],
                     bg=row["bg"], fg=COLORS["bg"] if is_sel else COLORS["text"],
                     padx=12, pady=7, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(row, text=str(count), font=FONTS["small"],
                     bg=row["bg"],
                     fg=COLORS["bg"] if is_sel else COLORS["subtext"],
                     padx=8).pack(side=tk.RIGHT)

            row.bind("<Button-1>", lambda e, s=sid: self._select_system(s))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, s=sid: self._select_system(s))
            row.bind("<Enter>", lambda e, r=row, s=sid: r.config(
                bg=COLORS["accent"] if self.selected_system == s else COLORS["hover"]))
            row.bind("<Leave>", lambda e, r=row, s=sid: r.config(
                bg=COLORS["accent"] if self.selected_system == s else COLORS["panel"]))

    def _refresh_library_view(self):
        for w in self.rom_list_inner.winfo_children():
            w.destroy()

        query = self.search_var.get().strip().lower()
        systems = self.config_data.get("systems", {})

        self.filtered_library = [
            r for r in self.library
            if (self.selected_system == "all" or r["system"] == self.selected_system)
            and (not query or query in r["name"].lower())
        ]

        if not self.filtered_library:
            msg = "No ROMs found."
            if not self.library:
                msg = "No ROMs in library.\nClick '+ ADD ROM DIR' to add a folder,\nthen '⟳ SCAN ROMS'."
            tk.Label(self.rom_list_inner, text=msg, font=FONTS["body"],
                     bg=COLORS["bg"], fg=COLORS["subtext"],
                     pady=60).pack()
        else:
            for i, rom in enumerate(self.filtered_library):
                self._make_rom_row(i, rom, systems)

        count_text = f"{len(self.filtered_library)} ROM{'s' if len(self.filtered_library) != 1 else ''}"
        self.count_lbl.config(text=count_text)
        self._build_sidebar()

    def _make_rom_row(self, i, rom, systems):
        sdef = systems.get(rom["system"], {})
        color = sdef.get("color", COLORS["subtext"])
        icon = sdef.get("icon", "?")
        sname = sdef.get("short", rom["system"].upper())
        bg = COLORS["bg"] if i % 2 == 0 else COLORS["card"]

        row = tk.Frame(self.rom_list_inner, bg=bg, cursor="hand2")
        row.pack(fill=tk.X)

        # Icon + name
        name_frame = tk.Frame(row, bg=bg)
        name_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=16, pady=7)
        tk.Label(name_frame, text=icon, font=FONTS["body"],
                 bg=bg, fg=color).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(name_frame, text=rom["name"], font=FONTS["body"],
                 bg=bg, fg=COLORS["text"], anchor="w").pack(side=tk.LEFT)

        # System badge
        badge = tk.Label(row, text=sname, font=FONTS["tag"],
                          bg=color, fg="white", padx=6, pady=2, width=7)
        badge.pack(side=tk.RIGHT, padx=(0, 80), pady=5)

        # Ext
        tk.Label(row, text=rom["ext"], font=FONTS["small"],
                 bg=bg, fg=COLORS["subtext"], width=6).pack(side=tk.RIGHT, padx=8)

        # Hover + click
        def on_enter(e, r=row, children=None):
            r.config(bg=COLORS["hover"])
            for c in r.winfo_children():
                try:
                    c.config(bg=COLORS["hover"])
                except Exception:
                    pass
                for cc in c.winfo_children():
                    try:
                        cc.config(bg=COLORS["hover"])
                    except Exception:
                        pass

        def on_leave(e, r=row, orig=bg):
            r.config(bg=orig)
            for c in r.winfo_children():
                try:
                    c.config(bg=orig)
                except Exception:
                    pass
                for cc in c.winfo_children():
                    try:
                        cc.config(bg=orig)
                    except Exception:
                        pass

        def on_click(e, r=rom):
            self._launch(r)

        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)
        row.bind("<Double-Button-1>", on_click)
        for child in row.winfo_children():
            child.bind("<Double-Button-1>", on_click)
            child.bind("<Enter>", on_enter)
            child.bind("<Leave>", on_leave)
            for cc in child.winfo_children():
                cc.bind("<Double-Button-1>", on_click)
                cc.bind("<Enter>", on_enter)
                cc.bind("<Leave>", on_leave)

        # Right-click context menu
        def show_menu(e, r=rom):
            menu = tk.Menu(self, tearoff=0, bg=COLORS["card"],
                            fg=COLORS["text"], activebackground=COLORS["accent"],
                            activeforeground=COLORS["bg"],
                            font=FONTS["small"], bd=0)
            menu.add_command(label=f"▶  Launch {r['name']}", command=lambda: self._launch(r))
            menu.add_separator()
            menu.add_command(label="📂  Open file location",
                              command=lambda: self._open_location(r))
            menu.add_command(label="🗑  Remove from library",
                              command=lambda: self._remove_rom(r))
            menu.tk_popup(e.x_root, e.y_root)

        row.bind("<Button-3>", show_menu)
        for child in row.winfo_children():
            child.bind("<Button-3>", show_menu)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _select_system(self, sid):
        self.selected_system = sid
        self._refresh_library_view()

    def _on_search(self, *args):
        self._refresh_library_view()

    def _launch(self, rom):
        self.status_var.set(f"Launching {rom['name']}...")
        def do_launch():
            ok, msg = launch_rom(rom, self.config_data)
            self.after(0, self._post_launch, rom, ok, msg)

        threading.Thread(target=do_launch, daemon=True).start()

    def _post_launch(self, rom, ok, msg):
        if ok:
            self.status_var.set(f"▶ Launched: {rom['name']}")
        else:
            self.status_var.set(f"⚠ Launch failed")
            messagebox.showerror("Launch Error", msg, parent=self)

    def _open_location(self, rom):
        path = Path(rom["path"]).parent
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _remove_rom(self, rom):
        self.library = [r for r in self.library if r["path"] != rom["path"]]
        save_library(self.library)
        self._refresh_library_view()
        self.status_var.set(f"Removed: {rom['name']}")

    def _add_rom_dir(self):
        d = filedialog.askdirectory(title="Select ROM Directory", parent=self)
        if d and d not in self.config_data["rom_dirs"]:
            self.config_data["rom_dirs"].append(d)
            save_config(self.config_data)
            self.status_var.set(f"Added ROM directory: {d}")

    def _scan_roms(self):
        self.status_var.set("Scanning...")
        self.update()

        def do_scan():
            new_lib = scan_roms(self.config_data)
            save_library(new_lib)
            self.library = new_lib
            self.after(0, self._post_scan, len(new_lib))

        threading.Thread(target=do_scan, daemon=True).start()

    def _post_scan(self, count):
        self._refresh_library_view()
        self.status_var.set(f"Scan complete — {count} ROM{'s' if count != 1 else ''} found")

    # ── Settings window ────────────────────────────────────────────────────────

    def _maybe_open_setup_wizard(self):
        if not self.config_data.get("setup", {}).get("completed", False):
            self._open_setup_wizard()

    def _open_url(self, url):
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Open URL", f"Could not open:\n{url}\n\n{type(e).__name__}: {e}", parent=self)

    def _open_setup_wizard(self):
        win = tk.Toplevel(self)
        win.title("RetroVault Setup")
        win.geometry("980x640")
        win.configure(bg=COLORS["bg"])
        win.grab_set()

        setup_cfg = self.config_data.get("setup", {})
        mode_var = tk.StringVar(value=setup_cfg.get("mode", "easy"))

        tk.Label(win, text="SETUP", font=FONTS["heading"],
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=20, pady=14).pack(anchor="w")
        tk.Frame(win, bg=COLORS["accent"], height=2).pack(fill=tk.X)
        tk.Label(
            win,
            text="Easy Mode keeps RetroVault focused on recommended standalone emulators. "
                 "Advanced Mode is reserved for RetroArch and core setup later.",
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            padx=20,
            pady=12,
            justify=tk.LEFT,
            wraplength=920,
        ).pack(anchor="w")

        mode_row = tk.Frame(win, bg=COLORS["bg"])
        mode_row.pack(fill=tk.X, padx=20, pady=(0, 8))
        tk.Radiobutton(
            mode_row,
            text=SETUP_MODES["easy"]["name"],
            variable=mode_var,
            value="easy",
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text"],
            selectcolor=COLORS["card"],
            activebackground=COLORS["bg"],
        ).pack(side=tk.LEFT, padx=(0, 16))
        tk.Radiobutton(
            mode_row,
            text=f"{SETUP_MODES['advanced']['name']} (Coming Soon)",
            variable=mode_var,
            value="advanced",
            state=tk.DISABLED,
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            selectcolor=COLORS["card"],
            activebackground=COLORS["bg"],
        ).pack(side=tk.LEFT)

        easy_frame = tk.LabelFrame(
            win,
            text=" Easy Mode Recommendations ",
            font=FONTS["tag"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
            bd=1,
            relief=tk.GROOVE,
        )
        easy_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=8)

        setup_vars = {}
        for sid, sdef in self.config_data["systems"].items():
            recommendation = get_recommended_emulator(sid)
            emu_cfg = get_emulator_config(sid, self.config_data)
            path_var = tk.StringVar(value=emu_cfg.get("path", ""))
            setup_vars[sid] = path_var

            row = tk.Frame(easy_frame, bg=COLORS["bg"])
            row.pack(fill=tk.X, padx=10, pady=6)

            left = tk.Frame(row, bg=COLORS["bg"], width=280)
            left.pack(side=tk.LEFT, fill=tk.Y)
            left.pack_propagate(False)
            tk.Label(left, text=f"{sdef['short']}  {recommendation.get('name', 'Custom')}",
                     font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text"],
                     anchor="w").pack(fill=tk.X)
            tk.Label(left, text=recommendation.get("notes", "No recommendation yet."),
                     font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["subtext"],
                     anchor="w", justify=tk.LEFT, wraplength=260).pack(fill=tk.X)

            center = tk.Frame(row, bg=COLORS["bg"])
            center.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            tk.Entry(center, textvariable=path_var, font=FONTS["small"],
                     bg=COLORS["card"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], relief=tk.FLAT).pack(fill=tk.X)

            actions = tk.Frame(row, bg=COLORS["bg"])
            actions.pack(side=tk.RIGHT)
            self._btn(actions, "DOWNLOAD", lambda rec=recommendation: self._open_url(rec["url"])).pack(side=tk.LEFT, padx=4)
            self._btn(actions, "BROWSE", lambda v=path_var: self._browse_file(v)).pack(side=tk.LEFT, padx=4)
            status_text = "READY" if is_emulator_configured(self.config_data, sid) else "NEEDED"
            status_fg = COLORS["success"] if status_text == "READY" else COLORS["warning"]
            tk.Label(actions, text=status_text, font=FONTS["tag"],
                     bg=COLORS["bg"], fg=status_fg, padx=6, pady=6).pack(side=tk.LEFT)

        tk.Label(
            win,
            text="Save uses recommended standalone emulator profiles and turns RetroArch off. "
                 "Advanced Mode will reuse this setup model later for RetroArch/core workflows.",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            padx=20,
            pady=8,
            justify=tk.LEFT,
            wraplength=920,
        ).pack(anchor="w")

        def save_setup():
            self.config_data["setup"]["mode"] = "easy"
            self.config_data["setup"]["completed"] = True
            self.config_data["use_retroarch"] = False
            for sid, path_var in setup_vars.items():
                self.config_data = apply_recommended_emulator(self.config_data, sid, path=path_var.get())
            save_config(self.config_data)
            self.status_var.set("Easy Mode setup saved.")
            win.destroy()

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill=tk.X)
        save_row = tk.Frame(win, bg=COLORS["bg"])
        save_row.pack(fill=tk.X, padx=16, pady=10)
        self._btn(save_row, "SAVE EASY MODE", save_setup, accent=True).pack(side=tk.RIGHT)
        self._btn(save_row, "CLOSE", win.destroy).pack(side=tk.RIGHT, padx=8)

    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings — RetroVault")
        win.geometry("980x620")
        win.configure(bg=COLORS["bg"])
        win.grab_set()

        tk.Label(win, text="⚙ SETTINGS", font=FONTS["heading"],
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=20, pady=14).pack(anchor="w")
        tk.Frame(win, bg=COLORS["accent"], height=2).pack(fill=tk.X)

        notebook = ttk.Notebook(win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["card"],
                         foreground=COLORS["text"], padding=[12, 6],
                         font=FONTS["tag"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["accent"])],
                   foreground=[("selected", COLORS["bg"])])

        # Tab 1: Emulators
        emu_frame = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(emu_frame, text="EMULATORS")

        ra_frame = tk.LabelFrame(emu_frame, text=" RetroArch ", font=FONTS["tag"],
                                   bg=COLORS["bg"], fg=COLORS["accent"],
                                   bd=1, relief=tk.GROOVE)
        ra_frame.pack(fill=tk.X, padx=12, pady=8)

        use_ra_var = tk.BooleanVar(value=self.config_data.get("use_retroarch", False))
        tk.Checkbutton(ra_frame, text="Use RetroArch as universal backend",
                        variable=use_ra_var, font=FONTS["body"],
                        bg=COLORS["bg"], fg=COLORS["text"],
                        selectcolor=COLORS["card"],
                        activebackground=COLORS["bg"]).pack(anchor="w", padx=8, pady=4)

        ra_path_var = tk.StringVar(value=self.config_data.get("retroarch_path", ""))
        self._path_row(ra_frame, "RetroArch binary:", ra_path_var, file=True)

        # Per-system emulators
        sys_frame = tk.LabelFrame(emu_frame, text=" Standalone Emulators ",
                                    font=FONTS["tag"], bg=COLORS["bg"],
                                    fg=COLORS["accent"], bd=1, relief=tk.GROOVE)
        sys_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        canvas2 = tk.Canvas(sys_frame, bg=COLORS["bg"], highlightthickness=0)
        sb2 = tk.Scrollbar(sys_frame, command=canvas2.yview)
        canvas2.configure(yscrollcommand=sb2.set)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        canvas2.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas2, bg=COLORS["bg"])
        canvas2.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas2.configure(scrollregion=canvas2.bbox("all")))

        emu_vars = {}
        profiles = self.config_data.get("emulator_profiles", EMULATOR_PRESETS)
        profile_choices = list(profiles.keys())
        for sid, sdef in self.config_data["systems"].items():
            emu_cfg = get_emulator_config(sid, self.config_data)
            path_var = tk.StringVar(value=emu_cfg.get("path", ""))
            args_var = tk.StringVar(value=emu_cfg.get("args", "{rom}"))
            profile_var = tk.StringVar(value=emu_cfg.get("profile", "custom"))
            emu_vars[sid] = (path_var, args_var, profile_var)

            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(fill=tk.X, padx=8, pady=3)
            tk.Label(row, text=f"{sdef['icon']} {sdef['name']}",
                      font=FONTS["body"], bg=COLORS["bg"],
                      fg=COLORS["text"], width=22, anchor="w").pack(side=tk.LEFT)
            tk.Entry(row, textvariable=path_var, font=FONTS["small"],
                      bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief=tk.FLAT,
                      width=28).pack(side=tk.LEFT, padx=4)
            tk.Label(row, text="args:", font=FONTS["small"],
                      bg=COLORS["bg"], fg=COLORS["subtext"]).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=args_var, font=FONTS["small"],
                      bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief=tk.FLAT,
                      width=14).pack(side=tk.LEFT, padx=4)
            tk.Label(row, text="profile:", font=FONTS["small"],
                      bg=COLORS["bg"], fg=COLORS["subtext"]).pack(side=tk.LEFT)
            profile_menu = tk.OptionMenu(row, profile_var, *profile_choices)
            profile_menu.config(bg=COLORS["card"], fg=COLORS["text"],
                                activebackground=COLORS["hover"], bd=0,
                                highlightthickness=0, font=FONTS["small"],
                                width=9)
            profile_menu["menu"].config(bg=COLORS["card"], fg=COLORS["text"],
                                         activebackground=COLORS["accent"])
            profile_menu.pack(side=tk.LEFT, padx=4)
            apply_btn = tk.Label(row, text="USE", font=FONTS["tag"],
                                 bg=COLORS["card"], fg=COLORS["text"],
                                 padx=6, cursor="hand2")
            apply_btn.pack(side=tk.LEFT)
            apply_btn.bind(
                "<Button-1>",
                lambda e, pv=profile_var, av=args_var: av.set(
                    profiles.get(pv.get(), profiles["custom"]).get("args", "{rom}")
                ),
            )
            btn = tk.Label(row, text="📂", font=FONTS["body"],
                            bg=COLORS["bg"], cursor="hand2")
            btn.pack(side=tk.LEFT)
            btn.bind("<Button-1>", lambda e, v=path_var: self._browse_file(v))

        # Tab 2: ROM Directories
        dirs_frame = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(dirs_frame, text="ROM DIRS")

        tk.Label(dirs_frame, text="ROM search directories:",
                  font=FONTS["body"], bg=COLORS["bg"],
                  fg=COLORS["subtext"], padx=12, pady=8).pack(anchor="w")

        dirs_listbox = tk.Listbox(dirs_frame, bg=COLORS["card"],
                                   fg=COLORS["text"], font=FONTS["small"],
                                   selectbackground=COLORS["accent"],
                                   relief=tk.FLAT, bd=0, height=10)
        dirs_listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        for d in self.config_data["rom_dirs"]:
            dirs_listbox.insert(tk.END, d)

        btn_row = tk.Frame(dirs_frame, bg=COLORS["bg"])
        btn_row.pack(fill=tk.X, padx=12, pady=4)

        def add_dir():
            d = filedialog.askdirectory(parent=win)
            if d:
                dirs_listbox.insert(tk.END, d)

        def remove_dir():
            sel = dirs_listbox.curselection()
            if sel:
                dirs_listbox.delete(sel[0])

        self._btn(btn_row, "+ ADD", add_dir, accent=True).pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "- REMOVE", remove_dir).pack(side=tk.LEFT, padx=4)

        # Tab 3: Systems
        sys_tab = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(sys_tab, text="SYSTEMS")

        tk.Label(sys_tab,
                  text="Systems are auto-detected by file extension.\nAdd custom systems by editing the config file directly.",
                  font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["subtext"],
                  padx=12, pady=8, justify=tk.LEFT).pack(anchor="w")

        for sid, sdef in self.config_data["systems"].items():
            row = tk.Frame(sys_tab, bg=COLORS["card"])
            row.pack(fill=tk.X, padx=12, pady=2)
            tk.Label(row, text=f"{sdef['icon']}  {sdef['name']}",
                      font=FONTS["body"], bg=COLORS["card"],
                      fg=COLORS["text"], padx=12, pady=6, width=28, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text="  ".join(sdef["extensions"]),
                      font=FONTS["small"], bg=COLORS["card"],
                      fg=COLORS["subtext"], padx=8).pack(side=tk.LEFT)

        tk.Label(sys_tab, text=f"Config file: {CONFIG_FILE}",
                  font=FONTS["small"], bg=COLORS["bg"],
                  fg=COLORS["subtext"], padx=12, pady=8).pack(anchor="w", side=tk.BOTTOM)

        # Save button
        def save_settings():
            # ROM dirs
            self.config_data["rom_dirs"] = list(dirs_listbox.get(0, tk.END))
            # RetroArch
            self.config_data["use_retroarch"] = use_ra_var.get()
            self.config_data["retroarch_path"] = ra_path_var.get()
            # Emulators
            for sid, (pv, av, profv) in emu_vars.items():
                self.config_data["emulators"][sid] = {
                    "path": pv.get(),
                    "args": av.get(),
                    "profile": profv.get(),
                }
            save_config(self.config_data)
            self.status_var.set("Settings saved.")
            win.destroy()

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill=tk.X)
        save_row = tk.Frame(win, bg=COLORS["bg"])
        save_row.pack(fill=tk.X, padx=16, pady=10)
        self._btn(save_row, "✓ SAVE SETTINGS", save_settings, accent=True).pack(side=tk.RIGHT)
        self._btn(save_row, "✕ CANCEL", win.destroy).pack(side=tk.RIGHT, padx=8)

    def _path_row(self, parent, label, var, file=False):
        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(row, text=label, font=FONTS["small"],
                  bg=COLORS["bg"], fg=COLORS["subtext"], width=20, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row, textvariable=var, font=FONTS["small"],
                  bg=COLORS["card"], fg=COLORS["text"],
                  insertbackground=COLORS["text"], relief=tk.FLAT, width=36).pack(side=tk.LEFT, padx=4)
        browse = tk.Label(row, text="📂", font=FONTS["body"],
                           bg=COLORS["bg"], cursor="hand2")
        browse.pack(side=tk.LEFT)
        if file:
            browse.bind("<Button-1>", lambda e: self._browse_file(var))
        else:
            browse.bind("<Button-1>", lambda e: self._browse_dir(var))

    def _browse_file(self, var):
        f = filedialog.askopenfilename(parent=self)
        if f:
            var.set(f)

    def _browse_dir(self, var):
        d = filedialog.askdirectory(parent=self)
        if d:
            var.set(d)

    # ── Canvas helpers ─────────────────────────────────────────────────────────

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
