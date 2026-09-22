"""Tkinter desktop UI for the Victoria II Mistral Analyzer.

The interface deliberately borrows the game's visual feel: flags, country
colors and names are read live from the user's own Victoria II installation
(no assets are bundled with this app).  The palette is the parchment theme
from www.caleb.ee.
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from vic2analyzer import discovery
from vic2analyzer.analyzer import SaveAnalyzer
from vic2analyzer.gamefiles import GameFiles
from vic2analyzer.parser import parse_file

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.ticker import FuncFormatter
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# Parchment palette from www.caleb.ee.
BG = "#e3d5b8"
FG = "#3e3529"
ACCENT = "#4a0000"
GOLD = "#c98d00"
PANEL = "#f1e5cd"
PANEL2 = "#d6c7ab"
BUTTON = "#5d4a37"
BUTTON_ACTIVE = "#7a634e"
INPUT_BG = "#f1e5cd"


def vfmt(n) -> str:
    """Integer with '.' thousands separators: 3500000 -> 3.500.000."""
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def money_fmt(n) -> str:
    """Money with full digits and period separators (never 1e6)."""
    try:
        return f"£{float(n):,.2f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def reform_color(level) -> str:
    """Red (worst) -> green (best) hex for a reform level in 0.0..1.0."""
    try:
        level = float(level)
    except (TypeError, ValueError):
        level = 0.0
    level = max(0.0, min(1.0, level))
    r = int(178 - 118 * level)
    g = int(34 + 122 * level)
    b = int(34 + 8 * level)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_color(rgb, fallback="#8a7a5f") -> str:
    try:
        r, g, b = (max(0, min(255, int(c))) for c in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"
    except (TypeError, ValueError):
        return fallback


INCOME_LABELS = {
    "taxes_poor": "Poor tax", "taxes_middle": "Middle tax", "taxes_rich": "Rich tax",
    "tariffs": "Tariffs", "gold": "Gold", "national_stockpile": "Stockpile sales",
    "industry_subsidies": "Industry subsidies", "education": "Education",
    "administration": "Administration", "military": "Military",
}


class App(tk.Tk):
    # Save-file tags whose flag files don't exist in the install (the game's
    # own files use e.g. SWI for Switzerland while history can record SUI).
    FLAG_ALIASES = {"SUI": "SWI"}

    def __init__(self):
        super().__init__()
        self.title("Victoria II Mistral Analyzer")
        self.geometry("1180x800")
        self.minsize(940, 640)
        self.configure(bg=BG)
        self._set_style()

        self.game_files: Optional[GameFiles] = None
        self.analyzers: Dict[str, SaveAnalyzer] = {}
        self._photo_refs: List[object] = []
        self._worker: Optional[threading.Thread] = None

        self._build_toolbar()
        self._build_status()
        self._build_tabs()

        self.after(10, self._auto_setup)

    # ------------------------------------------------------------ style

    def _set_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL2, foreground=FG, padding=(12, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL)],
                  foreground=[("selected", ACCENT)])
        style.configure("Treeview", background=PANEL, foreground=FG,
                        fieldbackground=PANEL, rowheight=22)
        style.configure("Treeview.Heading", background=PANEL2, foreground=ACCENT)
        style.map("Treeview",
                  background=[("selected", GOLD)],
                  foreground=[("selected", "#2b2100")])
        style.configure("TButton", background=BUTTON, foreground="#f1e5cd", padding=(10, 4))
        style.map("TButton",
                  background=[("active", BUTTON_ACTIVE), ("pressed", BUTTON_ACTIVE)],
                  foreground=[("active", "#f1e5cd"), ("pressed", "#f1e5cd")])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Status.TLabel", background=PANEL, foreground=FG)
        style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=("Georgia", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=FG, font=("Georgia", 10, "italic"))

    # ----------------------------------------------------------- toolbar

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=PANEL2)
        bar.pack(fill="x", padx=0, pady=0)
        self._install_label = tk.Label(bar, text="No Victoria II installation selected",
                                       fg=FG, bg=PANEL2)
        self._install_label.pack(side="left", padx=10, pady=6)
        ttk.Button(bar, text="Choose install…", command=self._choose_install).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Add save file…", command=self._choose_save).pack(side="left", padx=4)
        ttk.Button(bar, text="Rescan save folder", command=self._rescan).pack(side="left", padx=4)

    def _build_status(self):
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", side="bottom")
        self._status = ttk.Label(bar, text="Ready.", style="Status.TLabel")
        self._status.pack(anchor="w", padx=10, pady=4)

    def _build_tabs(self):
        self._tabs = ttk.Notebook(self)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self._welcome = WelcomeTab(self)
        self._tabs.add(self._welcome, text="  Welcome  ")
        for tab in (WarsTab, PopulationTab, EconomyTab, PoliticsTab, ImmigrationTab):
            widget = tab(self)
            setattr(self, f"_tab_{tab.__name__}", widget)
            self._tabs.add(widget, text=f"  {tab.TITLE}  ")

    # -------------------------------------------------------------- setup

    def _auto_setup(self):
        config = discovery.load_config()
        install = discovery.find_install(config.get("install_dir"))
        if install:
            self._set_install(install)
        if not install:
            self._status.config(text="Could not find Victoria II automatically — use 'Choose install…'")

    def _set_install(self, path: str):
        self.game_files = GameFiles(path)
        discovery.save_config({"install_dir": path})
        self._install_label.config(text=f"Install: {path}")

    def _choose_install(self):
        path = filedialog.askdirectory(title="Select your Victoria II install folder")
        if not path:
            return
        if not discovery._looks_like_install(path):
            messagebox.showwarning("Not a Victoria II install", "That folder doesn't look like a Victoria II installation (no common/gfx/map folders).")
            return
        self._set_install(path)
        self._rescan()

    def _choose_save(self):
        paths = filedialog.askopenfilenames(
            title="Select .v2 save game(s)",
            filetypes=[("Victoria II saves", "*.v2 *.v2e"), ("All files", "*.*")],
        )
        for path in paths:
            self._load_save_async(path)

    def _rescan(self):
        install = self.game_files.install_dir if self.game_files else None
        dirs = discovery.find_save_dirs(install)
        saves = discovery.list_saves(dirs)
        if not saves:
            self._status.config(text="No save games found — add one manually with 'Add save file…'")
            return
        for save in saves[:3]:
            self._load_save_async(save["path"])

    # ------------------------------------------------------------- loading

    def _load_save_async(self, path: str):
        if path in self.analyzers:
            self._status.config(text=f"Already loaded: {os.path.basename(path)}")
            return
        self._status.config(text=f"Loading {os.path.basename(path)} … (parsing, this can take ~30s)")
        def work():
            try:
                tree = parse_file(path)
                analyzer = SaveAnalyzer(tree, self.game_files)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Load failed", f"Could not parse {path}:\n{exc}"))
                return
            def done():
                self.analyzers[path] = analyzer
                label = f"{analyzer.player} {analyzer.date.replace('.', '/')}"
                self._refresh_tabs()
                self._status.config(text=f"Loaded {label} from {os.path.basename(path)}")
            self.after(0, done)
        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _refresh_tabs(self):
        self._welcome.refresh()
        for name in ("WarsTab", "PopulationTab", "EconomyTab", "PoliticsTab", "ImmigrationTab"):
            widget = getattr(self, f"_tab_{name}", None)
            if widget is not None:
                widget.refresh()
        self._tabs.select(1 if self.analyzers else 0)

    def latest(self) -> Optional[SaveAnalyzer]:
        if not self.analyzers:
            return None
        return list(self.analyzers.values())[-1]

    def flag_photo(self, tag: str, size=(48, 32)) -> Optional[object]:
        if self.game_files is None or ImageTk is None:
            return None
        government = None
        an = self.latest()
        if an is not None:
            block = an._country_block(tag)
            if isinstance(block, dict):
                government = block.get("government")
        img = self.game_files.flag_image(tag, government, size=size)
        if img is None:
            img = self.game_files.flag_image(tag, size=size)
        if img is None:
            alias = self.FLAG_ALIASES.get(tag)
            if alias:
                img = self.game_files.flag_image(alias, size=size)
        if img is None:
            return None
        photo = ImageTk.PhotoImage(img)
        self._photo_refs.append(photo)
        return photo

    def country_label(self, tag: str) -> str:
        if self.game_files is not None:
            name = self.game_files.country_names().get(tag)
            if name:
                return name
        return tag


class _ChartMixin:
    HAS_MPL_CHART = HAS_MPL

    def make_figure(self, parent, title: str, figsize=(6, 4)):
        fig = Figure(figsize=figsize, dpi=100, facecolor=PANEL)
        ax = fig.add_subplot(111)
        self._style_axes(ax, title)
        canvas = FigureCanvasTkAgg(fig, master=parent)
        return fig, ax, canvas

    @staticmethod
    def _style_axes(ax, title: str):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(PANEL2)
        ax.set_title(title, color=ACCENT, fontsize=11)


class WelcomeTab(tk.Frame, _ChartMixin):
    TITLE = "Welcome"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        inner = tk.Frame(self, bg=BG)
        inner.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(inner, text="Victoria II Mistral Analyzer", font=("Georgia", 26, "bold"),
                 fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(inner, text="War, economy and population analytics for your Heart of Darkness saves.",
                 font=("Georgia", 11, "italic"), fg=FG, bg=BG).pack(anchor="w", pady=(0, 6))
        body = (
            "1. Point the toolbar at your Victoria II installation (auto-detected on most systems).\n"
            "2. Load one or more .v2 save games — the map below shows the world as recorded in the save.\n"
            "3. Explore wars & battles, population, economy and politics tabs.\n\n"
            "All names, flags, colors and icons are read from your own game installation at runtime;\n"
            "this app bundles no Paradox Interactive assets."
        )
        tk.Label(inner, text=body, justify="left", font=("Georgia", 10), fg=FG, bg=BG).pack(anchor="w")
        self._map_label = tk.Label(inner, text="No save loaded yet — the world map will appear here.",
                                  font=("Georgia", 11, "italic"), fg=BUTTON, bg=BG)
        self._map_label.pack(anchor="w", pady=(10, 2))
        self._map_area = tk.Frame(self, bg=BG)
        self._map_area.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        self._fig = None

    def refresh(self):
        an = self._app.latest()
        if an is None or not HAS_MPL or self._app.game_files is None:
            return
        if self._fig is None:
            self._map_label.config(text="")
            self._fig, ax, canvas = self.make_figure(self._map_area, "", figsize=(11, 3.9))
            self._ax = ax
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self._canvas = canvas
        self._draw_map(an)

    def _draw_map(self, an: SaveAnalyzer):
        ax = self._ax
        ax.clear()
        self._style_axes(ax, "")
        ax.set_xticks([])
        ax.set_yticks([])
        gf = self._app.game_files
        owners = an.province_owners()
        positions = gf.province_positions()
        if not owners or not positions:
            self._canvas.draw()
            return
        width, height = gf.map_size()
        ax.set_xlim(0, width)
        ax.set_ylim(0, height)
        ax.set_facecolor("#c8d8e8")
        colors = gf.country_colors()
        player = an.player
        xs, ys, cs = [], [], []
        px, py = [], []
        for pid, tag in owners.items():
            pos = positions.get(pid)
            if pos is None:
                continue
            if tag == player:
                px.append(pos[0])
                py.append(pos[1])
                continue
            rgb = colors.get(tag, (140, 140, 140))
            xs.append(pos[0])
            ys.append(pos[1])
            cs.append(_hex_color(rgb))
        if xs:
            ax.scatter(xs, ys, s=5, c=cs, marker="s", linewidths=0)
        if px:
            ax.scatter(px, py, s=9, c=GOLD, marker="s", linewidths=0.3,
                       edgecolors=ACCENT, zorder=3, label=self._app.country_label(player))
            ax.legend(loc="lower right", facecolor=PANEL, edgecolor=PANEL2,
                      labelcolor=FG, fontsize=8)
        self._canvas.draw()


class WarsTab(tk.Frame):
    TITLE = "Wars & Battles"

    COLUMNS = ("war", "dates", "attacker", "defender", "battles", "losses_a", "losses_d")
    HEADERS = {"war": "War", "dates": "Dates", "attacker": "Attacker(s)",
               "defender": "Defender(s)", "battles": "Battles",
               "losses_a": "Att. losses", "losses_d": "Def. losses"}

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        self._filter_var = tk.BooleanVar(value=False)
        self._sort_col = "dates"
        self._sort_desc = True
        self._wars: List = []
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Wars & Battles", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        self._filter_cb = ttk.Checkbutton(
            top, text="Only wars with battles", variable=self._filter_var,
            command=self.refresh,
        )
        self._filter_cb.pack(side="left", padx=12)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=8, pady=4)
        self._tree = ttk.Treeview(wrap, columns=self.COLUMNS, show="headings", selectmode="browse")
        for col in self.COLUMNS:
            self._tree.heading(col, text=self.HEADERS[col],
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=180 if col in ("war", "attacker", "defender") else 90, anchor="w")
        self._tree.column("war", width=270)
        self._tree.column("attacker", width=190)
        self._tree.column("defender", width=190)
        self._tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select_war)

        detail = tk.Frame(self, bg=PANEL)
        detail.pack(fill="x", padx=8, pady=(4, 10))
        self._detail_title = tk.Label(detail, text="Select a war to see its details.", justify="left",
                                      anchor="w", fg=ACCENT, bg=PANEL, font=("Georgia", 12, "bold"))
        self._detail_title.pack(fill="x", padx=8, pady=(6, 0))
        self._flags_row = tk.Frame(detail, bg=PANEL)
        self._flags_row.pack(fill="x", padx=8, pady=4)
        self._detail_label = tk.Label(detail, text="", justify="left", anchor="w", fg=FG, bg=PANEL,
                                     font=("Georgia", 10))
        self._detail_label.pack(fill="x", padx=8, pady=(0, 8))

    # ------------------------------------------------------------- sorting

    def _war_sort_key(self, war, col: str):
        if col == "war":
            return war.name.lower()
        if col == "dates":
            return war.start_date or ""
        if col == "battles":
            return len(war.battles)
        if col == "losses_a":
            return sum(b.attacker_losses for b in war.battles)
        if col == "losses_d":
            return sum(b.defender_losses for b in war.battles)
        return ""

    def _sort_by(self, col: str):
        if col == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = col in ("battles", "losses_a", "losses_d")
        self._populate()

    def _heading_text(self, col: str) -> str:
        arrow = ""
        if col == self._sort_col:
            arrow = " ▼" if self._sort_desc else " ▲"
        return self.HEADERS[col] + arrow

    # ------------------------------------------------------------ contents

    def refresh(self):
        an = self._app.latest()
        self._wars = an.wars() if an is not None else []
        self._populate()

    def _populate(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        for col in self.COLUMNS:
            self._tree.heading(col, text=self._heading_text(col))
        wars = list(self._wars)
        if self._filter_var.get():
            wars = [w for w in wars if w.battles]
        wars.sort(key=lambda w: self._war_sort_key(w, self._sort_col),
                  reverse=self._sort_desc)
        self._war_items = []
        for counter, war in enumerate(wars):
            losses_a = sum(b.attacker_losses for b in war.battles)
            losses_d = sum(b.defender_losses for b in war.battles)
            iid = f"war{counter}"
            self._war_items.append((iid, war))
            self._tree.insert("", "end", iid=iid, values=(
                war.name,
                f"{(war.start_date or '?').replace('.', '/')} – {(war.end_date or '?').replace('.', '/')}",
                self._side_names(war.attackers, war.original_attacker),
                self._side_names(war.defenders, war.original_defender),
                len(war.battles),
                vfmt(losses_a),
                vfmt(losses_d),
            ))
        self._clear_flags_row()
        self._detail_title.config(text="Select a war to see its details.")
        self._detail_label.config(text="")

    def _side_names(self, tags: List[str], original: str) -> str:
        if tags:
            return ", ".join(self._app.country_label(t) for t in tags)
        if original and original != "---":
            return self._app.country_label(original)
        return "—"

    def _clear_flags_row(self):
        for child in self._flags_row.winfo_children():
            child.destroy()

    def _add_flag_chip(self, parent: tk.Frame, tag: str, highlight: bool = False) -> None:
        chip_bg = GOLD if highlight else PANEL2
        chip = tk.Frame(parent, bg=chip_bg)
        chip.pack(side="left", padx=3)
        photo = self._app.flag_photo(tag, size=(48, 32))
        if photo:
            tk.Label(chip, image=photo, bg=chip_bg).pack(padx=(4, 0))
        else:
            tk.Label(chip, text=f"[{tag}]", bg=chip_bg, fg=FG,
                     font=("Georgia", 10, "bold")).pack(padx=(4, 0), pady=(6, 0))
        name = self._app.country_label(tag)
        tk.Label(chip, text=name, bg=chip_bg,
                 fg=ACCENT if highlight else FG,
                 font=("Georgia", 8)).pack(pady=(0, 3), padx=2)

    def _render_flags_row(self, war) -> None:
        self._clear_flags_row()
        attackers = war.attackers or ([war.original_attacker] if war.original_attacker != "---" else [])
        defenders = war.defenders or ([war.original_defender] if war.original_defender != "---" else [])
        tk.Label(self._flags_row, text="Attackers:", fg=FG, bg=PANEL,
                 font=("Georgia", 9, "bold")).pack(side="left", padx=(2, 4))
        for tag in attackers:
            self._add_flag_chip(self._flags_row, tag, highlight=(tag == war.original_attacker))
        if attackers or defenders:
            tk.Label(self._flags_row, text="  vs  ", fg=FG, bg=PANEL,
                     font=("Georgia", 10, "italic")).pack(side="left", padx=4)
        if defenders:
            tk.Label(self._flags_row, text="Defenders:", fg=FG, bg=PANEL,
                     font=("Georgia", 9, "bold")).pack(side="left", padx=(2, 4))
        for tag in defenders:
            self._add_flag_chip(self._flags_row, tag, highlight=(tag == war.original_defender))

    def _on_select_war(self, _event=None):
        selection = self._tree.selection()
        if not selection or not self._wars:
            return
        iid = selection[0]
        war = next((w for item, w in self._war_items if item == iid), None)
        if war is None:
            return
        self._detail_title.config(text=(
            f"{war.name}   "
            f"({(war.start_date or '?').replace('.', '/')} – {(war.end_date or war.action or '?').replace('.', '/')})"
        ))
        self._render_flags_row(war)
        if not war.battles:
            self._detail_label.config(text=(
                "No battles were recorded for this war.\n"
                "Victoria II only records battles where armies actually met in combat — colonial and\n"
                "concession wars are often resolved without a fight (the target capitulates, or the\n"
                "wargoal is conceded without resistance). These are real, bloodless wars."
            ))
            return
        biggest = sorted(war.battles, key=lambda b: b.total_losses, reverse=True)[:8]
        lines = [f"{len(war.battles)} battles — deadliest:", ""]
        for b in biggest:
            lines.append(
                f"  {b.date.replace('.', '/')} {b.name}: {self._app.country_label(b.attacker)} vs "
                f"{self._app.country_label(b.defender)} — losses {vfmt(b.attacker_losses)} vs {vfmt(b.defender_losses)}"
                f" ({'attacker' if b.attacker_won else 'defender'} won)"
            )
        lines.append("")
        lines.append(f"Total recorded losses: attacker {vfmt(war.attacker_losses)} / defender {vfmt(war.defender_losses)}")
        self._detail_label.config(text="\n".join(lines))


class PopulationTab(tk.Frame, _ChartMixin):
    TITLE = "Population"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Population", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        self._selector = ttk.Combobox(top, state="readonly", width=40)
        self._selector.pack(side="left", padx=10)
        self._selector.bind("<<ComboboxSelected>>", lambda e: self._draw())

        info = tk.Frame(self, bg=PANEL)
        info.pack(fill="x", padx=8, pady=4)
        self._info = tk.Label(info, text="", justify="left", anchor="w", fg=FG, bg=PANEL,
                              font=("Georgia", 10))
        self._info.pack(fill="x", padx=8, pady=6)

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self._fig_left = self.make_figure(bottom, "Population by type", figsize=(5.4, 4.6))
        self._fig_left[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._fig_right = self.make_figure(bottom, "Literacy / militancy / consciousness", figsize=(4.2, 4.6))
        self._fig_right[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

        self._wealth_panel = tk.Frame(bottom, bg=PANEL)
        self._wealth_panel.pack(side="left", fill="both", expand=True, padx=(4, 0))
        tk.Label(self._wealth_panel, text="Wealthiest & poorest POPs", fg=ACCENT, bg=PANEL,
                 font=("Georgia", 11, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        self._wealth_rich = tk.Label(self._wealth_panel, text="", justify="left", anchor="w",
                                     fg=FG, bg=PANEL, font=("Georgia", 9))
        self._wealth_rich.pack(anchor="w", padx=6, pady=2)
        self._wealth_poor = tk.Label(self._wealth_panel, text="", justify="left", anchor="w",
                                    fg=FG, bg=PANEL, font=("Georgia", 9))
        self._wealth_poor.pack(anchor="w", padx=6, pady=(2, 6))

        self._issues_label = tk.Label(self, text="", justify="left", anchor="w",
                                      fg=FG, bg=BG, font=("Georgia", 10))
        self._issues_label.pack(fill="x", padx=10, pady=(0, 4))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        tags = an.country_tags()
        self._tags = tags
        self._selector["values"] = [f"{self._app.country_label(t)} ({t})" for t in tags]
        player_idx = tags.index(an.player) if an.player in tags else 0
        self._selector.current(player_idx)
        self._draw()

    def _pop_name(self, entry) -> str:
        gf = self._app.game_files
        prov = gf.province_name(entry.province_id) if gf is not None else entry.province_id
        return (f"{entry.pop_type.capitalize()} — {entry.culture.capitalize()} in {prov}: "
                f"{vfmt(entry.size)} pops, {money_fmt(entry.money_per_pop)} each")

    def _draw(self):
        an = self._app.latest()
        if an is None or not hasattr(self, "_tags"):
            return
        idx = self._selector.current()
        if idx < 0:
            return
        tag = self._tags[idx]
        pop = an.pop_stats(tag)
        gf = self._app.game_files
        self._info.config(text=(
            f"{self._app.country_label(tag)} — total population {vfmt(pop.size)}   |   "
            f"literacy {pop.literacy:.1%}   |   avg militancy {pop.militancy:.2f}   |   "
            f"avg consciousness {pop.consciousness:.2f}"
        ))

        fig, ax, canvas = self._fig_left
        ax.clear()
        self._style_axes(ax, "Population by type")
        items = sorted(pop.by_type.items(), key=lambda kv: -kv[1])
        if items:
            types = [k.capitalize() for k, _ in items][::-1]
            sizes = [v for _, v in items][::-1]
            ax.barh(range(len(types)), sizes, color=GOLD)
            ax.set_yticks(range(len(types)))
            ax.set_yticklabels(types)
            ax.tick_params(axis="y", length=0)
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.ticklabel_format(axis="x", useOffset=False, style="plain")
            if gf is not None and HAS_MPL and Image is not None:
                from matplotlib.offsetbox import AnnotationBbox, OffsetImage
                for row, (ptype, _size) in enumerate(items[::-1]):
                    img = gf.pop_icon(ptype, size=(22, 22))
                    if img is None:
                        continue
                    box = AnnotationBbox(
                        OffsetImage(_pil_to_array(img), resample=True),
                        (-0.02, row), xycoords=("axes fraction", "data"),
                        box_alignment=(1.0, 0.5), frameon=False)
                    ax.add_artist(box)
        fig.subplots_adjust(left=0.30)
        canvas.draw()

        fig, ax, canvas = self._fig_right
        ax.clear()
        self._style_axes(ax, "Literacy / militancy / consciousness")
        metrics = ("Literacy %", "Avg militancy", "Avg consciousness")
        values = [pop.literacy * 100, pop.militancy, pop.consciousness]
        ax.bar(metrics, values, color=["#5d7a4a", "#8a3a2a", "#4a5d7a"])
        ax.tick_params(axis="x", labelsize=8, labelrotation=12)
        canvas.draw()

        rich_lines = ["Wealthiest POPs (money per pop):"]
        rich_lines += [f"  {money_fmt(e.money_per_pop):>14}  {self._pop_name(e)[len(e.pop_type) + 1:]}"
                       for e in pop.richest[:5]]
        self._wealth_rich.config(text="\n".join(rich_lines))
        poor_lines = ["Poorest POPs (money per pop):"]
        poor_lines += [f"  {money_fmt(e.money_per_pop):>14}  {self._pop_name(e)[len(e.pop_type) + 1:]}"
                       for e in pop.poorest[:5]]
        self._wealth_poor.config(text="\n".join(poor_lines))

        if pop.by_issues and gf is not None:
            names = gf.pop_issue_names()
            total = sum(pop.by_issues.values()) or 1.0
            top_issues = sorted(pop.by_issues.items(), key=lambda kv: -kv[1])[:8]
            parts = [f"{names.get(i, 'Issue ' + i)} {v / total:.0%}"
                     for i, v in top_issues]
            self._issues_label.config(
                text="Most important issues: " + "   ·   ".join(parts))
        else:
            self._issues_label.config(text="")


def _pil_to_array(img):
    import numpy  # type: ignore
    return numpy.asarray(img)


class EconomyTab(tk.Frame, _ChartMixin):
    TITLE = "Economy"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Economy", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        self._selector = ttk.Combobox(top, state="readonly", width=40)
        self._selector.pack(side="left", padx=10)
        self._selector.bind("<<ComboboxSelected>>", lambda e: self._draw())

        self._info = tk.Label(self, text="", justify="left", anchor="w", fg=FG, bg=BG,
                              font=("Georgia", 10))
        self._info.pack(fill="x", padx=10, pady=2)
        self._highlights = tk.Label(self, text="", justify="left", anchor="w",
                                    fg=ACCENT, bg=BG, font=("Georgia", 11, "bold"))
        self._highlights.pack(fill="x", padx=10, pady=(2, 6))

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig_left = self.make_figure(charts, "Daily income by category", figsize=(6, 4.4))
        self._fig_left[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._fig_right = self.make_figure(charts, "Share of world production", figsize=(6, 4.4))
        self._fig_right[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        tags = an.country_tags()
        self._tags = tags
        self._selector["values"] = [f"{self._app.country_label(t)} ({t})" for t in tags]
        player_idx = tags.index(an.player) if an.player in tags else 0
        self._selector.current(player_idx)
        self._draw()

    @staticmethod
    def _world_rank(an, good: str, tag: str) -> int:
        producers = [(t, goods.get(good, 0.0))
                      for t, goods in an.production_by_country().items()]
        producers.sort(key=lambda kv: -kv[1])
        for rank, (t, _amount) in enumerate(producers, start=1):
            if t == tag:
                return rank
        return 0

    def _draw(self):
        an = self._app.latest()
        if an is None or not hasattr(self, "_tags"):
            return
        idx = self._selector.current()
        if idx < 0:
            return
        tag = self._tags[idx]
        gf = self._app.game_files
        econ = an.country_economy(tag)
        stats = an.country_stats(tag)
        net = sum(econ["incomes"].values()) - sum(econ["expenses"].values())
        self._info.config(text=(
            f"{self._app.country_label(tag)} — treasury {money_fmt(econ['money'])}   |   "
            f"factories {stats.factories} (level {stats.factory_levels}, {vfmt(stats.factory_workers)} workers)   |   "
            f"daily balance {money_fmt(net)}"
        ))
        highlights = an.production_highlights(tag, top=3)
        if highlights:
            parts = []
            for h in highlights:
                good = h["good"].replace("_", " ")
                if gf is not None:
                    good = gf.display_name(h["good"])
                share = h["share"]
                if share >= 0.25:
                    parts.append(f"Produces {share:.0%} of the world's {good} — world leader!")
                elif share >= 0.05:
                    parts.append(f"{share:.0%} of world {good} (#{self._world_rank(an, h['good'], tag)})")
                else:
                    parts.append(f"{share:.1%} of world {good}")
            self._highlights.config(text="★  " + "     ★  ".join(parts))
        else:
            self._highlights.config(text="")

        fig, ax, canvas = self._fig_left
        ax.clear()
        self._style_axes(ax, "Daily income by category")
        incomes = {k: v for k, v in econ["incomes"].items() if v > 0}
        if incomes:
            items = sorted(incomes.items(), key=lambda kv: kv[1])
            labels = [INCOME_LABELS.get(k, k.replace("_", " ").capitalize())
                      for k, _ in items]
            values = [v for _, v in items]
            ax.barh(labels, values, color=GOLD)
            ax.tick_params(axis="y", labelsize=8)
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(axis="y", length=0)
            ax.ticklabel_format(axis="x", useOffset=False, style="plain")
        canvas.draw()

        fig, ax, canvas = self._fig_right
        ax.clear()
        self._style_axes(ax, "Share of world production")
        totals = an.world_production_totals()
        production = an.production_by_country().get(tag, {})
        shares = []
        for good, amount in production.items():
            total = totals.get(good, 0.0)
            if total > 0 and amount > 0:
                shares.append((good, amount / total))
        shares.sort(key=lambda kv: kv[1])
        if shares:
            goods = [gf.display_name(k) if gf is not None else k.replace("_", " ") for k, _ in shares][-10:]
            values = [v * 100 for _, v in shares][-10:]
            colors = [reform_color(v) for v in values]
            ax.barh(goods, values, color=colors)
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(axis="y", length=0, labelsize=8)
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _p: f"{x:.0f}%"))
        canvas.draw()


class PoliticsTab(tk.Frame, _ChartMixin):
    TITLE = "Politics"

    REFORM_LABELS = {
        "slavery": "Slavery", "vote_franschise": "Voting franchise",
        "upper_house_composition": "Upper house composition",
        "voting_system": "Voting system", "public_meetings": "Public meetings",
        "press_rights": "Press rights", "trade_unions": "Trade unions",
        "political_parties": "Political parties", "wage_reform": "Minimum wage",
        "work_hours": "Work hours", "safety_regulations": "Safety regulations",
        "unemployment_subsidies": "Unemployment subsidies", "pensions": "Pensions",
        "health_care": "Health care", "school_reforms": "Schools",
    }

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Politics", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        self._selector = ttk.Combobox(top, state="readonly", width=40)
        self._selector.pack(side="left", padx=10)
        self._selector.bind("<<ComboboxSelected>>", lambda e: self._draw())

        info = tk.Frame(self, bg=PANEL)
        info.pack(fill="x", padx=8, pady=4)
        self._info = tk.Label(info, text="", justify="left", anchor="w", fg=FG, bg=PANEL,
                              font=("Georgia", 10))
        self._info.pack(fill="x", padx=8, pady=4)

        self._reforms_frame = tk.Frame(self, bg=BG)
        self._reforms_frame.pack(fill="x", padx=10, pady=(2, 4))

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig = self.make_figure(charts, "Upper house composition (%)", figsize=(5.6, 4.6))
        self._fig[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._pop_ideology_fig = self.make_figure(charts, "Population ideology (%)", figsize=(5.6, 4.6))
        self._pop_ideology_fig[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        tags = an.country_tags()
        self._tags = tags
        self._selector["values"] = [f"{self._app.country_label(t)} ({t})" for t in tags]
        player_idx = tags.index(an.player) if an.player in tags else 0
        self._selector.current(player_idx)
        self._draw()

    def _draw(self):
        an = self._app.latest()
        if an is None or not hasattr(self, "_tags"):
            return
        idx = self._selector.current()
        if idx < 0:
            return
        tag = self._tags[idx]
        gf = self._app.game_files
        stats = an.country_stats(tag)
        self._info.config(text=(
            f"{self._app.country_label(tag)} — government: {stats.government.replace('_', ' ')}   |   "
            f"prestige {stats.prestige:,.1f}   |   infamy {stats.badboy:.1f}   |   plurality {stats.plurality:.0f}"
        ))
        self._render_reforms(stats.reforms, gf)
        ideol_colors = gf.ideology_colors() if gf is not None else {}

        def _bar_colors(keys):
            return [_hex_color(ideol_colors.get(k, (120, 120, 120))) for k in keys]

        fig, ax, canvas = self._fig
        ax.clear()
        self._style_axes(ax, "Upper house composition (%)")
        if stats.upper_house:
            items = sorted(stats.upper_house.items(), key=lambda kv: -kv[1])
            keys = [k for k, _ in items]
            values = [v * 100 for _, v in items]
            ax.barh([k.replace("_", " ") for k in keys][::-1], values[::-1],
                    color=_bar_colors(keys)[::-1])
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _p: f"{x:.0f}%"))
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(axis="y", length=0)
        fig.subplots_adjust(left=0.22)
        canvas.draw()

        fig, ax, canvas = self._pop_ideology_fig
        ax.clear()
        self._style_axes(ax, "Population ideology (%)")
        pop = an.pop_stats(tag)
        if pop.by_ideology:
            total = sum(pop.by_ideology.values()) or 1.0
            items = sorted(pop.by_ideology.items(), key=lambda kv: -kv[1])
            keys = [k for k, _ in items]
            values = [v / total * 100 for _, v in items]
            ax.barh([k.replace("_", " ") for k in keys][::-1], values[::-1],
                    color=_bar_colors(keys)[::-1])
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _p: f"{x:.0f}%"))
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(axis="y", length=0)
        fig.subplots_adjust(left=0.22)
        canvas.draw()

    def _render_reforms(self, reforms, gf) -> None:
        for child in self._reforms_frame.winfo_children():
            child.destroy()
        if not reforms:
            tk.Label(self._reforms_frame, text="No reforms recorded for this country.",
                     fg=FG, bg=BG, font=("Georgia", 10)).pack(anchor="w")
            return
        order = [k for k in self.REFORM_LABELS if k in reforms]
        max_label = max(len(self.REFORM_LABELS[k]) for k in order)
        for key in order:
            option = reforms[key]
            level = gf.reform_level(key, option) if gf is not None else None
            name = gf.display_name(option) if gf is not None else option.replace("_", " ").title()
            label = self.REFORM_LABELS.get(key, key.replace("_", " ").title())
            row = tk.Frame(self._reforms_frame, bg=BG)
            row.pack(anchor="w")
            tk.Label(row, text=label.ljust(max_label + 2), fg=FG, bg=BG,
                     font=("Georgia", 10, "bold")).pack(side="left")
            tk.Label(row, text=name, fg=reform_color(level), bg=BG,
                     font=("Georgia", 10)).pack(side="left")



class ImmigrationTab(tk.Frame, _ChartMixin):
    TITLE = "Immigration"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        self._snapshot = None
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Immigration", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        self._range_var = tk.StringVar(value="7")
        tk.Label(top, text="Days back from save date:", fg=FG, bg=BG).pack(side="left", padx=(14, 2))
        for days, label in (("1", "Today"), ("7", "Last week"), ("30", "Last month")):
            ttk.Radiobutton(top, text=label, value=days, variable=self._range_var,
                            command=self._draw).pack(side="left", padx=4)

        self._info = tk.Label(self, text="", justify="left", anchor="w", fg=FG, bg=BG,
                              font=("Georgia", 10))
        self._info.pack(fill="x", padx=10, pady=2)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        wrap = tk.Frame(body, bg=BG)
        wrap.pack(side="left", fill="both", expand=True)
        columns = ("province", "owner", "date", "foreign", "total", "share")
        self._tree = ttk.Treeview(wrap, columns=columns, show="tree headings", selectmode="browse")
        self._tree.heading("#0", text="Flag")
        self._tree.column("#0", width=58, minwidth=58, stretch=False, anchor="center")
        headers = {"province": "Destination province", "owner": "Country",
                   "date": "Last arrival", "foreign": "Immigrant stock",
                   "total": "Province pop.", "share": "% foreign"}
        for col in columns:
            self._tree.heading(col, text=headers[col])
            anchor = "center" if col == "share" else "w"
            width = 110 if col == "date" else 120 if col in ("foreign", "total") else 100
            self._tree.column(col, width=width, anchor=anchor)
        self._tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        charts = tk.Frame(body, bg=BG)
        charts.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._fig_country = self.make_figure(charts, "Immigration by country (immigrant stock)", figsize=(5.2, 4.4))
        self._fig_country[2].get_tk_widget().pack(fill="both", expand=True)
        self._fig_culture = self.make_figure(charts, "Biggest diasporas (cumulative emigration)", figsize=(5.2, 4.4))
        self._fig_culture[2].get_tk_widget().pack(fill="both", expand=True)

        self._note = tk.Label(self, text="", justify="left", anchor="w", fg=BUTTON, bg=BG,
                              font=("Georgia", 9, "italic"))
        self._note.pack(fill="x", padx=10, pady=(2, 6))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        self._snapshot = an.migration_snapshot()
        self._draw()

    def _date_within(self, value: str) -> bool:
        days = int(self._range_var.get())
        try:
            vy, vm, vd = (int(x) for x in str(value).split("."))
            sy, sm, sd = (int(x) for x in self._snapshot.date.split("."))
        except (ValueError, TypeError, AttributeError):
            return False
        return (vy, vm, vd) <= (sy, sm, sd) and (vy, vm, vd) >= (sy, sm, sd - days)

    def _draw(self):
        snap = self._snapshot
        if snap is None:
            return
        gf = self._app.game_files
        for item in self._tree.get_children():
            self._tree.delete(item)
        rows = [r for r in snap.destinations if self._date_within(r.date)]
        for row in rows[:60]:
            name = gf.province_name(row.province_id) if gf is not None else f"Province {row.province_id}"
            share = (row.foreign_population / row.total_population * 100) if row.total_population else 0.0
            photo = self._app.flag_photo(row.owner, size=(36, 24))
            self._tree.insert("", "end", image=photo, values=(
                name, self._app.country_label(row.owner),
                row.date.replace(".", "/"), vfmt(row.foreign_population),
                vfmt(row.total_population), f"{share:.0f}%",
            ))
        total_today = sum(r.foreign_population for r in rows)
        self._info.config(text=(
            f"Save date {snap.date.replace('.', '/')} — {len(rows)} provinces received immigrants in the "
            f"selected window; {vfmt(total_today)} people of foreign culture live in them."
        ))
        self._note.config(text=(
            "Victoria II saves only record the date of each province's most recent arrival; "
            "the 'immigrant stock' column counts pops whose culture is not accepted by the owning country."
        ))

        fig, ax, canvas = self._fig_country
        ax.clear()
        self._style_axes(ax, "Immigration by country (immigrant stock)")
        items = snap.immigration_by_country[:10]
        if items:
            labels = [self._app.country_label(t) for t, _ in items][::-1]
            values = [v for _, v in items][::-1]
            ax.barh(labels, values, color=GOLD)
            ax.tick_params(axis="y", length=0, labelsize=8)
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.ticklabel_format(axis="x", useOffset=False, style="plain")
        fig.subplots_adjust(left=0.30)
        canvas.draw()

        fig, ax, canvas = self._fig_culture
        ax.clear()
        self._style_axes(ax, "Biggest diasporas (cumulative emigration)")
        items = snap.emigration_by_culture[:10]
        if items:
            labels = [c.replace("_", " ").capitalize() for c, _ in items][::-1]
            values = [v for _, v in items][::-1]
            ax.barh(labels, values, color="#8a3a2a")
            ax.tick_params(axis="y", length=0, labelsize=8)
            for spine in ("left", "right", "top"):
                ax.spines[spine].set_visible(False)
            ax.ticklabel_format(axis="x", useOffset=False, style="plain")
        fig.subplots_adjust(left=0.30)
        canvas.draw()


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
