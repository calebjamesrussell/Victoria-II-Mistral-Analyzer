import os

import pytest

from vic2analyzer.analyzer import SaveAnalyzer
from vic2analyzer.parser import parse_file

SAVE = os.environ.get("VIC2_TEST_SAVE", "")
INSTALL = os.environ.get("VIC2_TEST_INSTALL", "")


def _skip_if_no_save():
    if not (SAVE and os.path.isfile(SAVE)):
        pytest.skip("VIC2_TEST_SAVE not set to a real .v2 file")


@pytest.fixture(scope="module")
def analyzer():
    _skip_if_no_save()
    tree = parse_file(SAVE)
    return SaveAnalyzer(tree)


@pytest.fixture(scope="module")
def analyzer_with_gf():
    _skip_if_no_save()
    from vic2analyzer.gamefiles import GameFiles
    tree = parse_file(SAVE)
    gf = GameFiles(INSTALL) if INSTALL and os.path.isdir(INSTALL) else None
    return SaveAnalyzer(tree, gf)


def test_parses_save(analyzer):
    assert analyzer.date.count(".") == 2
    assert len(analyzer.player) == 3


def test_wars_extracted(analyzer):
    wars = analyzer.wars()
    assert len(wars) > 10
    assert all(w.name for w in wars)


def test_battles_have_losses(analyzer):
    battles = analyzer.battles()
    assert len(battles) > 100
    assert all(isinstance(b.attacker_losses, int) for b in battles)
    deadly = max(battles, key=lambda b: b.total_losses)
    assert deadly.total_losses > 0


def test_war_side_tracking(analyzer):
    wars = analyzer.wars()
    war = wars[0]
    if war.attackers:
        assert war.side_of(war.attackers[0]) == "attacker"
    if war.defenders:
        assert war.side_of(war.defenders[0]) == "defender"


def test_country_stats(analyzer):
    tags = analyzer.country_tags()
    assert len(tags) > 100
    stats = analyzer.country_stats(analyzer.player)
    assert stats.tag == analyzer.player
    assert stats.prestige >= 0


def test_population_stats(analyzer):
    pop = analyzer.pop_stats(analyzer.player)
    assert pop.size > 0
    assert 0.0 <= pop.literacy <= 1.0
    assert pop.by_type
    assert sum(pop.by_type.values()) == pop.size


def test_world_market(analyzer):
    market = analyzer.world_market()
    assert market
    assert all(v >= 0 for v in market.values())


def test_country_economy(analyzer):
    econ = analyzer.country_economy(analyzer.player)
    assert "money" in econ
    assert "incomes" in econ
    total_income = sum(econ["incomes"].values())
    assert total_income >= 0


def test_game_files_names_and_flags(analyzer_with_gf):
    import pytest as _pytest
    if not INSTALL:
        _pytest.skip("VIC2_TEST_INSTALL not set")
    gf = analyzer_with_gf.game_files
    names = gf.country_names()
    assert names.get(analyzer_with_gf.player)
    img = gf.flag_image(analyzer_with_gf.player)
    assert img is not None and img.size == (64, 42)


def test_migration_snapshot(analyzer):
    snap = analyzer.migration_snapshot()
    assert snap.date == analyzer.date
    assert snap.destinations, "expected receiving provinces in the save"
    for row in snap.destinations[:20]:
        assert row.province_id > 0
        assert len(row.owner) == 3
        assert row.foreign_population > 0
        assert row.total_population >= row.foreign_population
    if snap.immigration_by_country:
        tag, size = snap.immigration_by_country[0]
        assert len(tag) == 3 and size > 0
    assert snap.emigration_by_culture, "expected diaspora cultures"


def test_pop_issue_names_from_install(analyzer_with_gf):
    if analyzer_with_gf.game_files is None:
        pytest.skip("VIC2_TEST_INSTALL not set")
    names = analyzer_with_gf.game_files.pop_issue_names()
    assert names.get("14") == "Jingoism"
    assert names.get("1") == "Protectionism"
    assert names.get("80") == "Good School system"
