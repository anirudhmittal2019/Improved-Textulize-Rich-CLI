import pytest
from click.testing import CliRunner

from rich_cli import markdown as rich_markdown
from rich_cli.markdown import SectionNotFound, extract_section

DOC = """\
Some text before any heading.

# Intro

Welcome.

```bash
# this is a comment, not a heading
pip install rich-cli
```

Setup
=====

Install it.

## Setup *on Windows*

Use `pip`.

> # Quoted heading, not a section

# Usage

Use it.

## Setup

A second, nested "Setup" heading.
"""


def _use_commonmark(monkeypatch):
    pytest.importorskip("commonmark")
    monkeypatch.setattr(rich_markdown, "_parse_markdown_it", None)
    monkeypatch.setattr(
        rich_markdown, "_parse", lambda markup: rich_markdown._parse_commonmark(markup)
    )


def _use_markdown_it(monkeypatch):
    pytest.importorskip("markdown_it")
    monkeypatch.setattr(
        rich_markdown, "_parse", lambda markup: rich_markdown._parse_markdown_it(markup)
    )


# Run every test against both parsers (Rich < 13 uses commonmark, >= 13 markdown-it)
@pytest.fixture(
    params=[_use_commonmark, _use_markdown_it], ids=["commonmark", "markdown-it"]
)
def parser(request, monkeypatch):
    request.param(monkeypatch)


def test_section_includes_subsections_and_stops_at_next_heading(parser):
    section = extract_section(DOC, "Setup")
    assert section.startswith("Setup\n=====\n")
    assert "## Setup *on Windows*" in section
    assert "> # Quoted heading" in section
    assert "# Usage" not in section
    assert "Welcome" not in section


def test_hash_in_code_block_is_not_a_heading(parser):
    section = extract_section(DOC, "intro")
    assert "# this is a comment, not a heading" in section
    assert "pip install rich-cli" in section
    assert "Install it." not in section


def test_match_ignores_case_whitespace_and_inline_markup(parser):
    section = extract_section(DOC, "  setup   ON windows ")
    assert (
        section
        == "## Setup *on Windows*\n\nUse `pip`.\n\n> # Quoted heading, not a section\n"
    )


def test_last_section_runs_to_end_of_document(parser):
    section = extract_section(DOC, "Usage")
    assert section.startswith("# Usage")
    assert section.rstrip().endswith('A second, nested "Setup" heading.')


def test_first_matching_heading_wins(parser):
    assert extract_section(DOC, "setup").startswith("Setup\n=====")


def test_quoted_heading_is_not_a_section(parser):
    with pytest.raises(SectionNotFound):
        extract_section(DOC, "Quoted heading, not a section")


def test_section_not_found_lists_headings(parser):
    with pytest.raises(SectionNotFound) as error:
        extract_section(DOC, "Nope")
    assert [(h.level, h.title) for h in error.value.headings] == [
        (1, "Intro"),
        (1, "Setup"),
        (2, "Setup on Windows"),
        (1, "Usage"),
        (2, "Setup"),
    ]


def test_windows_line_endings(parser):
    section = extract_section(DOC.replace("\n", "\r\n"), "Usage")
    assert section.startswith("# Usage\n\nUse it.")


def test_reference_links_defined_elsewhere_are_kept(parser):
    doc = (
        "# Setup\n\nSee [the docs][docs], [wiki] and [dup].\n\n"
        "[dup]: https://example.com/mine\n\n"
        "# Other\n\n"
        '[docs]: https://example.com/docs "The \\"best\\" docs"\n'
        "[wiki]: https://en.wikipedia.org/wiki/Foo_(bar)\n"
        "[dup]: https://example.com/not-mine\n"
    )
    section = extract_section(doc, "Setup")
    assert "# Other" not in section
    # Re-parse the extracted section to check every link still resolves correctly
    _, references = rich_markdown._parse(section)
    references = {label.strip("[]").lower(): ref for label, ref in references.items()}
    assert references == {
        "docs": ("https://example.com/docs", 'The "best" docs'),
        "wiki": ("https://en.wikipedia.org/wiki/Foo_(bar)", ""),
        "dup": ("https://example.com/mine", ""),
    }


def _run(*args):
    from rich_cli.__main__ import main

    return CliRunner().invoke(main, [*args, "--width", "100"])


@pytest.fixture
def doc_path(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(DOC)
    return str(path)


def test_cli_section(doc_path):
    result = _run(doc_path, "--section", "Usage")
    assert result.exit_code == 0, result.output
    assert "Use it." in result.output
    assert "Install it." not in result.output
    assert "Welcome." not in result.output


def test_cli_section_not_found(doc_path):
    result = _run(doc_path, "--section", "Nope")
    assert result.exit_code != 0
    assert " ".join(result.output.split()) == "No such section found: 'Nope'"
    # Nothing from the document is printed, including its other headings
    assert "Intro" not in result.output
    assert "Setup" not in result.output


@pytest.mark.parametrize(
    "path, format_name",
    [
        ("test_data/deniro.csv", "CSV"),
        ("test_data/notebook.ipynb", "Jupyter notebooks"),
        ("test_data/test.rst", "reStructuredText"),
    ],
)
def test_cli_section_requires_markdown(path, format_name):
    result = _run(path, "--section", "Intro")
    assert result.exit_code != 0
    assert (
        " ".join(result.output.split())
        == f"--section only works with Markdown files, not {format_name}"
    )


def test_cli_section_on_json(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"a": 1}')
    result = _run(str(path), "--section", "Intro")
    assert result.exit_code != 0
    assert (
        " ".join(result.output.split())
        == "--section only works with Markdown files, not JSON"
    )


def test_cli_section_on_text_file_suggests_markdown(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("# Intro\n\nHello\n")
    result = _run(str(path), "--section", "Intro")
    assert result.exit_code != 0
    assert "use -m to read this as Markdown" in result.output
    # ...and following that advice works
    result = _run(str(path), "-m", "--section", "Intro")
    assert result.exit_code == 0, result.output
    assert "Hello" in result.output


# --- Case sensitivity & whitespace ---------------------------------------------
# Rule: case, surrounding / repeated whitespace and inline markup are ignored,
# otherwise the heading text must match exactly (no partial matches).

MATCHING_DOC = """\
# Intro

Intro body.

#    Setup   ##

Setup body.

# Usage  Guide

Usage body.

# Straße

Street body.

# **Bold** `code` [Link](https://example.com)

Markup body.

# Q&amp;A

QA body.

#

Under an empty heading.
"""


@pytest.mark.parametrize(
    "query, expected_body",
    [
        ("Setup", "Setup body."),
        ("setup", "Setup body."),
        ("SETUP", "Setup body."),
        ("sEtUp", "Setup body."),
        (" Setup ", "Setup body."),
        ("   setup\t", "Setup body."),
        ("\nSetup\n", "Setup body."),
        ("usage guide", "Usage body."),
        ("usage     guide", "Usage body."),
        ("usage\tguide", "Usage body."),
        ("STRASSE", "Street body."),  # full Unicode case folding
        ("straße", "Street body."),
        ("bold code link", "Markup body."),  # inline markup is ignored
        ("Q&A", "QA body."),  # entities are matched as displayed
    ],
)
def test_section_matching(parser, query, expected_body):
    section = extract_section(MATCHING_DOC, query)
    bodies = [line for line in section.splitlines() if line.endswith("body.")]
    assert bodies == [expected_body]


@pytest.mark.parametrize(
    "query",
    [
        "Set",  # no partial matches
        "Setup body",
        "usageguide",  # words must stay separated
        "Setup ##",
        "# Setup",  # the "#" is not part of the heading text
        "Q&amp;A",
        "**Bold** `code` [Link](https://example.com)",
        "",  # blank names never match, not even the empty "#" heading
        "   ",
        "\t",
    ],
)
def test_section_not_matching(parser, query):
    with pytest.raises(SectionNotFound):
        extract_section(MATCHING_DOC, query)


@pytest.mark.parametrize("query", ["", " ", "\t"])
def test_cli_blank_section_is_an_error(doc_path, query):
    result = _run(doc_path, "--section", query)
    assert result.exit_code != 0
    assert (
        " ".join(result.output.split())
        == '--section needs a heading name, e.g. --section "Setup"'
    )


# --- "#" lines inside code blocks are not headings ------------------------------

CODE_DOC = """\
# Backticks

```python
#!/usr/bin/env python
# backtick comment
## backtick double
Fake setext
===========
```

After backticks.

# Tildes

~~~python
# tilde comment
~~~

After tildes.

# Long fence

````markdown
```python
# nested comment
```
# still inside long fence
````

After long fence.

# Indented fence

   ```
   # indented fence comment
   ```

After indented fence.

# Indented code

Some text:

    # indented code comment

After indented code.

# List code

- Step one:

  ```bash
  # list code comment
  ```

After list code.

# Quoted code

> ```python
> # quoted comment
> ```

After quoted code.

# Mismatched

```python
# mismatched comment
~~~
# still in mismatched code
```

After mismatched.

# Unclosed

```python
# unclosed comment

# Later
"""

CODE_COMMENTS = [
    "#!/usr/bin/env python",
    "backtick comment",
    "backtick double",
    "Fake setext",
    "tilde comment",
    "nested comment",
    "still inside long fence",
    "indented fence comment",
    "indented code comment",
    "list code comment",
    "quoted comment",
    "mismatched comment",
    "still in mismatched code",
    "unclosed comment",
    # An unclosed fence runs to the end of the document (Rich renders this as code)
    "Later",
]


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_code_block_comments_are_not_headings(parser, line_ending):
    doc = CODE_DOC.replace("\n", line_ending)
    titles = [heading.title for heading in rich_markdown.get_headings(doc)]
    assert titles == [
        "Backticks",
        "Tildes",
        "Long fence",
        "Indented fence",
        "Indented code",
        "List code",
        "Quoted code",
        "Mismatched",
        "Unclosed",
    ]
    for comment in CODE_COMMENTS:
        with pytest.raises(SectionNotFound):
            extract_section(doc, comment)


@pytest.mark.parametrize(
    "section, next_section, comments",
    [
        ("Backticks", "Tildes", ["# backtick comment", "## backtick double"]),
        ("Tildes", "Long fence", ["# tilde comment"]),
        ("Long fence", "Indented fence", ["# nested comment", "# still inside"]),
        ("Indented fence", "Indented code", ["# indented fence comment"]),
        ("Indented code", "List code", ["# indented code comment"]),
        ("List code", "Quoted code", ["# list code comment"]),
        ("Quoted code", "Mismatched", ["# quoted comment"]),
        ("Mismatched", "Unclosed", ["# mismatched comment", "# still in mismatched"]),
    ],
)
def test_code_block_comments_do_not_cut_sections_short(
    parser, section, next_section, comments
):
    extracted = extract_section(CODE_DOC, section)
    for comment in comments:
        assert comment in extracted
    assert f"After {section.lower()}." in extracted  # text after the code block
    assert f"# {next_section}" not in extracted  # ...and stops at the next heading


def test_cli_code_block_comment_is_not_a_section(tmp_path):
    path = tmp_path / "code.md"
    path.write_text(CODE_DOC)
    result = _run(str(path), "--section", "backtick comment")
    assert result.exit_code != 0
    assert (
        " ".join(result.output.split()) == "No such section found: 'backtick comment'"
    )

    result = _run(str(path), "--section", "Backticks")
    assert result.exit_code == 0, result.output
    assert "# backtick comment" in result.output
    assert "After backticks." in result.output
    assert "tilde comment" not in result.output


# --- Combining --section with --lines / --head / --tail -------------------------


@pytest.mark.parametrize(
    "args, flag",
    [
        (["README.md", "--section", "Installation", "--lines", "1:5"], "--lines"),
        (["README.md", "--lines", "1:5", "--section", "Installation"], "--lines"),
        (["test_data/deniro.csv", "--section", "Setup", "--lines", "1:5"], "--lines"),
        (["README.md", "-m", "--section", "Installation", "--lines", "1:5"], "--lines"),
        # reported even when the values themselves are also invalid
        (["README.md", "--section", "", "--lines", "abc"], "--lines"),
        (["README.md", "--section", "Installation", "--head", "3"], "--head"),
        (["README.md", "--section", "Installation", "--tail", "3"], "--tail"),
    ],
)
def test_cli_section_cannot_be_combined(args, flag):
    result = _run(*args)
    assert result.exit_code != 0
    assert " ".join(result.output.split()) == f"--section can't be combined with {flag}"


def test_cli_section_and_lines_still_work_separately():
    result = _run("README.md", "--section", "Installation")
    assert result.exit_code == 0, result.output
    assert "pipx install rich-cli" in result.output

    result = _run("test_data/deniro.csv", "--lines", "1:2")
    assert result.exit_code == 0, result.output
    assert "Greetings" in result.output and "Bloody Mama" in result.output
