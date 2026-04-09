# BGG Forum Scraper

`bgg-scraper` logs into BoardGameGeek, searches for game forums, and exports forum threads to clean Markdown files.

The main use case is turning BGG rules discussions into structured text that is easier to search, summarize, or feed into an LLM.

## What It Does

- Searches BGG for games and prints forum URLs you can scrape directly.
- Scrapes an entire forum into one Markdown file per thread.
- Downloads a single thread when you only need one discussion.
- Preserves simple thread structure: the first post becomes `Question`, later posts become `Reply 1`, `Reply 2`, and so on.
- Optionally highlights replies from the game designer.

## Requirements

- Python 3.10+
- A BoardGameGeek account

This project uses BGG's authenticated web endpoints, so anonymous scraping is not supported.

## Installation

For a local checkout, `uv` is the easiest way to run the CLI:

```bash
uv sync
uv run bgg-scraper --help
```

If you prefer a regular install into your current Python environment:

```bash
python -m pip install .
bgg-scraper --help
```

If you install the tool globally with `uv tool install .`, you can run `bgg-scraper` directly and skip `uv run` in the examples below.

## Credentials

The CLI reads credentials in this order:

1. `BGG_USERNAME` / `BGG_PASSWORD`
2. Interactive prompt

The safest repo-local setup is a `.env` file:

```bash
cp .env.example .env
```

Then edit `.env`:

```dotenv
BGG_USERNAME=your_bgg_username
BGG_PASSWORD=your_bgg_password
BGG_DESIGNER=designer_username
```

`BGG_DESIGNER` is optional. When set, replies from that username are marked as designer answers in the generated Markdown.

The `--password` flag still works, but it is best avoided on shared machines because shell history and process listings can expose it.

## Usage

All examples below use `uv run bgg-scraper ...`. If you installed the command globally, use `bgg-scraper ...` instead.

### Search for a Game

```bash
uv run bgg-scraper search "quest for the lost pixel"
```

Example output:

```text
[307161] Quest for the Lost Pixel (2015)
  Reviews              (  5 threads) -> https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/63
  General              (115 threads) -> https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/65
  Rules                (122 threads) -> https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66
```

### Scrape a Forum by URL

```bash
uv run bgg-scraper scrape \
  "https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66"
```

### Scrape a Forum by IDs

```bash
uv run bgg-scraper scrape --game-id 307161 --forum-id 66
```

This is handy if you want to script runs without storing full forum URLs.

### Download a Single Thread

Canonical thread URLs produce the best fallback filenames:

```bash
uv run bgg-scraper thread \
  "https://boardgamegeek.com/thread/3006560/how-do-i-win"
```

Article URLs also work:

```bash
uv run bgg-scraper thread \
  "https://boardgamegeek.com/thread/3006560/article/41505990"
```

### Useful Flags

| Flag | Applies to | Default | Description |
| --- | --- | --- | --- |
| `-u`, `--username` | all commands | prompt / `BGG_USERNAME` | BGG username |
| `-p`, `--password` | all commands | prompt / `BGG_PASSWORD` | BGG password |
| `-d`, `--delay` | `search`, `scrape`, `thread` | `1.0` | Seconds to wait between requests |
| `-o`, `--output-dir` | `scrape`, `thread` | `output` | Output directory |
| `-n`, `--max-threads` | `scrape` | unlimited | Limit number of threads fetched |
| `-g`, `--game-id` | `scrape` | none | Game ID alternative to a forum URL |
| `-f`, `--forum-id` | `scrape` | none | Forum ID alternative to a forum URL |
| `--designer` | `scrape`, `thread` | `BGG_DESIGNER` / none | Mark replies from the designer |
| `-v`, `--verbose` | all commands | off | Enable debug logging |

## Output Layout

Forum scraping writes files to:

```text
output/<game-slug>/<forum-slug>/<thread-id>_<thread-slug>.md
```

Single-thread downloads write files to:

```text
output/<thread-id>_<thread-slug>.md
```

Example:

```text
output/
  quest-for-the-lost-pixel/
    rules/
      1001_how-do-i-win.md
      1002_second-question.md
```

## Markdown Format

Each exported thread looks like this:

```markdown
# Thread Subject

---

## Question

*author_name*

Question body...

---

## Reply 1

*designer_name*

> *quoted_user wrote:*
> Quoted text...

Reply body...
```

The output is intentionally minimal. It keeps the thread content and quote structure while leaving out extra site chrome.

## Resume Behavior

Re-running the scraper skips threads that already have a matching `thread_id_*.md` file.

Writes are atomic, so an interrupted run should not leave behind a partial Markdown file that gets mistaken for a completed export on the next run.

## Development

Install the project plus test/build dependencies:

```bash
uv sync --extra dev
```

Run the test suite:

```bash
uv run pytest -q
```

Build distribution artifacts:

```bash
uv run python -m build
```

GitHub Actions runs the same checks for pushes and pull requests.

## Limitations

- This depends on BGG's current authenticated web endpoints, which are not a public stable API.
- The CLI may need updates if BGG changes login flow, page structure, or JSON responses.
- Respect BGG's infrastructure. Use a sensible delay and avoid aggressive scraping.
