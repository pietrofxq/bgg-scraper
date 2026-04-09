import re

from .models import Post, Thread


def slug(subject: str) -> str:
    """Convert a thread subject to a safe filename fragment."""
    text = subject.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text[:60].strip("-")


def _format_date(iso_date: str) -> str:
    """Extract YYYY-MM-DD from an ISO 8601 date string."""
    if not iso_date:
        return ""
    return iso_date[:10]


def _bbcode_to_markdown(text: str) -> str:
    """Convert common BGG BBCode tags to Markdown."""
    # Quote blocks: [q="user"]...[/q] or [q]...[/q] → > blockquote
    def _quote(m: re.Match) -> str:
        author = m.group(1)
        content = m.group(2).strip()
        # Prefix every line with >
        quoted = "\n".join(f"> {line}" for line in content.splitlines()) if content else "> "
        return f"> *{author} wrote:*\n{quoted}" if author else quoted

    text = re.sub(r'\[q="([^"]+)"\](.*?)\[/q\]', _quote, text, flags=re.DOTALL)
    text = re.sub(r'\[q\](.*?)\[/q\]', lambda m: "\n".join(f"> {l}" for l in m.group(1).strip().splitlines()), text, flags=re.DOTALL)

    # Bold / italic
    text = re.sub(r'\[b\](.*?)\[/b\]', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'\[i\](.*?)\[/i\]', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'\[u\](.*?)\[/u\]', r'\1', text, flags=re.DOTALL)  # underline → plain

    # Links: [url=...]text[/url] or [url]link[/url]
    text = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', r'[\2](\1)', text, flags=re.DOTALL)
    text = re.sub(r'\[url\](.*?)\[/url\]', r'\1', text, flags=re.DOTALL)

    # Lists
    text = re.sub(r'\[list\]', '', text)
    text = re.sub(r'\[/list\]', '', text)
    text = re.sub(r'\[\*\]', '- ', text)

    # Strip any remaining unknown BBCode tags
    text = re.sub(r'\[/?[a-zA-Z][^\]]*\]', '', text)

    return text


def _clean_body(body: str) -> str:
    """Convert BBCode and normalise whitespace in a plain-text post body."""
    body = _bbcode_to_markdown(body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _format_post(post: Post, label: str, designer: str | None = None) -> str:
    body = _clean_body(post.body)
    is_designer = designer and post.author.lower() == designer.lower()
    if is_designer:
        lines = [
            f"## {label}",
            "",
            "> **[ANSWER FROM GAME DESIGNER — HIGHER PRIORITY]**",
            "",
            f"*{post.author}*",
            "",
            body,
            "",
        ]
    else:
        lines = [f"## {label}", "", f"*{post.author}*", "", body, ""]
    return "\n".join(lines)


def thread_to_markdown(thread: Thread, designer: str | None = None) -> str:
    """Render a Thread to a Markdown string optimised for AI consumption."""
    parts = [
        f"# {thread.subject}",
        "",
        "---",
        "",
    ]

    for i, post in enumerate(thread.posts):
        label = "Question" if i == 0 else f"Reply {i}"
        parts.append(_format_post(post, label, designer=designer))
        parts.append("---")
        parts.append("")

    return "\n".join(parts)


def output_filename(thread: Thread) -> str:
    """Return the output filename for a thread: '{id}_{slug}.md'."""
    s = slug(thread.subject) or "thread"
    return f"{thread.id}_{s}.md"
