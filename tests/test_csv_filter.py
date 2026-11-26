import csv

import pytest
from click.testing import CliRunner

from rich_cli.csv_filter import (
    Condition,
    FilterError,
    find_column,
    make_row_filter,
    parse_columns,
    parse_condition,
)

# --- Parsing --columns ----------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("name,status", ["name", "status"]),
        (" name , status ", ["name", "status"]),
        ("name,status,", ["name", "status"]),  # trailing comma ignored
        ('"City, State",name', ["City, State", "name"]),  # quoted names
        ("status,name", ["status", "name"]),  # order is kept
    ],
)
def test_parse_columns(value, expected):
    assert parse_columns(value) == expected


@pytest.mark.parametrize("value", ["", " ", ",", " , ,"])
def test_parse_columns_blank(value):
    with pytest.raises(FilterError, match="at least one column name"):
        parse_columns(value)


# --- Parsing --where ------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("status=active", ("status", "=", "active")),
        ("status == active", ("status", "=", "active")),
        (" status = active ", ("status", "=", "active")),
        ("status!=active", ("status", "!=", "active")),
        ("status<>active", ("status", "!=", "active")),
        ("age>30", ("age", ">", "30")),
        ("age>=30", ("age", ">=", "30")),
        ("age<30", ("age", "<", "30")),
        ("age<=30.5", ("age", "<=", "30.5")),
        ("age>-1e3", ("age", ">", "-1e3")),
        ("name=Adam Stern", ("name", "=", "Adam Stern")),
        ('name="Adam Stern"', ("name", "=", "Adam Stern")),
        ("name='Tom and Jerry'", ("name", "=", "Tom and Jerry")),
        ("title=Tom and Jerry", ("title", "=", "Tom and Jerry")),  # no 2nd condition
        ("note=a=b", ("note", "=", "a=b")),  # only the first operator counts
        ("status=", ("status", "=", "")),  # empty cells
        ('"City, State"=Austin, TX', ("City, State", "=", "Austin, TX")),
        ("'a>b' = x", ("a>b", "=", "x")),  # operators inside a quoted name
        ("Height(inches)>=74", ("Height(inches)", ">=", "74")),
    ],
)
def test_parse_condition(text, expected):
    assert parse_condition(text) == Condition(*expected)


@pytest.mark.parametrize(
    "text, message",
    [
        ("status", "expected COLUMN OPERATOR VALUE"),
        ("", "expected COLUMN OPERATOR VALUE"),
        ("=active", "missing column name"),
        ("age>abc", "> needs a number, got 'abc'"),
        ("age>", "> needs a number, got ''"),
        ("age>=nan", ">= needs a number"),
        ("age<inf", "< needs a number"),
        ('"City, State=x', 'missing closing "'),
        ('"City" zz=x', "unexpected text after the quoted column name"),
        ("status=active and age>30", "one condition per --where"),
        ("age>30 AND status=active", "one condition per --where"),
        ("status=active && age>30", "one condition per --where"),
        ("status=active or status=new", "OR is not supported"),
        ("status=active || age>30", "OR is not supported"),
    ],
)
def test_parse_condition_errors(text, message):
    with pytest.raises(FilterError, match=message.replace("(", r"\(")):
        parse_condition(text)


# --- Finding columns ------------------------------------------------------------

HEADER = ["Name", "Status", "City, State", "Score", "Score "]


def test_find_column_ignores_case_and_whitespace():
    assert find_column(HEADER, "name") == 0
    assert find_column(HEADER, "  STATUS ") == 1
    assert find_column(HEADER, "city,  state") == 2


def test_find_column_errors():
    with pytest.raises(FilterError, match="No such column: 'nope'"):
        find_column(HEADER, "nope")
    with pytest.raises(FilterError, match="No such column: 'Nam'"):
        find_column(HEADER, "Nam")  # no partial matches
    with pytest.raises(FilterError, match="ambiguous"):
        find_column(HEADER, "score")


# --- Matching rows --------------------------------------------------------------

ROWS = [
    ["Ada", "active", "Austin, TX", "10"],
    ["Bob", "Inactive", "Boston, MA", "N/A"],
    ["Cy", "ACTIVE ", "Chicago, IL", "7"],
    ["Dee", "active", "Denver, CO", ""],
    ["Eve", "active", "El Paso, TX", "10.0"],
    ["Fay"],  # short row, missing cells are treated as empty
]


def _names(*conditions):
    row_filter = make_row_filter(HEADER[:4], [parse_condition(c) for c in conditions])
    return [row[0] for row in ROWS if row_filter(row)]


@pytest.mark.parametrize(
    "condition, expected",
    [
        ("status=active", ["Ada", "Cy", "Dee", "Eve"]),  # case & spaces ignored
        ("status=ACTIVE", ["Ada", "Cy", "Dee", "Eve"]),
        ("status!=active", ["Bob", "Fay"]),
        ("score=10", ["Ada", "Eve"]),  # numeric: 10 == 10.0
        ("score=10.00", ["Ada", "Eve"]),
        ("score!=10", ["Bob", "Cy", "Dee", "Fay"]),
        ("score>7", ["Ada", "Eve"]),
        ("score>=7", ["Ada", "Cy", "Eve"]),  # N/A, empty and missing never match
        ("score<10", ["Cy"]),
        ("score<=10", ["Ada", "Cy", "Eve"]),
        ("score=", ["Dee", "Fay"]),
        ("score=n/a", ["Bob"]),
        ('"City, State"=austin, tx', ["Ada"]),
        ("name=Nobody", []),
    ],
)
def test_row_filter(condition, expected):
    assert _names(condition) == expected


def test_multiple_conditions_must_all_match():
    assert _names("status=active", "score>=10") == ["Ada", "Eve"]
    assert _names("status=active", "score>=10", "name!=eve") == ["Ada"]


# --- Command line ---------------------------------------------------------------

MLB = "test_data/mlb_players.csv"


def _run(*args):
    from rich_cli.__main__ import main

    return CliRunner().invoke(main, [*args, "--width", "250"])


def _table(output):
    return [
        [cell.strip() for cell in line.split("│")[1:-1]]
        for line in output.splitlines()
        if line.startswith("│")
    ]


def _one_line(output):
    return " ".join(output.split())


def _mlb():
    with open(MLB, encoding="utf8") as csv_file:
        rows = [row for row in csv.reader(csv_file, skipinitialspace=True) if row]
    return rows[0], rows[1:]


def test_cli_columns_and_where_match_independent_calculation():
    _, rows = _mlb()
    expected = [
        [row[0], row[2], row[5]]
        for row in rows
        if row[1] == "BAL" and float(row[5]) >= 30
    ]
    result = _run(
        MLB,
        "--columns",
        "name, POSITION,age",
        "--where",
        "team=bal",
        "--where",
        "Age>=30",
    )
    assert result.exit_code == 0, result.output
    assert "┃ Name" in result.output and "Position" in result.output
    assert _table(result.output) == expected


@pytest.mark.parametrize("operator", ["=", "!=", ">", "<", ">=", "<="])
def test_cli_operators_match_independent_calculation(operator):
    _, rows = _mlb()
    compare = {
        "=": float.__eq__,
        "!=": float.__ne__,
        ">": float.__gt__,
        "<": float.__lt__,
        ">=": float.__ge__,
        "<=": float.__le__,
    }[operator]
    expected = [[row[0]] for row in rows if compare(float(row[3]), 74.0)]
    result = _run(MLB, "--columns", "Name", "--where", f"Height(inches){operator}74")
    assert _table(result.output) == expected


def test_cli_where_is_applied_before_head_tail_and_lines():
    _, rows = _mlb()
    nyy = [[row[0]] for row in rows if row[1] == "NYY"]
    args = [MLB, "--columns", "Name", "--where", "Team=NYY"]
    assert _table(_run(*args, "--head", "3").output) == nyy[:3]
    assert _table(_run(*args, "--tail", "2").output) == nyy[-2:]
    assert _table(_run(*args, "--lines", "5:7").output) == nyy[4:7]

    result = _run(*args, "--lines", "40:50")
    assert result.exit_code != 0
    assert _one_line(result.output) == (
        f"--lines start (40) is past the last matching row ({len(nyy)} rows match --where)"
    )


def test_cli_no_matches_shows_empty_table():
    result = _run(MLB, "--where", "Team=Nobody")
    assert result.exit_code == 0
    assert "┃ Name" in result.output
    assert _table(result.output) == []


def test_cli_header_the_sniffer_misses():
    # airtravel.csv's header is "Month", "1958", ... which Python's csv sniffer
    # doesn't recognise, but naming columns implies the first row is the header
    result = _run(
        "test_data/airtravel.csv", "--columns", "Month,1960", "--where", "1960>=600"
    )
    assert result.exit_code == 0, result.output
    assert "┃ Month" in result.output
    assert _table(result.output) == [["JUL", "622"], ["AUG", "606"]]


@pytest.mark.parametrize(
    "args, message",
    [
        (["--columns", "Name,nope"], "No such column: 'nope'"),
        (["--where", "nope=1"], "No such column: 'nope'"),
        (["--columns", ","], "Invalid --columns value ',': expected at least one"),
        (["--where", "Team"], "Invalid --where value 'Team': expected COLUMN OPERATOR"),
        (["--where", "Age>old"], "Invalid --where value 'Age>old': > needs a number"),
        (["--where", "Team=BAL and Age>30"], "one condition per --where"),
        (["--where", "Team=BAL or Team=NYY"], "OR is not supported"),
    ],
)
def test_cli_errors_are_one_line(args, message):
    result = _run(MLB, *args)
    assert result.exit_code != 0
    assert message in _one_line(result.output)
    assert "Adam" not in result.output  # nothing from the file is shown


@pytest.mark.parametrize(
    "args, message",
    [
        (
            ["README.md", "--columns", "Name"],
            "--columns only works with CSV files, not Markdown",
        ),
        (
            ["README.md", "--where", "a=1"],
            "--where only works with CSV files, not Markdown",
        ),
        (
            ["test_data/test.rst", "--columns", "a"],
            "--columns only works with CSV files, not reStructuredText",
        ),
        (
            ["README.md", "--section", "Installation", "--columns", "Name"],
            "--section can't be combined with --columns",
        ),
        (
            ["README.md", "--section", "Installation", "--where", "a=1"],
            "--section can't be combined with --where",
        ),
    ],
)
def test_cli_columns_and_where_need_csv(args, message):
    result = _run(*args)
    assert result.exit_code != 0
    assert _one_line(result.output) == message


def test_cli_empty_csv(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    result = _run(str(path), "--columns", "Name")
    assert result.exit_code != 0
    assert _one_line(result.output) == "No such column: 'Name'"
