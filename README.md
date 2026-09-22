# Victoria II Mistral Analyzer

A desktop app that analyzes **Victoria II: Heart of Darkness** (and A House
Divided) save games — wars, battles, economy, population, politics — and
tracks change over time across multiple saves of a campaign, showing you
things the game's own ledger doesn't.

Built with Mistral AI.

![Windows build](https://github.com/calebjamesrussell/Victoria-II-Mistral-Analyzer/actions/workflows/build-windows.yml/badge.svg)

## What it shows

- **Welcome map** — a world map drawn from the save itself: every owned
  province colored by its owner's country color (read from your install),
  with your own country highlighted in gold.
- **Wars & Battles** — every war in the save's history with all recorded
  battles: dates, locations, forces committed, losses per side (sortable
  columns, period-separated numbers) and flag chips for every attacker and
  defender.
- **Population** — total population, literacy, militancy and consciousness
  for any country, broken down by pop type (with the game's own pop icons
  on the chart), culture and religion, plus the wealthiest and poorest
  POPs and the issues the population cares about most.
- **Economy** — treasury, factories and daily income by category, each
  good's share of world production, and what your country is best at
  (world leadership highlights).
- **Politics** — upper house and population ideology in % with the game's
  own ideology colors, reforms line by line and colored from red (worst)
  to green (best), government type, prestige, infamy, plurality.
- **Immigration** — for the save's current date: which provinces are
  receiving immigrants right now (with the country's flag), immigration
  hot spots by country, and the biggest diasporas by cumulative emigration.

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

### Windows (prebuilt)

Go to the repo's [**Releases** page](https://github.com/calebjamesrussell/Victoria-II-Mistral-Analyzer/releases)
and download `vic2-analyzer-windows.zip` from the **Latest build** entry —
a portable, self-contained distribution built by PyInstaller. Unzip
anywhere and run `vic2-analyzer.exe`. No Python install needed.

The latest build always reflects the current `main` branch; each release
also lists the commit it was built from.

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

This project is an unofficial fan tool. It **contains and distributes no
Paradox Interactive assets** — no game files, art, flags, music or other
copyrighted material are bundled in this repository or in the released
downloads. All country names, flags and colors are read live from the
user's own Victoria II installation at runtime.

"Victoria II" and "Paradox Interactive" are trademarks of Paradox
Interactive AB. This project is not affiliated with, endorsed by, or
sponsored by Paradox Interactive, and is not an official product. The use
of the game's name here is purely descriptive, to identify the save-game
format this tool reads. Victoria II is © Paradox Interactive AB.

If you are the trademark holder and have any concerns, please open an
issue in this repository and it will be addressed promptly.

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
