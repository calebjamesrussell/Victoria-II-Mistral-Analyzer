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
from typing import Dict, Optional

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
        """Tag -> (r, g, b) from common/countries/*.txt color entries."""
        if self._country_colors is None:
            table: Dict[str, tuple] = {}
            pattern = self._game_subdir("common", "countries", "*.txt")
            import re
            color_re = re.compile(r"color\s*=\s*\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}")
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

    def flag_path(self, tag: str, government: Optional[str] = None) -> Optional[str]:
        """Best flag .tga for a tag, honouring government variants.

        The save's ``government`` field is numeric; we map the common numeric
        governments to the flag suffixes the game uses.
        """
        base = self._game_subdir("gfx", "flags")
        if not os.path.isdir(base):
            return None
        suffixes = []
        if government:
            gov = str(government).lower()
            govmap = {
                "absolute_monarchy": "monarchy",
                "prussian_constitutionalism": "monarchy",
                "hms_government": "monarchy",
                "democracy": "republic",
                "presidential_dictatorship": "republic",
                "proletarian_dictatorship": "communist",
                "bourgeois_dictatorship": "republic",
                "fascist_dictatorship": "fascist",
                "anarcho_liberal": "republic",
            }
            suffix = govmap.get(gov)
            if suffix:
                suffixes.append(suffix)
        for suffix in suffixes:
            for name in (f"{tag}_{suffix}.tga",):
                p = os.path.join(base, name)
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
