import logging
import threading
import time

import cloudscraper
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

BGG_BASE = "https://boardgamegeek.com"

_JSON_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

_ARTICLES_PAGE_SIZE = 100


def _is_retryable(exc: BaseException) -> bool:
    import requests
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code in {429, 500, 502, 503, 504}
    return False


class AuthError(Exception):
    pass


class BGGClient:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.session = cloudscraper.create_scraper()
        self.session.headers.update(_JSON_HEADERS)
        self._user_cache: dict[int, str] = {}
        self._last_request_time: float = 0.0
        self._lock = threading.Lock()

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

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{BGG_BASE}{path}"
        with self._lock:
            self._rate_limit()
            log.debug("GET %s params=%s", url, params)
            resp = self.session.get(url, params=params, timeout=30)
            self._last_request_time = time.monotonic()
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
        """Return username for a user ID, with in-process caching."""
        if user_id not in self._user_cache:
            try:
                data = self._get_json(f"/api/user/{user_id}", {})
                self._user_cache[user_id] = data.get("username", str(user_id))
            except Exception:
                self._user_cache[user_id] = str(user_id)
        return self._user_cache[user_id]

    def prefetch_usernames(self, user_ids: set[int]) -> None:
        """Resolve and cache usernames for all given IDs (skips already-cached)."""
        for uid in user_ids - self._user_cache.keys():
            self.get_username(uid)
