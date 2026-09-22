"""Analysis layer over a parsed Victoria II save game.

Turns the raw parser tree into concrete, UI-ready datasets:

* wars and battles (from ``previous_war`` history blocks),
* population per country (from province pop blocks),
* economy (budget, factories, world market pool),
* politics (upper house, reforms, ruling party),
* technology progress.

Everything here reads *parsed save data only*; display names and colors
come from a :class:`~vic2analyzer.gamefiles.GameFiles` at UI time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = ["SaveAnalyzer", "Battle", "War", "CountryStats", "PopBreakdown"]


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first(value, default=None):
    items = _as_list(value)
    return items[0] if items else default


@dataclass
class Battle:
    date: str
    war_name: str
    name: str
    location: int
    attacker: str
    defender: str
    attacker_leader: str
    defender_leader: str
    attacker_forces: int
    defender_forces: int
    attacker_losses: int
    defender_losses: int
    attacker_won: bool

    @property
    def total_forces(self) -> int:
        return self.attacker_forces + self.defender_forces

    @property
    def total_losses(self) -> int:
        return self.attacker_losses + self.defender_losses

    @property
    def loss_ratio(self) -> float:
        return self.attacker_losses / self.defender_losses if self.defender_losses else float("inf")


@dataclass
class War:
    name: str
    start_date: Optional[str]
    end_date: Optional[str]
    original_attacker: str
    original_defender: str
    attackers: List[str]
    defenders: List[str]
    battles: List[Battle] = field(default_factory=list)
    casus_belli: str = ""
    action: Optional[str] = None

    @property
    def attacker_losses(self) -> int:
        return sum(b.attacker_losses for b in self.battles)

    @property
    def defender_losses(self) -> int:
        return sum(b.defender_losses for b in self.battles)

    @property
    def battles_count(self) -> int:
        return len(self.battles)

    def side_of(self, tag: str) -> Optional[str]:
        if tag in self.attackers or tag == self.original_attacker:
            return "attacker"
        if tag in self.defenders or tag == self.original_defender:
            return "defender"
        return None


@dataclass
class PopEntry:
    province_id: int
    pop_type: str
    size: int
    culture: str
    religion: str
    money_total: float
    money_per_pop: float
    literacy: float
    militancy: float
    consciousness: float
    needs: str = ""


@dataclass
class PopBreakdown:
    size: int = 0
    literacy: float = 0.0
    militancy: float = 0.0
    consciousness: float = 0.0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_culture: Dict[str, int] = field(default_factory=dict)
    by_ideology: Dict[str, float] = field(default_factory=dict)
    by_religion: Dict[str, int] = field(default_factory=dict)
    by_issues: Dict[str, float] = field(default_factory=dict)
    richest: List[PopEntry] = field(default_factory=list)
    poorest: List[PopEntry] = field(default_factory=list)


@dataclass
class MigrationDestination:
    province_id: int
    owner: str
    date: str
    foreign_population: float
    total_population: float


@dataclass
class MigrationSnapshot:
    date: str = ""
    destinations: List[MigrationDestination] = field(default_factory=list)
    immigration_by_country: List[Tuple[str, float]] = field(default_factory=list)
    top_immigrant_cultures: List[Tuple[str, float]] = field(default_factory=list)
    emigration_by_culture: List[Tuple[str, float]] = field(default_factory=list)


@dataclass
class CountryStats:
    tag: str
    name: str = ""
    capital: Optional[int] = None
    government: str = ""
    civilized: bool = False
    prestige: float = 0.0
    badboy: float = 0.0
    plurality: float = 0.0
    money: float = 0.0
    population: int = 0
    pop: PopBreakdown = field(default_factory=PopBreakdown)
    states: int = 0
    provinces: int = 0
    province_ids: List[int] = field(default_factory=list)
    factories: int = 0
    factory_levels: int = 0
    factory_workers: int = 0
    technologies: int = 0
    industry_score: float = 0.0
    upper_house: Dict[str, float] = field(default_factory=dict)
    reforms: Dict[str, str] = field(default_factory=dict)
    battles_won: int = 0
    battles_lost: int = 0
    total_losses_inflicted: int = 0
    total_losses_suffered: int = 0
    brigades: int = 0
    upper_house_ideology: Dict[str, float] = field(default_factory=dict)


POP_TYPES = [
    "aristocrats", "artisans", "bureaucrats", "capitalists", "clergymen",
    "clerks", "craftsmen", "farmers", "labourers", "officers", "peasants",
    "slaves", "soldiers",
]

ARMY_UNIT_KEYS = ["infantry", "irregular", "cavalry", "artillery", "tank",
                  "aeroplane", "cossack", "cuirassier", "dragoon", "hussar",
                  "plane", "airplane", "big_ship", "light_ship", "transport"]


def parse_date(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    return None


class SaveAnalyzer:
    """High-level analysis over one parsed save tree."""

    def __init__(self, tree: Dict[str, Any], game_files=None):
        self.tree = tree
        self.game_files = game_files
        self.date = str(tree.get("date", ""))
        self.player = str(tree.get("player", ""))
        self._production_cache: Optional[Dict[str, Dict[str, float]]] = None

    # ------------------------------------------------------------- helpers

    def _country_block(self, tag: str) -> Optional[Dict[str, Any]]:
        block = self.tree.get(tag)
        if isinstance(block, list):
            block = block[0] if block else None
        if isinstance(block, dict):
            return block
        return None

    def country_tags(self) -> List[str]:
        tags = []
        for key, value in self.tree.items():
            if len(key) == 3 and key.isalpha() and key.isupper() and isinstance(value, (dict, list)):
                tags.append(key)
        return sorted(set(tags))

    def _province_blocks(self) -> List[Tuple[int, Dict[str, Any]]]:
        """Province blocks live at the top level of the save as numeric keys."""
        result: List[Tuple[int, Dict[str, Any]]] = []
        for key, value in self.tree.items():
            if key == "__values__" or not key.isdigit():
                continue
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, dict):
                result.append((int(key), value))
        return result

    # ----------------------------------------------------------------- wars

    def wars(self) -> List[War]:
        wars: List[War] = []
        for raw in _as_list(self.tree.get("previous_war")) + _as_list(self.tree.get("current_war")):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "Unknown war"))
            start = end = None
            attackers: List[str] = []
            defenders: List[str] = []
            battles: List[Battle] = []
            cb = ""
            history = raw.get("history")
            if isinstance(history, list):
                history = history[0] if history else None
            if isinstance(history, dict):
                for date, entry in history.items():
                    if date == "__values__":
                        continue
                    date_str = str(date)
                    entries = _as_list(entry)
                    if not start:
                        start = date_str
                    end = date_str
                    for item in entries:
                        if not isinstance(item, dict):
                            continue
                        if "add_attacker" in item:
                            attackers.append(str(item["add_attacker"]))
                        if "add_defender" in item:
                            defenders.append(str(item["add_defender"]))
                        if "rem_attacker" in item:
                            # participants that left the war are still
                            # historical participants; don't drop them
                            pass
                        if "rem_defender" in item:
                            pass
                        wg = item.get("war_goal")
                        if isinstance(wg, dict):
                            cb = str(wg.get("casus_belli", cb))
                        battle = item.get("battle")
                        if isinstance(battle, dict):
                            battles.append(self._make_battle(battle, date_str, name))
            war = War(
                name=name,
                start_date=start,
                end_date=end,
                original_attacker=str(raw.get("original_attacker", attackers[0] if attackers else "---")),
                original_defender=str(raw.get("original_defender", defenders[0] if defenders else "---")),
                attackers=sorted(set(attackers)),
                defenders=sorted(set(defenders)),
                battles=battles,
                casus_belli=cb,
                action=str(raw.get("action", "") or ""),
            )
            wars.append(war)
        return wars

    def _make_battle(self, battle: Dict[str, Any], date: str, war_name: str) -> Battle:
        attacker = battle.get("attacker") or {}
        defender = battle.get("defender") or {}
        if isinstance(attacker, list):
            attacker = attacker[0] if attacker else {}
        if isinstance(defender, list):
            defender = defender[0] if defender else {}
        return Battle(
            date=date,
            war_name=war_name,
            name=str(battle.get("name", "")),
            location=int(battle.get("location", 0) or 0),
            attacker=str(attacker.get("country", "---")),
            defender=str(defender.get("country", "---")),
            attacker_leader=str(attacker.get("leader", "") or ""),
            defender_leader=str(defender.get("leader", "") or ""),
            attacker_forces=sum(int(attacker.get(k, 0) or 0) for k in ARMY_UNIT_KEYS),
            defender_forces=sum(int(defender.get(k, 0) or 0) for k in ARMY_UNIT_KEYS),
            attacker_losses=int(attacker.get("losses", 0) or 0),
            defender_losses=int(defender.get("losses", 0) or 0),
            attacker_won=bool(battle.get("result", False)),
        )

    def battles(self) -> List[Battle]:
        battles: List[Battle] = []
        for war in self.wars():
            battles.extend(war.battles)
        return battles

    def province_owners(self) -> Dict[int, str]:
        """Province id -> owner tag for every owned province in the save."""
        owners: Dict[int, str] = {}
        for pid, block in self._province_blocks():
            owner = block.get("owner")
            if isinstance(owner, str) and owner and owner != "---":
                owners[pid] = owner
        return owners

    # ------------------------------------------------------------- country

    def country_stats(self, tag: str) -> CountryStats:
        block = self._country_block(tag)
        stats = CountryStats(tag=tag)
        if block is None:
            return stats
        stats.capital = block.get("capital")
        stats.government = str(block.get("government", ""))
        stats.civilized = bool(block.get("civilized", False))
        stats.prestige = float(block.get("prestige", 0) or 0)
        stats.badboy = float(block.get("badboy", 0) or 0)
        stats.plurality = float(block.get("plurality", 0) or 0)
        stats.money = float(block.get("money", 0) or 0)
        uh = block.get("upper_house")
        if isinstance(uh, dict):
            stats.upper_house = {k: float(v) for k, v in uh.items() if k != "__values__"}
        stats.reforms = self._extract_reforms(block)
        stats.technologies = self._count_technologies(block)
        states = _as_list(block.get("state"))
        stats.states = len(states)
        for state in states:
            if not isinstance(state, dict):
                continue
            for building in _as_list(state.get("state_buildings")):
                if isinstance(building, dict):
                    stats.factories += 1
                    stats.factory_levels += int(building.get("level", 0) or 0)
                    employment = building.get("employment")
                    if isinstance(employment, dict):
                        for emp in _as_list(employment.get("employees")):
                            if isinstance(emp, dict):
                                stats.factory_workers += int(emp.get("count", 0) or 0)
            provs = state.get("provinces")
            if isinstance(provs, list):
                stats.province_ids.extend(int(p) for p in provs if isinstance(p, (int, float)))
            stats.provinces = len(stats.province_ids)
        stats.brigades = self._count_brigades(block)
        name = ""
        if self.game_files is not None:
            name = self.game_files.country_names().get(tag, "")
        stats.name = name
        return stats

    def _extract_reforms(self, block: Dict[str, Any]) -> Dict[str, str]:
        reforms: Dict[str, str] = {}
        for key, value in block.items():
            if key in REFORM_KEYS and isinstance(value, str):
                reforms[key] = value
        return reforms

    def _count_technologies(self, block: Dict[str, Any]) -> int:
        tech = block.get("technology")
        if not isinstance(tech, dict):
            return 0
        count = 0
        for name, value in tech.items():
            if name == "__values__":
                continue
            entry = _first(value)
            if isinstance(entry, list) and entry and entry[0] == 1:
                count += 1
            elif isinstance(entry, (int, float)) and entry >= 1:
                count += 1
        return count

    def _count_brigades(self, block: Dict[str, Any]) -> int:
        army = block.get("army")
        navy = block.get("navy")
        count = 0
        for branch in (army, navy):
            for reg in _as_list(branch):
                if isinstance(reg, dict):
                    count += len(_as_list(reg.get("regiment")))
        return count

    # ----------------------------------------------------------- population

    def pop_stats(self, tag: str) -> PopBreakdown:
        block = self._country_block(tag)
        breakdown = PopBreakdown()
        if block is None:
            return breakdown
        owned = set()
        for state in _as_list(block.get("state")):
            if isinstance(state, dict):
                provs = state.get("provinces")
                if isinstance(provs, list):
                    owned.update(int(p) for p in provs if isinstance(p, (int, float)))
        return self._pop_breakdown_for_provinces(owned, breakdown)

    def _pop_breakdown_for_provinces(self, province_ids, breakdown: PopBreakdown) -> PopBreakdown:
        provinces = dict(self._province_blocks())
        total = 0
        lit_sum = 0.0
        mil_sum = 0.0
        con_sum = 0.0
        entries: List[PopEntry] = []
        for pid in province_ids:
            prov = provinces.get(int(pid))
            if prov is None:
                continue
            for ptype in POP_TYPES:
                for pop in _as_list(prov.get(ptype)):
                    if not isinstance(pop, dict):
                        continue
                    size = int(pop.get("size", 0) or 0)
                    if size <= 0:
                        continue
                    total += size
                    lit_sum += float(pop.get("literacy", 0) or 0) * size
                    mil_sum += float(pop.get("mil", 0) or 0) * size
                    con_sum += float(pop.get("con", 0) or 0) * size
                    breakdown.by_type[ptype] = breakdown.by_type.get(ptype, 0) + size
                    culture = self._pop_culture(pop)
                    breakdown.by_culture[culture] = breakdown.by_culture.get(culture, 0) + size
                    religion = self._pop_religion(pop)
                    breakdown.by_religion[religion] = breakdown.by_religion.get(religion, 0) + size
                    ideology = pop.get("ideology")
                    if isinstance(ideology, dict):
                        for iid, share in ideology.items():
                            if iid == "__values__":
                                continue
                            key = IDEOLOGY_NAMES.get(iid, f"ideology_{iid}")
                            breakdown.by_ideology[key] = breakdown.by_ideology.get(key, 0.0) + float(share) * size / 100.0
                    issues = pop.get("issues")
                    if isinstance(issues, dict):
                        for iid, share in issues.items():
                            if iid == "__values__":
                                continue
                            breakdown.by_issues[iid] = breakdown.by_issues.get(iid, 0.0) + float(share) * size / 100.0
                    money = float(_first(pop.get("money")) or 0)
                    needs = ""
                    if pop.get("luxury_needs", 0) is not None:
                        needs = "luxury"
                    entries.append(PopEntry(
                        province_id=int(pid),
                        pop_type=ptype,
                        size=size,
                        culture=culture,
                        religion=religion,
                        money_total=money,
                        money_per_pop=money / size,
                        literacy=float(pop.get("literacy", 0) or 0),
                        militancy=float(pop.get("mil", 0) or 0),
                        consciousness=float(pop.get("con", 0) or 0),
                        needs=needs,
                    ))
        breakdown.size = total
        if total:
            breakdown.literacy = lit_sum / total
            breakdown.militancy = mil_sum / total
            breakdown.consciousness = con_sum / total
        entries.sort(key=lambda e: -e.money_per_pop)
        breakdown.richest = entries[:5]
        breakdown.poorest = [e for e in reversed(entries)
                             if e.money_per_pop < entries[0].money_per_pop][:5] if entries else []
        # poorest: take from the bottom, but skip zero-money unreconciled pops
        zeroless = [e for e in entries if e.money_per_pop > 0]
        if zeroless:
            breakdown.poorest = zeroless[-5:]
            breakdown.poorest.reverse()
        return breakdown

    @staticmethod
    def _pop_culture(pop: Dict[str, Any]) -> str:
        for key in pop:
            if key in ("id", "size", "money", "ideology", "issues", "con", "mil",
                       "literacy", "bank", "con_factor", "demoted", "luxury_needs",
                       "random", "production_type", "stockpile", "need", "last_spending",
                       "current_producing", "percent_afforded", "percent_sold_domestic",
                       "percent_sold_export", "leftover", "throttle", "needs_cost",
                       "production_income", "__values__"):
                continue
            value = pop.get(key)
            if isinstance(value, str) and key not in ("type",):
                return key
        return "unknown"

    @staticmethod
    def _pop_religion(pop: Dict[str, Any]) -> str:
        for key in pop:
            value = pop.get(key)
            if isinstance(value, str) and key in RELIGION_HINTS:
                return value
        for key in pop:
            value = pop.get(key)
            if isinstance(value, str) and value in RELIGION_HINTS:
                return value
        return "unknown"

    # --------------------------------------------------------------- economy

    def _good_production_of_pop(self, pop: Dict[str, Any]) -> Optional[Tuple[str, float]]:
        """Goods produced by an artisan pop (production_type + current output)."""
        ptype = pop.get("production_type")
        if not isinstance(ptype, str) or not ptype.startswith("artisan_"):
            return None
        good = ptype[len("artisan_"):]
        producing = pop.get("current_producing")
        if not isinstance(producing, (int, float)):
            producing = 0.0
        return good, float(producing)

    def production_by_country(self) -> Dict[str, Dict[str, float]]:
        """Tag -> {good: supply reaching the market}.

        Uses the save's own per-country ``saved_country_supply`` snapshot
        (actual daily supply per good).  Fallbacks, merged in where supply
        data is missing: artisan ``current_producing`` output, factory
        ``produces`` and RGO ``last_income``.
        """
        if self._production_cache is not None:
            return self._production_cache
        result: Dict[str, Dict[str, float]] = {}
        for tag in self.country_tags():
            block = self._country_block(tag)
            if not block:
                continue
            supply = _first(block.get("saved_country_supply"))
            goods: Dict[str, float] = {}
            if isinstance(supply, dict):
                for good, amount in supply.items():
                    if good != "__values__" and isinstance(amount, (int, float)):
                        goods[good] = float(amount)
            result[tag] = goods
        self._production_cache = result
        return result

    def world_production_totals(self) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for goods in self.production_by_country().values():
            for good, amount in goods.items():
                totals[good] = totals.get(good, 0.0) + amount
        return totals

    def production_highlights(self, tag: str, top: int = 3) -> List[Dict[str, Any]]:
        """The goods a country is best at, with its world share."""
        country_goods = self.production_by_country().get(tag, {})
        world = self.world_production_totals()
        entries: List[Dict[str, Any]] = []
        for good, amount in country_goods.items():
            world_total = world.get(good, 0.0)
            if world_total <= 0:
                continue
            entries.append({
                "good": good,
                "output": amount,
                "world_total": world_total,
                "share": amount / world_total,
            })
        # rank by world share: what the country is *best at* comes first
        entries.sort(key=lambda h: -h["share"])
        return entries[:top]

    # ------------------------------------------------------------- migration

    def migration_snapshot(self) -> MigrationSnapshot:
        """Immigration activity around the save's current date.

        Victoria II records per province only ``last_imigration`` — the date
        of the most recent arrival — so "today's" destinations are the
        provinces whose date matches (or is within a few days of) the save
        date.  For each destination we size the immigrant community by the
        population of pops whose culture is foreign to the owning country.
        Cumulative emigration by culture is measured by diaspora: pops of a
        culture living under states that do not accept them.
        """
        today = self.date
        if not today:
            return MigrationSnapshot()
        year, month, day = (int(x) for x in today.split("."))
        def _date_no_later_than(value: Any, max_days: int) -> bool:
            try:
                y, m, d = (int(x) for x in str(value).split("."))
            except (ValueError, TypeError):
                return False
            return (y, m, d) >= (year, month, day - max_days) and (y, m, d) <= (year, month, day)

        owners = self.province_owners()
        accepted: Dict[str, set] = {}
        for tag in set(owners.values()):
            block = self._country_block(tag) or {}
            ok = set()
            primary = block.get("primary_culture")
            if isinstance(primary, str):
                ok.add(primary)
            for culture in _as_list(block.get("culture")):
                if isinstance(culture, str):
                    ok.add(culture)
            accepted[tag] = ok

        provinces = dict(self._province_blocks())
        destination_rows: List[MigrationDestination] = []
        diaspora: Dict[str, float] = {}
        immigrant_stock: Dict[str, Dict[str, float]] = {}
        for pid, prov in provinces.items():
            tag = owners.get(pid)
            if not tag:
                continue
            ok = accepted.get(tag, set())
            receiving = _date_no_later_than(prov.get("last_imigration"), 30)
            prov_foreign = 0.0
            prov_total = 0.0
            for ptype in POP_TYPES:
                for pop in _as_list(prov.get(ptype)):
                    if not isinstance(pop, dict):
                        continue
                    size = float(pop.get("size", 0) or 0)
                    if size <= 0:
                        continue
                    culture = self._pop_culture(pop)
                    prov_total += size
                    if culture not in ok:
                        prov_foreign += size
                        stock = immigrant_stock.setdefault(tag, {})
                        stock[culture] = stock.get(culture, 0.0) + size
                        diaspora[culture] = diaspora.get(culture, 0.0) + size
            if receiving and prov_foreign > 0:
                destination_rows.append(MigrationDestination(
                    province_id=pid, owner=tag, date=str(prov.get("last_imigration")),
                    foreign_population=prov_foreign, total_population=prov_total))

        by_country: Dict[str, float] = {}
        for row in destination_rows:
            by_country[row.owner] = by_country.get(row.owner, 0.0) + row.foreign_population
        top_sources = sorted(diaspora.items(), key=lambda kv: -kv[1])[:10]
        top_cultures = sorted(
            ((c, v) for stock in immigrant_stock.values() for c, v in stock.items()),
            key=lambda kv: -kv[1])
        seen = set()
        unique_cultures = []
        for culture, size in top_cultures:
            if culture not in seen:
                seen.add(culture)
                unique_cultures.append((culture, size))
        return MigrationSnapshot(
            date=today,
            destinations=sorted(destination_rows, key=lambda r: -r.foreign_population),
            immigration_by_country=sorted(by_country.items(), key=lambda kv: -kv[1]),
            top_immigrant_cultures=unique_cultures[:10],
            emigration_by_culture=top_sources,
        )

    def world_market(self) -> Dict[str, float]:
        market = self.tree.get("worldmarket")
        if isinstance(market, list):
            market = market[0] if market else None
        if not isinstance(market, dict):
            return {}
        pool = market.get("worldmarket_pool")
        if isinstance(pool, list):
            pool = pool[0] if pool else None
        if not isinstance(pool, dict):
            return {}
        return {k: float(v) for k, v in pool.items() if k != "__values__"}

    def country_economy(self, tag: str) -> Dict[str, Any]:
        block = self._country_block(tag)
        if block is None:
            return {}
        def _scalar(key: str) -> float:
            value = _first(block.get(key))
            return float(value) if isinstance(value, (int, float)) else 0.0

        return {
            "money": _scalar("money"),
            "bank": _scalar("bank"),
            "rich_tax": _scalar("rich_tax"),
            "middle_tax": _scalar("middle_tax"),
            "poor_tax": _scalar("poor_tax"),
            "tariffs": _scalar("tariffs"),
            "incomes": _budget_vector(block.get("incomes"), INCOME_CATEGORIES),
            "expenses": _budget_vector(block.get("expenses"), EXPENSE_CATEGORIES),
            "stockpile": dict(_flatten_scalars(block.get("stockpile"))),
        }

    # -------------------------------------------------------------- summary

    def summary(self) -> Dict[str, Any]:
        player_stats = self.country_stats(self.player) if self.player else None
        return {
            "date": self.date,
            "player": self.player,
            "wars": len(self.wars()),
            "battles": len(self.battles()),
            "population": player_stats.pop.size if player_stats else 0,
            "prestige": player_stats.prestige if player_stats else 0,
            "money": player_stats.money if player_stats else 0,
        }


def _flatten_scalars(value) -> Dict[str, float]:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return {}
    return {k: float(v) for k, v in value.items()
            if k != "__values__" and isinstance(v, (int, float, bool))}


FACTORY_OUTPUT = {
    "fabric_factory": "fabric", "cement_factory": "cement",
    "ammunition_factory": "ammunition", "small_arms_factory": "small_arms",
    "artillery_factory": "artillery", "canned_food_factory": "canned_food",
    "glass_factory": "glass", "winery": "liquor", "liquor_distillery": "liquor",
    "furniture_factory": "furniture", "clothing_factory": "clothes",
    "paper_mill": "paper", "steel_factory": "steel",
    "auto_factory": "automobiles", "aeroplane_factory": "aeroplanes",
    "electric_gear_factory": "electric_gear", "radio_factory": "radio",
    "telephone_factory": "telephones", "tank_factory": "tanks",
    "explosives_factory": "explosives", "fuel_refinery": "fuel",
    "fertilizer_plant": "fertilizer", "machine_parts_factory": "machine_parts",
    "luxury_clothes_factory": "luxury_clothes",
    "luxury_furniture_factory": "luxury_furniture",
    "silk_factory": "silk", "dye_factory": "dye",
    "lumber_mill": "lumber", "shipyard": "steamer_convoy",
}

INCOME_CATEGORIES = [
    "taxes_poor", "taxes_middle", "taxes_rich", "tariffs", "gold",
    "national_stockpile", "industry_subsidies", "education",
    "administration", "military",
]

EXPENSE_CATEGORIES = [
    "national_stockpile", "tariff_subsidies", "naval_stockpile",
    "army_stockpile", "construction", "project_construction",
    "education", "administration", "social_spending", "military_spending",
]


def _budget_vector(value, categories: List[str]) -> Dict[str, float]:
    """Positional budget arrays in the save map to fixed category order."""
    if isinstance(value, list) and value and not isinstance(value[0], (int, float)):
        value = _first(value)
    if not isinstance(value, list):
        return {}
    return {cat: float(v) for cat, v in zip(categories, value)
            if isinstance(v, (int, float))}


IDEOLOGY_NAMES = {
    "1": "anarcho_liberal", "2": "conservative", "3": "reactionary",
    "4": "liberal", "5": "socialist", "6": "communist", "7": "fascist",
    "8": "fascist", "9": "anarcho_liberal",
}

REFORM_KEYS = {
    "slavery", "vote_franschise", "upper_house_composition", "voting_system",
    "public_meetings", "press_rights", "trade_unions", "political_parties",
    "wage_reform", "work_hours", "safety_regulations", "unemployment_subsidies",
    "pensions", "health_care", "school_reforms",
}

RELIGION_HINTS = {
    "animist", "orthodox", "catholic", "protestant", "sunni", "shiite",
    "mahayana", "gelugpa", "hindu", "buddhist", "shinto", "pagan",
    "confucian", "tolerated", "jewish", "zoroastrian",
}
