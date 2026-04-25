import json
import logging
import threading
import time
from concurrent.futures import Executor
from pathlib import Path

import cloudscraper
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)

log = logging.getLogger(__name__)

BGG_BASE = "https://boardgamegeek.com"

_JSON_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

_ARTICLES_PAGE_SIZE = 100
_MAX_BACKOFF = 60.0
_BACKOFF_BASE = 2.0


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def _retry_wait(retry_state) -> float:
    """Tenacity wait callback: honour Retry-After when present, else exponential backoff."""
    attempt = getattr(retry_state, "attempt_number", 1) or 1
    backoff = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _MAX_BACKOFF)

    outcome = getattr(retry_state, "outcome", None)
    if outcome is None:
        return backoff

    exc = outcome.exception()
    if isinstance(exc, requests.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is not None:
            ra = resp.headers.get("Retry-After")
            if ra is not None:
                try:
                    return min(float(ra), _MAX_BACKOFF)
                except (TypeError, ValueError):
                    pass
    return backoff


class AuthError(Exception):
    pass


class BGGClient:
    def __init__(
        self,
        delay: float = 1.0,
        user_cache_path: str | Path | None = None,
    ):
        self.delay = delay
        self.session = cloudscraper.create_scraper()
        self.session.headers.update(_JSON_HEADERS)

        # Token-bucket rate limiter — reserves a slot then releases the lock,
        # so concurrent requests get spaced timestamps instead of being serialized.
        self._rate_lock = threading.Lock()
        self._next_slot: float = time.monotonic()

        # Username cache (in-process + optional persistent file).
        self._user_cache: dict[int, str] = {}
        self._user_cache_lock = threading.Lock()
        self._user_cache_path: Path | None = (
            Path(user_cache_path) if user_cache_path is not None else None
        )
        self._user_cache_dirty = False
        if self._user_cache_path is not None:
            self._load_user_cache()

    def login(self, username: str, password: str) -> None:
        """Authenticate with BGG and store the session cookie."""
        log.debug("POST %s/login/api/v1 (username=%s)", BGG_BASE, username)
        resp = self.session.post(
            f"{BGG_BASE}/login/api/v1",
            json={"credentials": {"username": username, "password": password}},
            headers={
                "Content-Type": "application/json",
                "Origin": BGG_BASE,
                "Referer": f"{BGG_BASE}/login",
            },
            timeout=30,
        )
        log.debug("Login response: HTTP %s", resp.status_code)
        if not resp.ok:
            try:
                msg = resp.json().get("errors", {}).get("message", resp.text)
            except Exception:
                msg = resp.text
            raise AuthError(f"BGG login failed ({resp.status_code}): {msg}")

    def _acquire_slot(self) -> None:
        """Reserve the next request slot under the configured delay, then sleep until it."""
        if self.delay <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.delay
        wait = slot - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=_retry_wait,
        stop=stop_after_attempt(5),
        reraise=True,
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{BGG_BASE}{path}"
        self._acquire_slot()
        log.debug("GET %s params=%s", url, params)
        resp = self.session.get(url, params=params, timeout=30)
        log.debug("Response: HTTP %s (%d bytes)", resp.status_code, len(resp.content))
        resp.raise_for_status()
        data = resp.json()
        if not data:
            log.warning("Empty JSON response from %s params=%s", url, params)
        return data

    def search_games(self, query: str, limit: int = 10) -> list[dict]:
        """Search BGG for board games by name. Returns list of {id, name, year} dicts."""
        data = self._get_json("/search/boardgame", {"q": query, "nosession": 1})
        results = []
        for item in data.get("items", [])[:limit]:
            results.append(
                {
                    "id": int(item["objectid"]),
                    "name": item.get("name", ""),
                    "year": item.get("yearpublished"),
                    "href": item.get("href", ""),
                }
            )
        return results

    def get_game_forums(self, game_id: int) -> list[dict]:
        """List all forums for a game. Returns list of {id, title, numthreads} dicts."""
        data = self._get_json("/api/forum", {"objecttype": "thing", "objectid": game_id})
        return [
            {
                "id": int(f["forumid"]),
                "title": f.get("title", ""),
                "num_threads": int(f.get("numthreads", 0)),
            }
            for f in data.get("forums", [])
        ]

    def get_forum_threads_page(
        self,
        objectid: int,
        forumid: int,
        page: int = 1,
    ) -> dict:
        return self._get_json(
            "/api/forums/threads",
            {
                "objecttype": "thing",
                "objectid": objectid,
                "forumid": forumid,
                "sort": "recent",
                "pageid": page,   # BGG uses 'pageid', not 'page'
            },
        )

    def get_thread_articles(self, thread_id: int, page: int = 1) -> dict:
        return self._get_json(
            "/api/article",
            {
                "threadid": thread_id,
                "count": _ARTICLES_PAGE_SIZE,
                "page": page,
            },
        )

    def get_username(self, user_id: int) -> str:
        """Return username for a user ID, caching the result in-process."""
        with self._user_cache_lock:
            cached = self._user_cache.get(user_id)
        if cached is not None:
            return cached

        try:
            data = self._get_json(f"/api/user/{user_id}", {})
            username = data.get("username", str(user_id))
        except Exception:
            username = str(user_id)

        with self._user_cache_lock:
            self._user_cache[user_id] = username
            self._user_cache_dirty = True
        return username

    def prefetch_usernames(
        self,
        user_ids: set[int],
        executor: Executor | None = None,
    ) -> None:
        """Resolve and cache usernames for all given IDs, skipping ones already cached."""
        with self._user_cache_lock:
            missing = {uid for uid in user_ids if uid not in self._user_cache}
        if not missing:
            return
        if executor is None:
            for uid in missing:
                self.get_username(uid)
            return
        futures = [executor.submit(self.get_username, uid) for uid in missing]
        for f in futures:
            f.result()

    def _load_user_cache(self) -> None:
        """Load the persistent username cache. Silent on missing/malformed files."""
        if self._user_cache_path is None:
            return
        try:
            raw = self._user_cache_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (FileNotFoundError, OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        loaded: dict[int, str] = {}
        for k, v in data.items():
            try:
                loaded[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        with self._user_cache_lock:
            self._user_cache.update(loaded)
            self._user_cache_dirty = False

    def save_user_cache(self) -> None:
        """Persist the username cache to disk if it has changed."""
        if self._user_cache_path is None:
            return
        with self._user_cache_lock:
            if not self._user_cache_dirty:
                return
            payload = {str(k): v for k, v in self._user_cache.items()}
            self._user_cache_dirty = False
        path = self._user_cache_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
