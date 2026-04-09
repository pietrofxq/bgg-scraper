# AGENTS.md — BGG Forum Scraper

Guidelines for AI agents working on this codebase.

## Project Purpose

This tool scrapes BoardGameGeek forum threads into Markdown files. The primary use case is feeding rules Q&A threads into an LLM to generate improved, community-informed rulebooks.

## Architecture Overview

```
URL → client.py (HTTP + auth) → parser.py (JSON → dataclasses) → formatter.py (Markdown) → .md files
```

Key files:
- `bgg_scraper/client.py` — `BGGClient`: login, all API calls, user ID cache
- `bgg_scraper/parser.py` — pure functions: `parse_forum_threads_page`, `parse_articles`
- `bgg_scraper/formatter.py` — pure functions: `thread_to_markdown`, `_bbcode_to_markdown`, `slug`
- `bgg_scraper/models.py` — `Post`, `Thread`, `ForumPage` dataclasses
- `bgg_scraper/cli.py` — click group with `search` and `scrape` subcommands

## BGG API Notes

BGG's public XML API v2 (`/xmlapi2/`) now returns 401 and is unusable. We use the private JSON REST API that powers the BGG website:

| Endpoint | Purpose |
|----------|---------|
| `POST /login/api/v1` | Authenticate; requires `Content-Type: application/json`, `Origin`, `Referer` headers |
| `GET /search/boardgame?q=...` | Search games by name |
| `GET /api/forum?objecttype=thing&objectid={id}` | List forums for a game |
| `GET /api/forums/threads?objecttype=thing&objectid={id}&forumid={id}&sort=recent&count=50&page={n}` | List threads (paginated) |
| `GET /api/article?threadid={id}&count=100&page={n}` | Get thread posts (paginated) |
| `GET /api/user/{id}` | Resolve numeric user ID → username |

BGG uses `cloudscraper` to bypass Cloudflare. The `BGGClient` uses this as its HTTP session.

## Development Rules

### Testing
- Run: `uv run python -m pytest tests/ -v`
- Tests are pure unit tests using fixture dicts (no network calls)
- `test_parser.py` uses in-memory dict fixtures matching real API response structure
- `test_formatter.py` builds `Thread`/`Post` objects directly

### Adding new fields
- Add to `models.py` dataclass first
- Update `parser.py` to extract from JSON
- Update `formatter.py` if it should appear in output
- Add a test assertion

### Rate limiting
- Default 1.0s delay between requests (`--delay` flag)
- `tenacity` retries on 429/5xx with exponential backoff
- Don't remove or bypass rate limiting

### Output format decisions
The Markdown format is intentionally minimal for AI consumption:
- No dates, thread IDs, or BGG footer links
- BBCode converted to Markdown (`[q]` → `>`, `[b]` → `**`, `[i]` → `*`)
- Author names kept (useful for identifying designer answers)
- Unknown BBCode tags stripped

### Credentials
Never hardcode credentials. Tests must not make real network calls. The `.bashrc` must use single-quoted passwords due to special characters.

## Common Tasks

**Add a new BBCode tag**: edit `_bbcode_to_markdown()` in `formatter.py`

**Add a new API method**: add to `BGGClient` in `client.py`, then update parser/CLI as needed

**Change output structure**: edit `thread_to_markdown()` in `formatter.py` and update related tests

**Add a new subcommand**: add `@main.command("name")` in `cli.py` following the pattern of `search_cmd`/`scrape_cmd`
