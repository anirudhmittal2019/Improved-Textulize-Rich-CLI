"""Column selection (--columns) and row filtering (--where) for CSV tables."""

import csv
import re
from typing import Callable, List, NamedTuple, Optional, Sequence

# Longest operators first, so ">=" is not read as ">" followed by "=value"
OPERATORS = ("==", "!=", "<>", ">=", "<=", "=", ">", "<")
NUMERIC_ONLY_OPERATORS = (">", "<", ">=", "<=")

# e.g. "active and score>5": the user tried to write two conditions in one --where
_COMBINED = re.compile(
    r"\s(and|or|&&|\|\|)\s+[^\s=!<>]+\s*(==|!=|<>|>=|<=|=|>|<)", re.IGNORECASE
).search

_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?").fullmatch


class FilterError(ValueError):
    """An invalid --columns / --where value, with a user facing message."""


class Condition(NamedTuple):
    """A single --where condition, e.g. status=active."""

    column: str
    operator: str
    value: str


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _to_number(text: str) -> Optional[float]:
    text = text.strip()
    return float(text) if _NUMBER(text) else None


def parse_columns(value: str) -> List[str]:
    """Parse a comma separated list of column names.

    Names may be quoted (CSV style) to include a comma, e.g. '"City, State",Name'.
    Empty names (e.g. from a trailing comma) are ignored.
    """
    try:
        names = next(csv.reader([value], skipinitialspace=True), [])
    except csv.Error:
        raise FilterError("expected column names separated by commas") from None
    names = [name.strip() for name in names if name.strip()]
    if not names:
        raise FilterError("expected at least one column name, e.g. Name,Team")
    return names


def parse_condition(text: str) -> Condition:
    """Parse a condition such as "status=active" or "age >= 30".

    The column name may be quoted, e.g. '"City, State"=Austin, TX'.
    """
    # A quoted column name may contain anything (even operators), so only look
    # for the operator after the closing quote
    stripped = text.lstrip()
    search_from = len(text) - len(stripped)
    quote = stripped[:1]
    if quote in ("'", '"'):
        closing = text.find(quote, search_from + 1)
        if closing == -1:
            raise FilterError(f"missing closing {quote} after the column name")
        search_from = closing + 1

    # Find the first operator (preferring the longest at a position)
    position = -1
    operator = ""
    for index in range(search_from, len(text)):
        for candidate in OPERATORS:
            if text.startswith(candidate, index):
                position, operator = index, candidate
                break
        if operator:
            break
    if not operator:
        raise FilterError("expected COLUMN OPERATOR VALUE, e.g. status=active")

    column = text[:position].strip()
    if quote in ("'", '"'):
        if column[-1:] != quote:  # e.g. '"a" b = 1'
            raise FilterError("unexpected text after the quoted column name")
        column = column[1:-1]
    value = text[position + len(operator) :].strip()
    if not column:
        raise FilterError("missing column name before the operator")
    # Allow the value to be quoted, e.g. name="Adam Stern" (quoted values are literal)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    else:
        combined = _COMBINED(f" {value}")
        if combined and combined.group(1).lower() in ("or", "||"):
            raise FilterError("OR is not supported, repeated --where must all match")
        if combined:
            raise FilterError(
                'one condition per --where, e.g. --where "Age>30" --where "Team=BAL"'
            )
    operator = {"==": "=", "<>": "!="}.get(operator, operator)
    if operator in NUMERIC_ONLY_OPERATORS and _to_number(value) is None:
        raise FilterError(f"{operator} needs a number, got {value!r}")
    return Condition(column, operator, value)


def find_column(header: Sequence[str], name: str) -> int:
    """Get the index of a column (case insensitive, ignoring extra whitespace).

    Raises:
        FilterError: If there is no such column, or the name is ambiguous.
    """
    wanted = _normalize(name)
    matches = [
        index for index, column in enumerate(header) if _normalize(column) == wanted
    ]
    if not matches:
        raise FilterError(f"No such column: {name!r}")
    if len(matches) > 1:
        raise FilterError(f"Column {name!r} is ambiguous (it appears more than once)")
    return matches[0]


def make_row_filter(
    header: Sequence[str], conditions: Sequence[Condition]
) -> Callable[[Sequence[str]], bool]:
    """Make a function that returns True for rows matching *all* conditions."""
    checks: List[Callable[[Sequence[str]], bool]] = []
    for condition in conditions:
        index = find_column(header, condition.column)
        checks.append(_make_check(index, condition))

    def row_filter(row: Sequence[str]) -> bool:
        return all(check(row) for check in checks)

    return row_filter


def _make_check(index: int, condition: Condition) -> Callable[[Sequence[str]], bool]:
    operator = condition.operator
    wanted_text = _normalize(condition.value)
    wanted_number = _to_number(condition.value)

    def check(row: Sequence[str]) -> bool:
        cell = row[index] if index < len(row) else ""
        cell_number = _to_number(cell)
        if operator in ("=", "!="):
            if wanted_number is not None and cell_number is not None:
                equal = cell_number == wanted_number
            else:
                equal = _normalize(cell) == wanted_text
            return equal if operator == "=" else not equal
        # Numeric comparison; cells that aren't numbers never match (like NULL in SQL)
        if cell_number is None:
            return False
        assert wanted_number is not None
        if operator == ">":
            return cell_number > wanted_number
        if operator == "<":
            return cell_number < wanted_number
        if operator == ">=":
            return cell_number >= wanted_number
        return cell_number <= wanted_number

    return check
