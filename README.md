# Victoria II Mistral Analyzer

A desktop app that analyzes **Victoria II: Heart of Darkness** (and A House
Divided) save games — wars, battles, economy, population, politics — and
tracks change over time across multiple saves of a campaign, showing you
things the game's own ledger doesn't.

Built with Mistral AI.

![Windows build](https://github.com/calebjamesrussell/Victoria-II-Mistral-Analyzer/actions/workflows/build-windows.yml/badge.svg)

## What it shows

- **Wars & Battles** — every war in the save's history with all recorded
  battles: dates, locations, leaders, forces committed, losses per side,
  and the deadliest engagements.
- **Population** — total population, literacy, militancy and consciousness
  for any country, broken down by pop type, culture and religion.
- **Economy** — treasury, daily income vs. expenses, factory count/levels/
  workforce, and the world market pool of all goods.
- **Politics** — upper house composition, population ideology, reforms,
  government type, prestige, infamy, plurality.
- **Compare (over time)** — load several saves from the same campaign and
  plot population, prestige and treasury across the whole campaign.

## Quick start (from source)

Requires Python 3.9+ with Tkinter (included with the Windows python.org
installer).

```
pip install pillow matplotlib
python run_analyzer.py
```

On first launch the app auto-detects your Victoria II installation (Windows
registry, Steam and GOG locations; Linux/macOS Steam paths) and lists the
save games in your Paradox Documents folder. You can also pick the install
folder manually, and add `.v2` files from anywhere.

### Windows installer (prebuilt)

Go to the repo's **Actions** tab → **Build Windows exe** → latest run →
artifacts: a portable, self-contained `vic2-analyzer-windows.zip` built by
PyInstaller. Unzip anywhere and run `vic2-analyzer.exe`. No Python install
needed.

## Using it

1. Launch the app; it tries to find your install and recent saves by itself.
2. If needed, click **Choose install…** and select your `Victoria 2` folder.
3. The three most recent saves in your save games folder are loaded
   automatically (parse takes a few seconds each). Add more with
   **Add save file…**.
4. Switch between the tabs and use the country selector on each tab.

Save parsing is read-only; the app never modifies your saves or the game
installation.

## Intellectual property

This project is a fan tool. It **contains no Paradox Interactive assets**.
All country names, flags and colors are read live from the user's own
Victoria II installation at runtime. Victoria II is © Paradox Interactive;
this project is not affiliated with or endorsed by Paradox Interactive.

## Development

```
pip install pillow matplotlib pytest
python -m pytest tests/
```

Tests include a full parser suite and integration tests that run against a
real save file when the `VIC2_TEST_SAVE` environment variable is set:

```
VIC2_TEST_SAVE="C:/path/to/Georgia1903.v2" VIC2_TEST_INSTALL="C:/Games/Victoria 2" python -m pytest
```

### Project layout

- `vic2analyzer/parser.py` — Clausewitz `.v2` text-format parser
- `vic2analyzer/analyzer.py` — wars/battles, population, economy, politics datasets
- `vic2analyzer/gamefiles.py` — reads localisation, flags, colors from the install
- `vic2analyzer/discovery.py` — install auto-detection and save-game discovery
- `vic2analyzer/gui.py` — Tkinter UI (dark "game ledger" theme)
- `run_analyzer.py` — entry point
- `vic2-analyzer.spec` — PyInstaller packaging spec

## License

MIT — see [LICENSE](LICENSE).
