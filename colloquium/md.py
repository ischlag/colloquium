"""Shared markdown-it configuration.

Every renderer in colloquium (main slide pipeline and block elements like box
and conversation) should build on this base so typography is consistent:
smart quotes, en/em dashes from ``--``/``---``, and table support everywhere.
"""

from markdown_it import MarkdownIt


def create_base_md() -> MarkdownIt:
    """Return a markdown-it renderer with the deck's shared typography."""
    md = MarkdownIt("commonmark", {"html": True, "typographer": True})
    md.enable(["table", "replacements", "smartquotes"])
    return md
