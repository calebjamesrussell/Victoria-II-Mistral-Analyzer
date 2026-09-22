"""Tkinter desktop UI for the Victoria II Mistral Analyzer.

The interface deliberately borrows the game's visual feel: flags, country
colors and names are read live from the user's own Victoria II installation
(no assets are bundled with this app).
"""

from __future__ import annotations

import os
import pickle
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
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


BG = "#1e2628"
FG = "#d8cfc0"
ACCENT = "#c9a45c"
PANEL = "#252f31"
PANEL2 = "#2c3a3d"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Victoria II Mistral Analyzer")
        self.geometry("1180x760")
        self.minsize(940, 600)
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
        style.configure("TNotebook.Tab", background=PANEL, foreground=FG, padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", ACCENT)])
        style.configure("Treeview", background=PANEL, foreground=FG, fieldbackground=PANEL, rowheight=22)
        style.configure("Treeview.Heading", background=PANEL2, foreground=ACCENT)
        style.map("Treeview", background=[("selected", PANEL2)])
        style.configure("TButton", background=PANEL2, foreground=FG, padding=(10, 4))
        style.map("TButton", background=[("active", "#37474a")])
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Status.TLabel", background=PANEL, foreground=FG)
        style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=("Georgia", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=FG, font=("Georgia", 10, "italic"))

    # ----------------------------------------------------------- toolbar

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=0, pady=0)
        self._install_label = tk.Label(bar, text="No Victoria II installation selected", fg=FG, bg=PANEL)
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
        for tab in (WarsTab, PopulationTab, EconomyTab, PoliticsTab, CompareTab):
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
        # Load the three most recent saves automatically.
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
        for name in ("WarsTab", "PopulationTab", "EconomyTab", "PoliticsTab", "CompareTab"):
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
        img = self.game_files.flag_image(tag, size=size)
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


class WelcomeTab(tk.Frame):
    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        inner = tk.Frame(self, bg=BG)
        inner.pack(expand=True)
        tk.Label(inner, text="Victoria II Mistral Analyzer", font=("Georgia", 30, "bold"), fg=ACCENT, bg=BG).pack(pady=(60, 4))
        tk.Label(inner, text="War, economy and population analytics for your Heart of Darkness saves.", font=("Georgia", 12, "italic"), fg=FG, bg=BG).pack(pady=4)
        tk.Label(inner, text="", bg=BG).pack(pady=10)
        body = (
            "1. Point the toolbar at your Victoria II installation (auto-detected on most systems).\n"
            "2. Load one or more .v2 save games.\n"
            "3. Explore wars & battles, population, economy and politics tabs.\n"
            "4. Load several saves from the same campaign to see change over time in Compare.\n\n"
            "All names, flags and colors are read from your own game installation at runtime;\n"
            "this app bundles no Paradox Interactive assets."
        )
        tk.Label(inner, text=body, justify="left", font=("Georgia", 11), fg=FG, bg=BG).pack(pady=8)

    def refresh(self):
        pass


class WarsTab(tk.Frame):
    TITLE = "Wars & Battles"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        self._build()
        app.bind_analyzer_hook = None

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Wars & Battles", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")

        columns = ("war", "dates", "attacker", "defender", "battles", "losses_a", "losses_d")
        headers = {"war": "War", "dates": "Dates", "attacker": "Attacker(s)", "defender": "Defender(s)",
                    "battles": "Battles", "losses_a": "Att. losses", "losses_d": "Def. losses"}
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=8, pady=4)
        self._tree = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            self._tree.heading(col, text=headers[col])
            self._tree.column(col, width=180 if col in ("war", "attacker", "defender") else 90, anchor="w")
        self._tree.column("war", width=280)
        self._tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select_war)

        detail = tk.Frame(self, bg=PANEL)
        detail.pack(fill="x", padx=8, pady=(4, 10))
        self._detail_label = tk.Label(detail, text="Select a war to see its battles.", justify="left", anchor="w", fg=FG, bg=PANEL, font=("Georgia", 10))
        self._detail_label.pack(fill="x", padx=8, pady=6)

    def refresh(self):
        an = self._app.latest()
        for item in self._tree.get_children():
            self._tree.delete(item)
        if an is None:
            return
        self._wars = an.wars()
        self._war_items = []
        for counter, war in enumerate(sorted(self._wars, key=lambda w: w.start_date or "", reverse=True)):
            losses_a = sum(b.attacker_losses for b in war.battles)
            losses_d = sum(b.defender_losses for b in war.battles)
            item = f"war{counter}"
            self._war_items.append((item, war))
            self._tree.insert("", "end", iid=item, values=(
                war.name,
                f"{(war.start_date or '?').replace('.', '/')} – {(war.end_date or '?').replace('.', '/')}",
                ", ".join(self._app.country_label(t) for t in war.attackers) or war.original_attacker,
                ", ".join(self._app.country_label(t) for t in war.defenders) or war.original_defender,
                len(war.battles),
                losses_a,
                losses_d,
            ))

    def _on_select_war(self, _event=None):
        selection = self._tree.selection()
        if not selection or not hasattr(self, "_wars"):
            return
        war = next(w for item, w in self._war_items if item == selection[0])
        if not war.battles:
            self._detail_label.config(text="No recorded battles.")
            return
        biggest = sorted(war.battles, key=lambda b: b.total_losses, reverse=True)[:5]
        lines = [f"{war.name} — {len(war.battles)} battles, deadliest:", ""]
        for b in biggest:
            lines.append(
                f"  {b.date.replace('.', '/')} {b.name}: {self._app.country_label(b.attacker)} vs "
                f"{self._app.country_label(b.defender)} — losses {b.attacker_losses:,} vs {b.defender_losses:,}"
                f" ({'attacker' if b.attacker_won else 'defender'} won)"
            )
        lines.append("")
        lines.append(f"Total recorded losses: attacker {war.attacker_losses:,} / defender {war.defender_losses:,}")
        self._detail_label.config(text="\n".join(lines))


class _ChartMixin:
    def make_figure(self, parent, title: str):
        fig = Figure(figsize=(6, 4), dpi=100, facecolor=PANEL)
        ax = fig.add_subplot(111)
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title(title, color=ACCENT)
        canvas = FigureCanvasTkAgg(fig, master=parent)
        return fig, ax, canvas


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
        self._info = tk.Label(info, text="", justify="left", anchor="w", fg=FG, bg=PANEL, font=("Georgia", 10))
        self._info.pack(fill="x", padx=8, pady=6)

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig_left = self.make_figure(charts, "Population by type")
        self._fig_left[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._fig_right = self.make_figure(charts, "Literacy / militancy / consciousness")
        self._fig_right[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        tags = an.country_tags()
        labels = {t: self._app.country_label(t) for t in tags}
        self._tags = tags
        self._selector["values"] = [f"{labels[t]} ({t})" for t in tags]
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
        pop = an.pop_stats(tag)
        self._info.config(text=(
            f"{self._app.country_label(tag)} — total population {pop.size:,}   |   "
            f"literacy {pop.literacy:.1%}   |   avg militancy {pop.militancy:.2f}   |   "
            f"avg consciousness {pop.consciousness:.2f}"
        ))
        fig, ax, canvas = self._fig_left
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("Population by type", color=ACCENT)
        if pop.by_type:
            items = sorted(pop.by_type.items(), key=lambda kv: -kv[1])
            ax.barh([k for k, _ in items][::-1], [v for _, v in items][::-1], color=ACCENT)
        canvas.draw()
        fig, ax, canvas = self._fig_right
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("Literacy / militancy / consciousness", color=ACCENT)
        metrics = ("Literacy %", "Avg militancy", "Avg consciousness")
        values = [pop.literacy * 100, pop.militancy, pop.consciousness]
        ax.bar(metrics, values, color=["#7da87b", "#b0654f", "#6d8fa3"])
        canvas.draw()


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

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig_left = self.make_figure(charts, "Budget: income vs expenses")
        self._fig_left[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._fig_right = self.make_figure(charts, "World market pool")
        self._fig_right[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

        self._info = tk.Label(self, text="", justify="left", anchor="w", fg=FG, bg=BG, font=("Georgia", 10))
        self._info.pack(fill="x", padx=10, pady=2)

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
        econ = an.country_economy(tag)
        stats = an.country_stats(tag)
        net = sum(econ["incomes"].values()) - sum(econ["expenses"].values())
        self._info.config(text=(
            f"{self._app.country_label(tag)} — treasury £{econ['money']:,.0f}   |   "
            f"factories {stats.factories} (level {stats.factory_levels}, {stats.factory_workers:,} workers)   |   "
            f"daily balance £{net:+,.0f}"
        ))
        fig, ax, canvas = self._fig_left
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("Budget: income vs expenses", color=ACCENT)
        inc = sum(econ["incomes"].values())
        exp = sum(econ["expenses"].values())
        ax.bar(["Income", "Expenses"], [inc, exp], color=["#7da87b", "#b0654f"])
        canvas.draw()

        fig, ax, canvas = self._fig_right
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("World market pool", color=ACCENT)
        market = an.world_market()
        items = sorted(market.items(), key=lambda kv: kv[1], reverse=True)[:12]
        if items:
            ax.barh([k.replace("_", " ") for k, _ in items][::-1],
                    [v for _, v in items][::-1], color="#c9a45c")
        canvas.draw()


class PoliticsTab(tk.Frame, _ChartMixin):
    TITLE = "Politics"

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
        self._info = tk.Label(info, text="", justify="left", anchor="w", fg=FG, bg=PANEL, font=("Georgia", 10))
        self._info.pack(fill="x", padx=8, pady=6)

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig = self.make_figure(charts, "Upper house composition")
        self._fig[2].get_tk_widget().pack(fill="both", expand=True)
        self._pop_ideology_fig = self.make_figure(charts, "Population ideology")
        self._pop_ideology_fig[2].get_tk_widget().pack(fill="both", expand=True)

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
        stats = an.country_stats(tag)
        reforms = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(stats.reforms.items())) or "none recorded"
        self._info.config(text=(
            f"{self._app.country_label(tag)} — government: {stats.government.replace('_', ' ')}   |   "
            f"prestige {stats.prestige:,.1f}   |   infamy {stats.badboy:.1f}   |   plurality {stats.plurality:.0f}\n"
            f"Reforms — {reforms}"
        ))
        fig, ax, canvas = self._fig
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("Upper house composition", color=ACCENT)
        if stats.upper_house:
            items = sorted(stats.upper_house.items(), key=lambda kv: -kv[1])
            ax.barh([k.replace("_", " ") for k, _ in items][::-1],
                    [v for _, v in items][::-1], color="#6d8fa3")
        canvas.draw()
        fig, ax, canvas = self._pop_ideology_fig
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=FG)
        for spine in ax.spines.values():
            spine.set_color(FG)
        ax.set_title("Population ideology", color=ACCENT)
        pop = an.pop_stats(tag)
        if pop.by_ideology:
            items = sorted(pop.by_ideology.items(), key=lambda kv: -kv[1])
            ax.barh([k.replace("_", " ") for k, _ in items][::-1],
                    [v for _, v in items][::-1], color="#b0654f")
        canvas.draw()


class CompareTab(tk.Frame, _ChartMixin):
    TITLE = "Compare (over time)"

    def __init__(self, app: App):
        super().__init__(app, bg=BG)
        self._app = app
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Campaign over time", font=("Georgia", 16, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(top, text="Load multiple saves of the same campaign to plot change over time.", fg=FG, bg=BG).pack(side="left", padx=12)
        self._selector = ttk.Combobox(top, state="readonly", width=40)
        self._selector.pack(side="left", padx=10)
        self._selector.bind("<<ComboboxSelected>>", lambda e: self._draw())

        charts = tk.Frame(self, bg=BG)
        charts.pack(fill="both", expand=True, padx=8, pady=6)
        self._fig_pop = self.make_figure(charts, "Population")
        self._fig_pop[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._fig_prestige = self.make_figure(charts, "Prestige")
        self._fig_prestige[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=4)
        self._fig_money = self.make_figure(charts, "Treasury")
        self._fig_money[2].get_tk_widget().pack(side="left", fill="both", expand=True, padx=(4, 0))

    def refresh(self):
        an = self._app.latest()
        if an is None:
            return
        tags = an.country_tags()
        self._tags = tags
        self._selector["values"] = [f"{self._app.country_label(t)} ({t})" for t in tags]
        if an.player in tags:
            self._selector.current(tags.index(an.player))
        self._draw()

    def _draw(self):
        analyzers = [a for a in self._app.analyzers.values()]
        if not analyzers or not hasattr(self, "_tags"):
            return
        idx = self._selector.current()
        if idx < 0:
            return
        tag = self._tags[idx]
        ordered = sorted(analyzers, key=lambda a: a.date)

        pops, prestige, money, dates = [], [], [], []
        for an in ordered:
            stats = an.country_stats(tag)
            pop = an.pop_stats(tag)
            pops.append(pop.size)
            prestige.append(stats.prestige)
            money.append(stats.money)
            dates.append(an.date.replace(".", "/"))

        for (fig, ax, canvas), values, title in (
            (self._fig_pop, pops, "Population"),
            (self._fig_prestige, prestige, "Prestige"),
            (self._fig_money, money, "Treasury"),
        ):
            ax.clear()
            ax.set_facecolor(PANEL)
            ax.tick_params(colors=FG)
            for spine in ax.spines.values():
                spine.set_color(FG)
            ax.set_title(f"{title} — {self._app.country_label(tag)}", color=ACCENT)
            if len(dates) > 1:
                ax.plot(dates, values, marker="o", color=ACCENT)
            elif dates:
                ax.bar(dates, values, color=ACCENT)
            canvas.draw()


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
