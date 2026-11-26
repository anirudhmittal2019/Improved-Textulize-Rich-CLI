import click
import pytest
from click import Command
from click.decorators import FC, Parameter
from click.testing import CliRunner


class DuplicateOptionsError(ValueError):
    pass


def test_duplicate_option_flags_raises_exception(monkeypatch):
    """Create a test that will monkeypatch the click.option decorators
    so that they fail noisily when options are duplicated for a command
    """

    def _param_memo_safe(f: FC, param: Parameter) -> None:
        if isinstance(f, Command):
            f.params.append(param)
        else:
            if not hasattr(f, "__click_params__"):
                f.__click_params__ = []  # type: ignore
            else:
                for opt in param.opts:
                    for preexisting_param in f.__click_params__:
                        if opt in preexisting_param.opts:
                            raise DuplicateOptionsError(
                                "Duplicate option added to command."
                                + " The following option appears more than once:\n"
                                + f"{opt} (used for {param.human_readable_name}"
                                + f" and {preexisting_param.human_readable_name})"
                            )

            f.__click_params__.append(param)  # type: ignore

    monkeypatch.setattr(click.decorators, "_param_memo", _param_memo_safe)

    # import here (after monkeypatch) because decorators are run on import
    from rich_cli.__main__ import main

    runner = CliRunner()
    runner.invoke(main)


def _run(*args):
    from rich_cli.__main__ import main

    return CliRunner().invoke(main, [*args, "--width", "200"])


def _csv_titles(output):
    """Extract the 'Title' column values from a rendered deniro.csv table."""
    return [
        line.split("│")[3].strip()
        for line in output.splitlines()
        if line.startswith("│")
    ]


DENIRO = "test_data/deniro.csv"


def test_lines_csv_selects_inclusive_range_and_keeps_header():
    result = _run(DENIRO, "--lines", "2:4")
    assert result.exit_code == 0, result.output
    assert "Title" in result.output  # header is always shown
    assert _csv_titles(result.output) == ["Bloody Mama", "Hi, Mom!", "Born to Win"]


def test_lines_csv_open_ended_ranges():
    assert _csv_titles(_run(DENIRO, "--lines", ":2").output) == [
        "Greetings",
        "Bloody Mama",
    ]
    assert _csv_titles(_run(DENIRO, "--lines", "87:").output) == ["Dirty Grandpa"]
    assert _csv_titles(_run(DENIRO, "--lines", "3").output) == ["Hi, Mom!"]


def test_lines_csv_end_past_last_row_is_clamped():
    result = _run(DENIRO, "--lines", "86:1000")
    assert result.exit_code == 0
    assert _csv_titles(result.output) == ["The Intern", "Dirty Grandpa"]


def test_lines_csv_start_past_last_row_is_an_error():
    result = _run(DENIRO, "--lines", "500:600")
    assert result.exit_code != 0
    assert "past the last row" in result.output


def test_lines_syntax(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("".join(f"line {n}\n" for n in range(1, 21)))
    result = _run(str(path), "--lines", "10:12")
    assert result.exit_code == 0, result.output
    assert result.output.split() == ["line", "10", "line", "11", "line", "12"]

    result = _run(str(path), "--lines", "19:99")
    assert result.output.split() == ["line", "19", "line", "20"]

    result = _run(str(path), "--lines", "50:60")
    assert result.exit_code != 0
    assert "past the last line" in result.output


@pytest.mark.parametrize(
    "value, reason",
    [
        ("50:10", "end line (10) is before start line (50)"),
        ("abc", "expected START:END, e.g. 10:50"),
        ("a:b", "expected START:END, e.g. 10:50"),
        ("10-50", "expected START:END, e.g. 10:50"),
        ("1.5:3", "expected START:END, e.g. 10:50"),
        ("1:2:3", "expected START:END, e.g. 10:50"),
        # Blank ranges are rejected rather than silently showing everything
        ("", "expected START:END, e.g. 10:50"),
        ("   ", "expected START:END, e.g. 10:50"),
        (":", "expected START:END, e.g. 10:50"),
        ("0:5", "start line must be 1 or greater (got 0)"),
        ("-1:5", "start line must be 1 or greater (got -1)"),
    ],
)
def test_lines_invalid_values(value, reason):
    result = _run(DENIRO, f"--lines={value}")
    assert result.exit_code != 0
    # A single, short error line and nothing from the file
    expected = f"Invalid --lines value {value!r}: {reason}"
    assert " ".join(result.output.split()) == " ".join(expected.split())


@pytest.mark.parametrize(
    "path, format_name",
    [
        ("test_data/notebook.ipynb", None),  # supported, for contrast
        ("README.md", "Markdown"),
        ("test_data/test.rst", "reStructuredText"),
    ],
)
def test_lines_only_for_supported_formats(path, format_name):
    result = _run(path, "--lines", "1:2")
    if format_name is None:
        assert result.exit_code == 0, result.output
    else:
        assert result.exit_code != 0
        assert " ".join(result.output.split()) == (
            "--lines only works with CSV, text / code and notebook files, "
            f"not {format_name}"
        )


def test_lines_on_json_is_an_error(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"a": 1}')
    result = _run(str(path), "--lines", "1:2")
    assert result.exit_code != 0
    assert " ".join(result.output.split()).endswith("not JSON")


@pytest.mark.parametrize("other", [["--head", "3"], ["--tail", "3"]])
def test_lines_cannot_be_combined_with_head_or_tail(other):
    result = _run(DENIRO, "--lines", "1:5", *other)
    assert result.exit_code != 0
    assert "cannot combine --lines" in result.output
