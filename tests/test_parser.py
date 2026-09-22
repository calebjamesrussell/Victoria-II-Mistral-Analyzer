import pytest

from vic2analyzer.parser import parse_string, ClausewitzSyntaxError


def test_simple_pairs():
    tree = parse_string('a=1 b="two" c=yes d=no')
    assert tree == {"a": 1, "b": "two", "c": True, "d": False}


def test_nested_block():
    tree = parse_string("outer={ inner=42 flag=yes }")
    assert tree["outer"]["inner"] == 42
    assert tree["outer"]["flag"] is True


def test_plain_array_block():
    tree = parse_string("provinces={ 1096 1848 1850 }")
    assert tree["provinces"] == [1096, 1848, 1850]


def test_repeated_keys_collect_into_list():
    tree = parse_string("state={id=1} state={id=2}")
    states = tree["state"]
    assert isinstance(states, list)
    assert [s["id"] for s in states] == [1, 2]


def test_date_keys():
    tree = parse_string("history={ 1836.1.1={ add_attacker=\"AFG\" } 1836.3.7={ battle={name=\"Kulob\"} } }")
    history = tree["history"]
    assert history["1836.1.1"]["add_attacker"] == "AFG"
    assert history["1836.3.7"]["battle"]["name"] == "Kulob"


def test_mixed_pairs_and_values_block():
    tree = parse_string("profit_history_entry={ 0.02 0.01 -0.17 }")
    assert tree["profit_history_entry"] == [0.02, 0.01, -0.17]


def test_floats_and_negatives():
    tree = parse_string("money=387.68280 badboy=-3.5")
    assert tree["money"] == 387.68280
    assert tree["badboy"] == -3.5


def test_comments_ignored():
    tree = parse_string("# a comment\nkey=1")
    assert tree == {"key": 1}


def test_trailing_stray_brace_tolerated():
    tree = parse_string("date=\"1903.1.13\" }\n")
    assert tree["date"] == "1903.1.13"


def test_tab_and_crlf_whitespace():
    tree = parse_string("a={\r\n\tb=1\r\n}\r\n")
    assert tree["a"]["b"] == 1


def test_employees_style_nested_anonymous_blocks():
    text = "employees={ { province_pop_id={ province_id=1096 index=0 type=7 } count=5216 } { province_pop_id={ province_id=1096 index=0 type=6 } count=210 } }"
    tree = parse_string(text)
    employees = tree["employees"]
    assert isinstance(employees, list) and len(employees) == 2
    assert employees[0]["count"] == 5216


def test_uppercase_hex_like_tokens():
    tree = parse_string('GEO={ human=yes capital=1096 }')
    assert tree["GEO"]["capital"] == 1096


def test_unterminated_string_raises():
    with pytest.raises(ClausewitzSyntaxError):
        parse_string('a="oops')
