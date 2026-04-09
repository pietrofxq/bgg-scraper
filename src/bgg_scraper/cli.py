import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import click
from dotenv import load_dotenv

load_dotenv()  # loads .env from project root (or any parent dir)
from tqdm import tqdm

from .client import AuthError, BGGClient
from .formatter import output_filename, slug, thread_to_markdown
from .parser import parse_articles, parse_forum_threads_page

# ── Shared auth options ────────────────────────────────────────────────────────

_auth_options = [
    click.option(
        "--username", "-u",
        envvar="BGG_USERNAME",
        prompt="BGG username",
        show_envvar=True,
        help="BGG username. Falls back to BGG_USERNAME or an interactive prompt.",
    ),
    click.option(
        "--password", "-p",
        envvar="BGG_PASSWORD",
        prompt="BGG password",
        hide_input=True,
        show_envvar=True,
        help="BGG password. Falls back to BGG_PASSWORD or a hidden interactive prompt.",
    ),
]


def _add_auth(f):
    for opt in reversed(_auth_options):
        f = opt(f)
    return f


def _login(username: str, password: str, delay: float = 1.0) -> BGGClient:
    client = BGGClient(delay=delay)
    try:
        client.login(username, password)
    except AuthError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    return client


# ── URL parsing ────────────────────────────────────────────────────────────────

def _parse_forum_url(url: str) -> tuple[int, int, str]:
    """Return (game_id, forum_id, game_slug) from a BGG forum URL."""
    m = re.search(r"/boardgame/(\d+)/([^/]+)/forums/(\d+)", url)
    if not m:
        raise click.BadParameter(
            f"Could not parse game ID and forum ID from: {url}\n"
            "Expected: https://boardgamegeek.com/boardgame/<game_id>/<slug>/forums/<forum_id>"
        )
    return int(m.group(1)), int(m.group(3)), m.group(2)


def _parse_thread_url(url: str) -> int:
    """Return thread_id from a BGG thread URL."""
    m = re.search(r"/thread/(\d+)", url)
    if not m:
        raise click.BadParameter(
            f"Could not parse thread ID from: {url}\n"
            "Expected: https://boardgamegeek.com/thread/<thread_id>/..."
        )
    return int(m.group(1))


def _thread_subject_hint(url: str) -> str:
    """Return a best-effort subject hint from a canonical thread URL slug."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 3 or path_parts[0] != "thread":
        return ""

    slug_part = path_parts[2]
    if slug_part == "article":
        return ""

    words = [word for word in unquote(slug_part).strip("-").split("-") if word]
    return " ".join(word.capitalize() for word in words)


_log = logging.getLogger(__name__)


def _write_text_atomic(dest: Path, content: str) -> None:
    """Write text to a file atomically so interrupted runs do not leave partial output."""
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_name = tmp.name
        os.replace(tmp_name, dest)
    except Exception:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        raise


def _fetch_thread(client: BGGClient, thread_id: int, subject: str = "") -> object:
    """Fetch all articles for a thread (handles pagination) and return a Thread."""
    all_articles: list[dict] = []
    art_page = 1
    total: int | None = None
    while True:
        _log.debug("Fetching thread %d articles page %d", thread_id, art_page)
        art_data = client.get_thread_articles(thread_id, page=art_page)
        page_articles = art_data.get("articles", [])

        if not page_articles and art_page == 1:
            click.echo(
                f"Warning: thread {thread_id} ({subject!r}) returned 0 articles.", err=True
            )

        if total is None and art_data.get("total") is not None:
            total = int(art_data["total"])
            _log.debug("Thread %d: API reports %d total articles", thread_id, total)

        all_articles.extend(page_articles)
        _log.debug(
            "Thread %d page %d: got %d articles (%d/%s collected)",
            thread_id, art_page, len(page_articles), len(all_articles), total,
        )

        if not page_articles:
            break
        if total is not None and len(all_articles) >= total:
            break
        # Fallback: last page has fewer articles than the page size
        per_page = int(art_data.get("perPage", 100))
        if len(page_articles) < per_page:
            break

        art_page += 1
    _log.debug("Thread %d: %d total articles across %d page(s)", thread_id, len(all_articles), art_page)
    return parse_articles(
        thread_id, subject,
        {"articles": all_articles, "total": len(all_articles)},
        client=client,
    )


# ── CLI group ─────────────────────────────────────────────────────────────────

class _TqdmHandler(logging.StreamHandler):
    """Log handler that writes via tqdm.write() to avoid clobbering progress bars."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:
            self.handleError(record)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    handler = _TqdmHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level, handlers=[handler])


@click.group()
def main() -> None:
    """BGG Forum Scraper — download forum threads as Markdown files."""


# ── search command ────────────────────────────────────────────────────────────

@main.command("search")
@_add_auth
@click.argument("query")
@click.option("--delay", "-d", default=1.0, show_default=True, type=float,
              help="Seconds to wait between API requests.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Enable debug logging.")
def search_cmd(query: str, username: str, password: str, delay: float, verbose: bool) -> None:
    """Search BGG for a game and list its forums with scrape-ready URLs.

    Example: bgg-scraper search "quest for the lost pixel"
    """
    _configure_logging(verbose)
    click.echo("Logging in to BGG...")
    client = _login(username, password, delay)
    click.echo("Logged in.\n")

    results = client.search_games(query, limit=5)
    if not results:
        click.echo("No games found.")
        return

    for game in results:
        year = f" ({game['year']})" if game['year'] else ""
        click.echo(f"[{game['id']}] {game['name']}{year}")

        try:
            forums = client.get_game_forums(game["id"])
        except Exception:
            click.echo("  (could not fetch forums)")
            continue

        game_slug_str = re.sub(r"[^a-z0-9]+", "-", game["name"].lower()).strip("-")
        for forum in forums:
            if forum["num_threads"] == 0:
                continue
            url = (
                f"https://boardgamegeek.com/boardgame/{game['id']}"
                f"/{game_slug_str}/forums/{forum['id']}"
            )
            click.echo(f"  {forum['title']:20s} ({forum['num_threads']:3d} threads) → {url}")
        click.echo()


# ── scrape command ────────────────────────────────────────────────────────────

@main.command("scrape")
@_add_auth
@click.argument("url", required=False, default=None)
@click.option("--game-id", "-g", default=None, type=int, envvar="BGG_GAME_ID",
              help="BGG game ID (alternative to passing a full URL).")
@click.option("--forum-id", "-f", default=None, type=int, envvar="BGG_FORUM_ID",
              help="BGG forum ID (alternative to passing a full URL).")
@click.option("--output-dir", "-o", default="output", show_default=True,
              help="Root directory for output; files go into <output>/<game>/<forum>/.")
@click.option("--delay", "-d", default=1.0, show_default=True, type=float,
              help="Seconds to wait between API requests.")
@click.option("--max-threads", "-n", default=None, type=int,
              help="Limit number of threads to fetch (useful for testing).")
@click.option("--designer", default=None, envvar="BGG_DESIGNER",
              help="BGG username of the game designer (or set BGG_DESIGNER env var). Their replies are marked '— Designer'.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Enable debug logging.")
def scrape_cmd(
    url: str | None,
    game_id: int | None,
    forum_id: int | None,
    username: str,
    password: str,
    output_dir: str,
    delay: float,
    max_threads: int | None,
    designer: str | None,
    verbose: bool,
) -> None:
    """Scrape a BGG forum and write each thread as a Markdown file.

    Files are saved to: <output-dir>/<game-slug>/<forum-title>/<thread>.md

    Pass either a full forum URL:

      bgg-scraper scrape https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66

    Or use --game-id / --forum-id directly:

      bgg-scraper scrape --game-id 307161 --forum-id 66

    Use `bgg-scraper search <game name>` to discover IDs.

    Credentials can also be supplied via BGG_USERNAME / BGG_PASSWORD env vars.
    """
    if url:
        try:
            game_id, forum_id, game_slug = _parse_forum_url(url)
        except click.BadParameter as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
    elif game_id is not None and forum_id is not None:
        game_slug = str(game_id)
    else:
        click.echo(
            "Error: provide either a forum URL or both --game-id and --forum-id.", err=True
        )
        sys.exit(1)

    _configure_logging(verbose)
    click.echo("Logging in to BGG...")
    client = _login(username, password, delay)
    click.echo("Logged in.")

    # --- Collect all thread stubs via pagination ---
    click.echo(f"Fetching thread list for game {game_id}, forum {forum_id}...")
    all_stubs: list[dict] = []
    seen_ids: set[int] = set()
    page = 1
    end_page: int | None = None
    forum_title = ""

    with tqdm(desc="Pages", unit="page") as pbar:
        while True:
            data = client.get_forum_threads_page(game_id, forum_id, page=page)
            forum_page = parse_forum_threads_page(data, game_id, forum_id)

            if end_page is None:
                end_page = forum_page.end_page
                forum_title = forum_page.title
                click.echo(f"Forum: {forum_title!r} — {forum_page.num_threads} threads total")

            for stub in forum_page.threads:
                if stub["id"] not in seen_ids:
                    seen_ids.add(stub["id"])
                    all_stubs.append(stub)
            pbar.update(1)

            if page >= end_page or not forum_page.threads:
                break
            page += 1

    if not all_stubs:
        click.echo("Warning: no threads found for this forum.", err=True)
        return

    if max_threads is not None:
        all_stubs = all_stubs[:max_threads]

    # Output directory: <base>/<game-slug>/<forum-slug>/
    forum_slug_str = slug(forum_title) or f"forum-{forum_id}"
    out_path = Path(output_dir) / game_slug / forum_slug_str
    out_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"Fetching {len(all_stubs)} thread(s) → {out_path}/")

    # --- Fetch each thread's articles and write to .md ---
    start = time.time()
    written = skipped = 0

    for stub in tqdm(all_stubs, desc="Threads", unit="thread"):
        thread_id = stub["id"]
        subject = stub["subject"]

        # Skip if a file with this thread ID already exists
        existing = list(out_path.glob(f"{thread_id}_*.md"))
        if existing:
            _log.debug("Skipping thread %d — file exists: %s", thread_id, existing[0])
            skipped += 1
            continue

        thread = _fetch_thread(client, thread_id, subject)

        dest = out_path / output_filename(thread)
        _write_text_atomic(dest, thread_to_markdown(thread, designer=designer))
        written += 1

    elapsed = time.time() - start
    click.echo(
        f"\nDone in {elapsed:.1f}s — {written} written, {skipped} skipped (already existed)"
    )


# ── thread command ────────────────────────────────────────────────────────────

@main.command("thread")
@_add_auth
@click.argument("url")
@click.option("--output-dir", "-o", default="output", show_default=True,
              help="Directory to write the .md file into.")
@click.option("--delay", "-d", default=1.0, show_default=True, type=float,
              help="Seconds to wait between API requests.")
@click.option("--designer", default=None, envvar="BGG_DESIGNER",
              help="BGG username of the game designer (or set BGG_DESIGNER env var). Their replies are marked '— Designer'.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Enable debug logging.")
def thread_cmd(
    url: str,
    username: str,
    password: str,
    output_dir: str,
    delay: float,
    designer: str | None,
    verbose: bool,
) -> None:
    """Download a single BGG thread as a Markdown file.

    URL format:
      https://boardgamegeek.com/thread/3006560/article/41505990

    The file is written to <output-dir>/<thread_id>_<slug>.md.

    Canonical thread URLs with a subject slug produce better fallback filenames
    if the article API omits the thread subject.
    """
    try:
        thread_id = _parse_thread_url(url)
    except click.BadParameter as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    _configure_logging(verbose)
    click.echo("Logging in to BGG...")
    client = _login(username, password, delay)
    click.echo("Logged in.")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    existing = list(out_path.glob(f"{thread_id}_*.md"))
    if existing:
        click.echo(f"Skipped — already exists: {existing[0]}")
        return

    click.echo(f"Fetching thread {thread_id}...")
    thread = _fetch_thread(client, thread_id, subject=_thread_subject_hint(url))

    dest = out_path / output_filename(thread)
    _write_text_atomic(dest, thread_to_markdown(thread, designer=designer))
    click.echo(f"Written: {dest}")
