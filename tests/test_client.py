"""Tests for BGGClient internals: rate limiter, retry wait, username cache."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import requests

from bgg_scraper.client import BGGClient, _retry_wait


# ---------------------------------------------------------------------------
# _retry_wait
# ---------------------------------------------------------------------------

def _retry_state(exc, attempt=1):
    st = MagicMock()
    st.outcome.exception.return_value = exc
    st.attempt_number = attempt
    return st


class TestRetryWait:
    def test_honours_retry_after_seconds(self):
        resp = MagicMock()
        resp.headers = {"Retry-After": "12"}
        assert _retry_wait(_retry_state(requests.HTTPError(response=resp))) == 12.0

    def test_clamps_retry_after_to_max(self):
        resp = MagicMock()
        resp.headers = {"Retry-After": "9999"}
        assert _retry_wait(_retry_state(requests.HTTPError(response=resp))) == 60.0

    def test_malformed_retry_after_falls_back_to_exponential(self):
        resp = MagicMock()
        resp.headers = {"Retry-After": "not-a-number"}
        # attempt 1 → 2.0 * 2^0 = 2.0
        assert _retry_wait(_retry_state(requests.HTTPError(response=resp), attempt=1)) == 2.0

    def test_no_retry_after_uses_exponential(self):
        resp = MagicMock()
        resp.headers = {}
        # attempt 3 → 2.0 * 2^2 = 8.0
        assert _retry_wait(_retry_state(requests.HTTPError(response=resp), attempt=3)) == 8.0

    def test_non_http_error_uses_exponential(self):
        # attempt 2 → 2.0 * 2^1 = 4.0
        assert _retry_wait(_retry_state(requests.ConnectionError(), attempt=2)) == 4.0

    def test_no_outcome_still_returns_wait(self):
        st = MagicMock()
        st.outcome = None
        st.attempt_number = 1
        assert _retry_wait(st) == 2.0


# ---------------------------------------------------------------------------
# _acquire_slot (token-bucket rate limiter)
# ---------------------------------------------------------------------------

def _make_rate_client(delay: float) -> BGGClient:
    """Build a BGGClient without touching the network or creating a scraper."""
    c = BGGClient.__new__(BGGClient)
    c.delay = delay
    c._rate_lock = threading.Lock()
    c._next_slot = time.monotonic()
    return c


class TestAcquireSlot:
    def test_zero_delay_is_noop(self):
        c = _make_rate_client(0.0)
        start = time.monotonic()
        for _ in range(5):
            c._acquire_slot()
        assert time.monotonic() - start < 0.05

    def test_sequential_calls_are_spaced_by_delay(self):
        c = _make_rate_client(0.1)
        start = time.monotonic()
        c._acquire_slot()  # first returns immediately (slot = now)
        c._acquire_slot()  # ~+0.1s
        c._acquire_slot()  # ~+0.2s
        elapsed = time.monotonic() - start
        # Expected ~0.2s; lenient upper bound for CI noise
        assert 0.18 <= elapsed < 0.6, f"elapsed={elapsed}"

    def test_concurrent_reservations_are_spaced(self):
        c = _make_rate_client(0.1)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(lambda _: c._acquire_slot(), range(4)))
        elapsed = time.monotonic() - start
        # 4 slots spaced 0.1s → last finishes at ~0.3s; concurrent acquisition
        # must not collapse to ~0s (regression guard against the old global lock)
        assert 0.25 <= elapsed < 0.7, f"elapsed={elapsed}"


# ---------------------------------------------------------------------------
# persistent username cache
# ---------------------------------------------------------------------------

def _make_cache_client(path):
    c = BGGClient.__new__(BGGClient)
    c.delay = 0
    c._user_cache = {}
    c._user_cache_lock = threading.Lock()
    c._user_cache_path = path
    c._user_cache_dirty = False
    c._rate_lock = threading.Lock()
    c._next_slot = time.monotonic()
    return c


class TestUserCachePersistence:
    def test_load_missing_file_is_silent(self, tmp_path):
        c = _make_cache_client(tmp_path / "missing.json")
        c._load_user_cache()
        assert c._user_cache == {}

    def test_load_malformed_file_is_silent(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not json")
        c = _make_cache_client(p)
        c._load_user_cache()
        assert c._user_cache == {}

    def test_save_and_load_round_trip(self, tmp_path):
        p = tmp_path / "cache.json"
        c = _make_cache_client(p)
        c._user_cache = {1: "alice", 42: "bob"}
        c._user_cache_dirty = True
        c.save_user_cache()
        assert p.exists()

        c2 = _make_cache_client(p)
        c2._load_user_cache()
        assert c2._user_cache == {1: "alice", 42: "bob"}

    def test_save_skips_when_not_dirty(self, tmp_path):
        p = tmp_path / "cache.json"
        c = _make_cache_client(p)
        c._user_cache = {1: "alice"}
        c._user_cache_dirty = False
        c.save_user_cache()
        assert not p.exists()

    def test_save_with_no_path_is_noop(self):
        c = _make_cache_client(None)
        c._user_cache = {1: "alice"}
        c._user_cache_dirty = True
        c.save_user_cache()  # must not raise

    def test_save_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "deep" / "cache.json"
        c = _make_cache_client(p)
        c._user_cache = {1: "alice"}
        c._user_cache_dirty = True
        c.save_user_cache()
        assert p.exists()


# ---------------------------------------------------------------------------
# prefetch_usernames with executor
# ---------------------------------------------------------------------------

class TestPrefetchUsernames:
    def test_skips_already_cached_ids(self):
        c = _make_cache_client(None)
        c._user_cache = {1: "alice", 2: "bob"}
        called = []
        c.get_username = lambda uid: called.append(uid) or "x"  # type: ignore
        c.prefetch_usernames({1, 2})
        assert called == []

    def test_resolves_missing_ids_serially_without_executor(self):
        c = _make_cache_client(None)
        resolved = {}
        def fake_get(uid):
            resolved[uid] = f"user_{uid}"
            return resolved[uid]
        c.get_username = fake_get  # type: ignore
        c.prefetch_usernames({10, 20, 30})
        assert set(resolved.keys()) == {10, 20, 30}

    def test_resolves_missing_ids_via_executor(self):
        c = _make_cache_client(None)
        resolved = []
        lock = threading.Lock()
        def fake_get(uid):
            with lock:
                resolved.append(uid)
            return f"user_{uid}"
        c.get_username = fake_get  # type: ignore
        with ThreadPoolExecutor(max_workers=4) as ex:
            c.prefetch_usernames({100, 200, 300, 400}, executor=ex)
        assert set(resolved) == {100, 200, 300, 400}
