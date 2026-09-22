"""Reads reference data from the user's Victoria II installation.

Nothing in this module ships game assets: everything is read from the
install directory at runtime (localisation CSVs, country colors, flags,
province definitions).  Supports A House Divided and Heart of Darkness.
"""

from __future__ import annotations

import csv
import glob
import io
import os
import struct
from typing import Dict, List, Optional

from PIL import Image

__all__ = ["GameFiles"]


def _open_enc(path: str):
    return open(path, "r", encoding="cp1252", errors="replace", newline="")


class GameFiles:
    """Lazy reader for Victoria II install reference data."""

    def __init__(self, install_dir: str):
        self.install_dir = install_dir
        self._localisation: Optional[Dict[str, str]] = None
        self._country_names: Optional[Dict[str, str]] = None
        # province id -> (name, r, g, b)
        self._provinces: Optional[Dict[int, tuple]] = None
        # tag -> (r, g, b)
        self._country_colors: Optional[Dict[str, tuple]] = None
        self._good_names: Optional[Dict[str, str]] = None
        self._cache_flags: Dict[str, Image.Image] = {}
        self._gov_flag_types: Optional[Dict[str, str]] = None
        self._pop_icons: Optional[Dict[str, Image.Image]] = None
        self._pop_sprite_map: Optional[Dict[str, int]] = None
        self._reform_options: Optional[Dict[str, List[str]]] = None
        self._issue_options: Optional[List[str]] = None
        self._pop_issue_names: Optional[Dict[str, str]] = None
        self._ideology_colors: Optional[Dict[str, tuple]] = None
        self._province_positions: Optional[Dict[int, tuple]] = None

    # ------------------------------------------------------------------ paths

    def _game_subdir(self, *parts: str) -> str:
        return os.path.join(self.install_dir, *parts)

    def province_definition_path(self) -> str:
        return self._game_subdir("map", "definition.csv")

    def localisation_files(self):
        """Localisation CSVs, HoD first (3.03/3.04 override older keys)."""
        base = self._game_subdir("localisation")
        if not os.path.isdir(base):
            return []
        paths = glob.glob(os.path.join(base, "*.csv"))
        def sort_key(p: str):
            name = os.path.basename(p).lower()
            # older files first so newer override them
            order = {"text.csv": 0, "v2_1.1.csv": 1, "darkness_3_03.csv": 9, "darkness_3_04.csv": 10}
            for key, rank in order.items():
                if name == key:
                    return rank
            return 5
        return sorted(paths, key=sort_key)

    # ---------------------------------------------------------- localisation

    def localisation(self) -> Dict[str, str]:
        """All key -> English text pairs from localisation CSVs."""
        if self._localisation is None:
            table: Dict[str, str] = {}
            for path in self.localisation_files():
                try:
                    with _open_enc(path) as fh:
                        for row in csv.reader(fh, delimiter=";"):
                            if not row:
                                continue
                            key = row[0].strip()
                            if not key or key.startswith("#"):
                                continue
                            value = row[1].strip() if len(row) > 1 else ""
                            if value:
                                table[key] = value
                except OSError:
                    continue
            self._localisation = table
        return self._localisation

    def country_names(self) -> Dict[str, str]:
        """Tag (e.g. GEO) -> display name."""
        if self._country_names is None:
            table: Dict[str, str] = {}
            loc = self.localisation()
            # country names live under keys like "GEO" in text.csv?  Victoria 2
            # actually uses explicit per-country keys in the localisation of
            # common/countries/*.txt ("graphical_culture" etc.), but display
            # names are in localisation as the tag itself.
            countries_txt = self._game_subdir("common", "countries.txt")
            tags = []
            if os.path.isfile(countries_txt):
                with _open_enc(countries_txt) as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        tag = line.split("=")[0].strip().split()[0]
                        if tag:
                            tags.append(tag)
            for tag in tags:
                for candidate in (tag, tag.upper()):
                    if candidate in loc:
                        table[tag] = loc[candidate]
                        break
            self._country_names = table
        return self._country_names

    def good_names(self) -> Dict[str, str]:
        """Internal good name (e.g. small_arms) -> display name."""
        if self._good_names is None:
            loc = self.localisation()
            table: Dict[str, str] = {}
            for good in KNOWN_GOODS:
                table[good] = loc.get(good, good.replace("_", " ").title())
            self._good_names = table
        return self._good_names

    # ------------------------------------------------------------- provinces

    def provinces(self) -> Dict[int, tuple]:
        """Province id -> (name, r, g, b) from map/definition.csv."""
        if self._provinces is None:
            table: Dict[int, tuple] = {}
            path = self.province_definition_path()
            if os.path.isfile(path):
                with _open_enc(path) as fh:
                    reader = csv.reader(fh, delimiter=";")
                    for row in reader:
                        if len(row) < 4:
                            continue
                        try:
                            pid = int(row[0].strip())
                            r, g, b = (int(row[1]), int(row[2]), int(row[3]))
                        except ValueError:
                            continue
                        name = row[4].strip() if len(row) > 4 else ""
                        table[pid] = (name, r, g, b)
            self._provinces = table
        return self._provinces

    def province_name(self, province_id: int) -> str:
        info = self.provinces().get(int(province_id))
        return info[0] if info else f"Province {province_id}"

    # --------------------------------------------------------------- colors

    def country_colors(self) -> Dict[str, tuple]:
        """Tag (e.g. GEO) -> (r, g, b) from common/countries.txt + country files."""
        if self._country_colors is None:
            import re
            table: Dict[str, tuple] = {}
            color_re = re.compile(r"color\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}")
            countries_txt = self._game_subdir("common", "countries.txt")
            if os.path.isfile(countries_txt):
                try:
                    with _open_enc(countries_txt) as fh:
                        for line in fh:
                            line = line.strip()
                            if "=" not in line or '"' not in line:
                                continue
                            tag = line.split("=")[0].strip()
                            rel = line.split('"')[1]
                            path = self._game_subdir("common", *rel.split("/"))
                            if not os.path.isfile(path):
                                continue
                            try:
                                with _open_enc(path) as fh:
                                    m = color_re.search(fh.read())
                            except OSError:
                                continue
                            if m and tag:
                                table[tag] = tuple(int(c) for c in m.groups())
                except OSError:
                    pass
            if not table:
                pattern = self._game_subdir("common", "countries", "*.txt")
                for path in glob.glob(pattern):
                    tag = os.path.basename(path)[: -len(".txt")]
                    try:
                        with _open_enc(path) as fh:
                            m = color_re.search(fh.read())
                    except OSError:
                        continue
                    if m:
                        table[tag] = tuple(int(c) for c in m.groups())
            self._country_colors = table
        return self._country_colors

    def country_color(self, tag: str, fallback=(120, 120, 120)) -> tuple:
        return self.country_colors().get(tag, fallback)

    # ---------------------------------------------------------------- flags

    def government_flag_types(self) -> Dict[str, str]:
        """Map government name (e.g. absolute_monarchy) -> flag suffix."""
        if self._gov_flag_types is None:
            table: Dict[str, str] = {}
            path = self._game_subdir("common", "governments.txt")
            if os.path.isfile(path):
                import re
                try:
                    with _open_enc(path) as fh:
                        text = fh.read()
                    for match in re.finditer(r"([a-z_]+)\s*=\s*\{", text):
                        gov_name = match.group(1)
                        brace = 1
                        pos = match.end()
                        while pos < len(text) and brace:
                            if text[pos] == "{":
                                brace += 1
                            elif text[pos] == "}":
                                brace -= 1
                            pos += 1
                        block = text[match.end():pos]
                        m = re.search(r"flagType\s*=\s*([A-Za-z_]+)", block)
                        if m:
                            table[gov_name] = m.group(1).lower()
                except OSError:
                    pass
            self._gov_flag_types = table
        return self._gov_flag_types

    def flag_path(self, tag: str, government: Optional[str] = None) -> Optional[str]:
        """Best flag .tga for a tag, honouring government variants."""
        base = self._game_subdir("gfx", "flags")
        if not os.path.isdir(base):
            return None
        if government:
            suffix = self.government_flag_types().get(str(government))
            if suffix:
                p = os.path.join(base, f"{tag}_{suffix}.tga")
                if os.path.isfile(p):
                    return p
        p = os.path.join(base, f"{tag}.tga")
        return p if os.path.isfile(p) else None

    def flag_image(self, tag: str, government: Optional[str] = None,
                   size: tuple = (64, 42)) -> Optional[Image.Image]:
        """Flag as an RGBA PIL image, or None if unavailable."""
        key = (tag, government, size)
        if key in self._cache_flags:
            return self._cache_flags[key]
        path = self.flag_path(tag, government)
        img = None
        if path:
            try:
                img = Image.open(path).convert("RGBA")
                if img.size != tuple(size):
                    img = img.resize(size, Image.LANCZOS)
            except (OSError, struct.error):
                img = None
        self._cache_flags[key] = img
        return img


    # ------------------------------------------------------------- pop icons

    def pop_sprite_map(self) -> Dict[str, int]:
        """Pop type name -> sprite index, from the install's poptypes/*.txt."""
        if self._pop_sprite_map is None:
            table: Dict[str, int] = {}
            import re
            pattern = self._game_subdir("poptypes", "*.txt")
            for path in glob.glob(pattern):
                ptype = os.path.basename(path)[: -len(".txt")]
                try:
                    with _open_enc(path) as fh:
                        m = re.search(r"sprite\s*=\s*(\d+)", fh.read())
                except OSError:
                    continue
                if m:
                    table[ptype] = int(m.group(1))
            self._pop_sprite_map = table
        return self._pop_sprite_map

    # --------------------------------------------------- reforms & issues

    def reform_options(self) -> Dict[str, List[str]]:
        """Reform name -> ordered option list (worst -> best), from issues.txt."""
        if self._reform_options is None:
            table: Dict[str, List[str]] = {}
            path = self._game_subdir("common", "issues.txt")
            if os.path.isfile(path):
                import re
                try:
                    with _open_enc(path) as fh:
                        text = fh.read()
                except OSError:
                    text = ""
                for section in ("political_reforms", "social_reforms",
                                "economic_reforms", "military_reforms"):
                    m = re.search(section + r"\s*=\s*\{", text)
                    if not m:
                        continue
                    start = m.end()
                    depth = 1
                    pos = start
                    while pos < len(text) and depth:
                        if text[pos] == "{":
                            depth += 1
                        elif text[pos] == "}":
                            depth -= 1
                        pos += 1
                    block = text[start:pos]
                    # reform keys are indented with a single tab; options
                    # with two.  Walk the block line by line.
                    current_reform = None
                    for line in block.splitlines():
                        m2 = re.match(r"\t([a-z_0-9]+)\s*=\s*\{\s*$", line)
                        if m2:
                            current_reform = m2.group(1)
                            table.setdefault(current_reform, [])
                            continue
                        m3 = re.match(r"\t\t([a-z_0-9]+)\s*=\s*\{", line)
                        if m3 and current_reform:
                            table[current_reform].append(m3.group(1))
            self._reform_options = table
        return self._reform_options

    def reform_level(self, reform: str, option: str) -> Optional[float]:
        """0.0 (worst) .. 1.0 (best) for a reform option; None if unknown."""
        opts = self.reform_options().get(reform)
        if not opts or option not in opts:
            return None
        return opts.index(option) / (len(opts) - 1)

    def issue_options(self) -> List[str]:
        """All issue options in save-file order (index + 1 = numeric id).

        Saves store pop issues as numeric ids (``issues = {14=7.8 15=6.1 ...}``);
        the engine numbers every option from ``common/issues.txt`` in file
        order: the 17 party-issue options first, then political reform
        options, then social reform options (1..80 in Heart of Darkness).
        """
        if self._issue_options is None:
            import re
            options: List[str] = []
            path = self._game_subdir("common", "issues.txt")
            if os.path.isfile(path):
                try:
                    with _open_enc(path) as fh:
                        lines = fh.read().splitlines()
                except OSError:
                    lines = []
                section = False
                current_issue = None
                for line in lines:
                    if line.startswith("economic_reforms") or line.startswith("military_reforms"):
                        section = False
                        current_issue = None
                        continue
                    if re.match(r"(party_issues|political_reforms|social_reforms)\s*=\s*\{", line):
                        section = True
                        current_issue = None
                        continue
                    if section and line.startswith("}"):
                        section = False
                        current_issue = None
                        continue
                    m = re.match(r"\t([a-z_0-9]+)\s*=\s*\{", line)
                    if m:
                        current_issue = m.group(1)
                        continue
                    m = re.match(r"\t\t([a-z_0-9]+)\s*=\s*\{", line)
                    if m and current_issue:
                        options.append(m.group(1))
            self._issue_options = options
        return self._issue_options

    def pop_issue_names(self) -> Dict[str, str]:
        """Numeric issue id ("14") -> localised display name ("Jingoism")."""
        if self._pop_issue_names is None:
            loc = self.localisation()
            table: Dict[str, str] = {}
            for idx, option in enumerate(self.issue_options(), start=1):
                table[str(idx)] = loc.get(option, option.replace("_", " ").title())
            self._pop_issue_names = table
        return self._pop_issue_names

    def display_name(self, key: str) -> str:
        """Localised display name for any game key, prettified as fallback."""
        if self._localisation is not None and key in self._localisation:
            return self._localisation[key]
        return self.localisation().get(key, key.replace("_", " ").title())

    def ideology_colors(self) -> Dict[str, tuple]:
        """Ideology name -> (r, g, b) from common/ideologies.txt."""
        if self._ideology_colors is None:
            import re
            table: Dict[str, tuple] = {}
            path = self._game_subdir("common", "ideologies.txt")
            if os.path.isfile(path):
                try:
                    with _open_enc(path) as fh:
                        text = fh.read()
                    for m in re.finditer(r"\n\t([a-z_]+)\s*=\s*\{", text):
                        name = m.group(1)
                        cm = re.search(r"color\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)",
                                       text[m.end():m.end() + 400])
                        if cm:
                            table[name] = tuple(int(c) for c in cm.groups())
                except OSError:
                    pass
            self._ideology_colors = table
        return self._ideology_colors

    # ----------------------------------------------------------------- map

    def province_positions(self) -> Dict[int, tuple]:
        """Province id -> (x, y) pixel position from map/positions.txt."""
        if self._province_positions is None:
            import re
            table: Dict[int, tuple] = {}
            path = self._game_subdir("map", "positions.txt")
            if os.path.isfile(path):
                try:
                    with _open_enc(path) as fh:
                        text = fh.read()
                    for m in re.finditer(r"(?m)^(\d+)\s*=\s*\{\s*unit=\s*\{\s*x=([\d.]+)\s*y=([\d.]+)", text):
                        table[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
                except OSError:
                    pass
            self._province_positions = table
        return self._province_positions

    def map_size(self) -> tuple:
        """(width, height) of the game map in pixels, from default.map."""
        path = self._game_subdir("map", "default.map")
        if os.path.isfile(path):
            try:
                with _open_enc(path) as fh:
                    text = fh.read()
            except OSError:
                return (5616, 2160)
            import re
            wm = re.search(r"width\s*=\s*(\d+)", text)
            hm = re.search(r"height\s*=\s*(\d+)", text)
            if wm and hm:
                return (int(wm.group(1)), int(hm.group(1)))
        return (5616, 2160)

    def pop_icon(self, pop_type: str, size: tuple = (24, 24)) -> Optional[Image.Image]:
        """The game's own pop-type icon, read from gfx/interface/pops_small.dds.

        The sheet is a single strip of 12 frames (32px wide); the game maps
        pop types to frames via ``sprite = N`` in ``poptypes/*.txt``.
        """
        key = (pop_type, size)
        if self._pop_icons is not None and key in self._pop_icons:
            return self._pop_icons[key]
        if self._pop_icons is None:
            self._pop_icons = {}
        sprite_index = self.pop_sprite_map().get(pop_type)
        if sprite_index is None:
            return None
        sheet_path = self._game_subdir("gfx", "interface", "pops_small.dds")
        if not os.path.isfile(sheet_path):
            return None
        try:
            sheet = Image.open(sheet_path).convert("RGBA")
        except (OSError, ValueError):
            return None
        frame_width = sheet.width // 12
        frame = sheet.crop((sprite_index * frame_width, 0,
                            (sprite_index + 1) * frame_width, 32))
        if frame.size != tuple(size):
            frame = frame.resize(size, Image.LANCZOS)
        self._pop_icons[key] = frame
        return frame


KNOWN_GOODS = [
    "ammunition", "small_arms", "artillery", "canned_food", "aeroplanes",
    "cotton", "dye", "wool", "silk", "coal", "sulphur", "iron", "timber",
    "tropical_wood", "rubber", "oil", "precious_metal", "steel", "cement",
    "machine_parts", "glass", "fuel", "fertilizer", "explosives",
    "clipper_convoy", "steamer_convoy", "electric_gear", "telephones",
    "radio", "automobiles", "tanks", "airplanes", "luxury_clothes",
    "luxury_furniture", "furniture", "clothes", "fabric", "paper",
    "liquor", "wine", "tobacco", "opium", "tea", "coffee", "sugar", "fruit",
    "grain", "cattle", "fish", "ore", "coal", "industrial_rail_units",
]
