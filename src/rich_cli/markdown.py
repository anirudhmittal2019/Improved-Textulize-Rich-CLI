from typing import Any, Dict, List, NamedTuple, Tuple

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Markdown, TextElement
from rich.padding import Padding
from rich.syntax import Syntax


class CodeBlock(TextElement):
    """A code block with syntax highlighting."""

    style_name = "markdown.code_block"

    @classmethod
    def create(cls, markdown: "Markdown", node: Any) -> "CodeBlock":
        node_info = node.info or ""
        lexer_name = node_info.partition(" ")[0]
        return cls(lexer_name or "default", markdown.code_theme)

    def __init__(self, lexer_name: str, theme: str) -> None:
        self.lexer_name = lexer_name
        self.theme = theme

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        code = str(self.text).rstrip()
        syntax = Syntax(code, self.lexer_name, theme=self.theme, word_wrap=True)
        yield Padding(syntax, (0, 4))


Markdown.elements["code_block"] = CodeBlock


class Heading(NamedTuple):
    """A top level heading in a Markdown document."""

    level: int
    """Heading level, 1 for `#`, 2 for `##` etc."""
    title: str
    """Plain text of the heading (without markup)."""
    line: int
    """0-based index of the first source line of the heading."""


class SectionNotFound(Exception):
    """Raised when a requested section does not exist."""

    def __init__(self, section: str, headings: List[Heading]) -> None:
        self.section = section
        self.headings = headings
        super().__init__(f"no section with heading {section!r}")


def _split_lines(markup: str) -> List[str]:
    """Split lines the same way CommonMark parsers do (so line numbers agree)."""
    return markup.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _normalize(title: str) -> str:
    return " ".join(title.split()).casefold()


# Link reference definitions, maps label on to (destination, title)
References = Dict[str, Tuple[str, str]]


def _parse_markdown_it(markup: str) -> Tuple[List[Heading], References]:
    from markdown_it import MarkdownIt

    env: dict = {}
    tokens = MarkdownIt().parse(markup, env)
    headings: List[Heading] = []
    for token, inline in zip(tokens, tokens[1:]):
        # level 0 == not nested inside a block quote, list etc.
        if token.type != "heading_open" or token.level != 0 or token.map is None:
            continue
        title = "".join(
            " " if child.type in ("softbreak", "hardbreak") else child.content
            for child in inline.children or []
            if child.type in ("text", "code_inline", "softbreak", "hardbreak")
        )
        headings.append(Heading(int(token.tag[1:]), title.strip(), token.map[0]))
    references = {
        label: (ref.get("href", ""), ref.get("title", "") or "")
        for label, ref in env.get("references", {}).items()
    }
    return headings, references


def _parse_commonmark(markup: str) -> Tuple[List[Heading], References]:
    import commonmark

    parser = commonmark.Parser()
    document = parser.parse(markup)
    headings: List[Heading] = []
    node = document.first_child
    while node is not None:  # Only top level nodes
        if node.t == "heading":
            parts: List[str] = []
            for child, entering in node.walker():
                if not entering:
                    continue
                if child.t in ("text", "code"):
                    parts.append(child.literal)
                elif child.t in ("softbreak", "linebreak"):
                    parts.append(" ")
            headings.append(
                Heading(node.level, "".join(parts).strip(), node.sourcepos[0][0] - 1)
            )
        node = node.nxt
    references = {
        label: (ref.get("destination", ""), ref.get("title", "") or "")
        for label, ref in parser.refmap.items()
    }
    return headings, references


def _parse(markup: str) -> Tuple[List[Heading], References]:
    """Get the top level headings and link reference definitions.

    Uses a real CommonMark parser rather than looking for lines starting with
    "#", so code blocks, setext (underlined) headings etc. are handled the same
    way as when Rich renders them. Prefers markdown-it-py (which Rich >= 13
    uses) and falls back to commonmark (which Rich < 13 uses).
    """
    try:
        import markdown_it  # noqa: F401
    except ImportError:
        return _parse_commonmark(markup)
    return _parse_markdown_it(markup)


def get_headings(markup: str) -> List[Heading]:
    """Get the top level headings in a Markdown document."""
    headings, _references = _parse(markup)
    return headings


def _format_reference(label: str, destination: str, title: str) -> str:
    """Format a link reference definition, e.g. `[label]: <url> "title"`."""
    label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    destination = destination.replace("<", "%3C").replace(">", "%3E")
    definition = f"[{label}]: <{destination}>"
    if title:
        title = title.replace("\\", "\\\\").replace('"', '\\"')
        definition += f' "{title}"'
    return definition


def extract_section(markup: str, section: str) -> str:
    """Extract a single section from a Markdown document.

    The section starts at the first heading whose text matches `section`
    (case insensitive, ignoring inline markup) and continues up to the next
    heading of the same or a higher level, so sub-sections are included.

    Raises:
        SectionNotFound: If there is no heading matching `section`.
    """
    headings, references = _parse(markup)
    wanted = _normalize(section)
    for index, heading in enumerate(headings):
        # A blank name never matches, not even an empty heading (a lone "#")
        if wanted and _normalize(heading.title) == wanted:
            break
    else:
        raise SectionNotFound(section, headings)

    end_line = None
    for next_heading in headings[index + 1 :]:
        if next_heading.level <= heading.level:
            end_line = next_heading.line
            break

    lines = _split_lines(markup)[heading.line : end_line]
    section_markup = "\n".join(lines).rstrip() + "\n"
    if references:
        # Links such as [text][label] may be defined elsewhere in the document
        # (often at the end), so carry the definitions over to the section.
        # Definitions within the section still take priority, as the first
        # definition of a label wins.
        section_markup += "\n" + "\n".join(
            _format_reference(label, destination, title)
            for label, (destination, title) in references.items()
        )
        section_markup += "\n"
    return section_markup
