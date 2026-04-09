"""Tests for CLI argument parsing and routing logic.

All BGGClient interactions are patched so no network calls are made.
"""
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from bgg_scraper.cli import main

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FORUM_RESPONSE = {
    "threads": [
        {
            "threadid": "1001",
            "subject": "How do I win?",
            "user": {"username": "player1"},
            "numposts": "2",
            "postdate": "2024-01-01 10:00:00",
            "lastpostdate": "2024-01-02 10:00:00",
            "href": "/thread/1001/how-do-i-win",
        }
    ],
    "forums": [],
    "config": {
        "forumtitle": "Rules",
        "numthreads": "1",
        "endpage": 1,
        "forumid": "66",
    },
}

ARTICLE_RESPONSE = {
    "articles": [
        {
            "id": "5001",
            "author": "player1",
            "postdate": "2024-01-01T10:00:00+00:00",
            "editdate": None,
            "body": "How do I win?",
        },
        {
            "id": "5002",
            "author": "designer1",
            "postdate": "2024-01-02T10:00:00+00:00",
            "editdate": None,
            "body": "Score the most points.",
        },
    ],
    "total": 2,
    "perPage": 100,
    "pageid": 1,
}


def _make_mock_client():
    client = MagicMock()
    client.get_forum_threads_page.return_value = FORUM_RESPONSE
    client.get_thread_articles.return_value = ARTICLE_RESPONSE
    return client


# ---------------------------------------------------------------------------
# _parse_forum_url
# ---------------------------------------------------------------------------

class TestParseForumUrl:
    def test_valid_url(self):
        from bgg_scraper.cli import _parse_forum_url
        game_id, forum_id, game_slug = _parse_forum_url(
            "https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66"
        )
        assert game_id == 307161
        assert forum_id == 66
        assert game_slug == "quest-for-the-lost-pixel"

    def test_invalid_url_raises(self):
        from bgg_scraper.cli import _parse_forum_url
        import click
        with pytest.raises(click.BadParameter):
            _parse_forum_url("https://boardgamegeek.com/boardgame/307161")


# ---------------------------------------------------------------------------
# scrape — URL argument
# ---------------------------------------------------------------------------

class TestScrapeWithUrl:
    def _run(self, tmp_path, extra_args=None):
        runner = CliRunner()
        client = _make_mock_client()
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            args = [
                "scrape",
                "https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66",
                "--output-dir", str(tmp_path),
                *(extra_args or []),
            ]
            result = runner.invoke(main, args, env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
            })
        return result, client

    def test_creates_output_file(self, tmp_path):
        result, _ = self._run(tmp_path)
        assert result.exit_code == 0, result.output
        md_files = list(tmp_path.rglob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].name == "1001_how-do-i-win.md"

    def test_output_path_uses_game_and_forum_slug(self, tmp_path):
        result, _ = self._run(tmp_path)
        assert result.exit_code == 0
        md_files = list(tmp_path.rglob("*.md"))
        parts = md_files[0].relative_to(tmp_path).parts
        assert parts[0] == "quest-for-the-lost-pixel"
        assert parts[1] == "rules"

    def test_login_called_with_credentials(self, tmp_path):
        _, client = self._run(tmp_path)
        client.login.assert_called_once_with("user", "pass")

    def test_skips_existing_file(self, tmp_path):
        # First run writes the file
        self._run(tmp_path)
        # Second run should skip it
        result, client = self._run(tmp_path)
        assert result.exit_code == 0
        assert "1 skipped" in result.output

    def test_max_threads_limits_fetched(self, tmp_path):
        # Add a second stub to the forum page
        two_thread_response = dict(FORUM_RESPONSE)
        two_thread_response["threads"] = FORUM_RESPONSE["threads"] + [
            {
                "threadid": "1002",
                "subject": "Second question",
                "user": {"username": "player2"},
                "numposts": "1",
                "postdate": "2024-01-03 10:00:00",
                "lastpostdate": "2024-01-03 10:00:00",
                "href": "/thread/1002/second-question",
            }
        ]
        runner = CliRunner()
        client = _make_mock_client()
        client.get_forum_threads_page.return_value = two_thread_response
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "scrape",
                "https://boardgamegeek.com/boardgame/307161/quest-for-the-lost-pixel/forums/66",
                "--output-dir", str(tmp_path),
                "--max-threads", "1",
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})
        assert result.exit_code == 0
        assert len(list(tmp_path.rglob("*.md"))) == 1


# ---------------------------------------------------------------------------
# scrape — --game-id / --forum-id flags
# ---------------------------------------------------------------------------

class TestScrapeWithIds:
    def _run(self, tmp_path, args):
        runner = CliRunner()
        client = _make_mock_client()
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, args, env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
            })
        return result, client

    def test_long_flags(self, tmp_path):
        result, _ = self._run(tmp_path, [
            "scrape", "--game-id", "307161", "--forum-id", "66",
            "--output-dir", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.rglob("*.md"))) == 1

    def test_short_flags(self, tmp_path):
        result, _ = self._run(tmp_path, [
            "scrape", "-g", "307161", "-f", "66",
            "--output-dir", str(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.rglob("*.md"))) == 1

    def test_game_id_used_as_slug_in_path(self, tmp_path):
        result, _ = self._run(tmp_path, [
            "scrape", "-g", "307161", "-f", "66",
            "--output-dir", str(tmp_path),
        ])
        assert result.exit_code == 0
        md_files = list(tmp_path.rglob("*.md"))
        assert md_files[0].relative_to(tmp_path).parts[0] == "307161"

    def test_env_vars(self, tmp_path):
        runner = CliRunner()
        client = _make_mock_client()
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "scrape", "--output-dir", str(tmp_path),
            ], env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
                "BGG_GAME_ID": "307161", "BGG_FORUM_ID": "66",
            })
        assert result.exit_code == 0, result.output
        assert len(list(tmp_path.rglob("*.md"))) == 1


# ---------------------------------------------------------------------------
# scrape — error cases
# ---------------------------------------------------------------------------

class TestScrapeErrors:
    def test_no_url_no_ids_exits_with_error(self):
        runner = CliRunner()
        with patch("bgg_scraper.cli.BGGClient"):
            result = runner.invoke(main, ["scrape"], env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
            })
        assert result.exit_code != 0

    def test_game_id_without_forum_id_exits_with_error(self):
        runner = CliRunner()
        with patch("bgg_scraper.cli.BGGClient"):
            result = runner.invoke(main, ["scrape", "--game-id", "307161"], env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
            })
        assert result.exit_code != 0

    def test_invalid_url_exits_with_error(self):
        runner = CliRunner()
        with patch("bgg_scraper.cli.BGGClient"):
            result = runner.invoke(main, [
                "scrape", "https://boardgamegeek.com/not/a/forum",
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})
        assert result.exit_code != 0

    def test_login_failure_exits_with_error(self):
        from bgg_scraper.client import AuthError
        runner = CliRunner()
        client = MagicMock()
        client.login.side_effect = AuthError("bad credentials")
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "scrape", "-g", "307161", "-f", "66",
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _parse_thread_url
# ---------------------------------------------------------------------------

class TestParseThreadUrl:
    def test_full_url_with_article(self):
        from bgg_scraper.cli import _parse_thread_url
        assert _parse_thread_url(
            "https://boardgamegeek.com/thread/3006560/article/41505990"
        ) == 3006560

    def test_url_without_article(self):
        from bgg_scraper.cli import _parse_thread_url
        assert _parse_thread_url(
            "https://boardgamegeek.com/thread/3006560/some-thread-slug"
        ) == 3006560

    def test_invalid_url_raises(self):
        from bgg_scraper.cli import _parse_thread_url
        import click
        with pytest.raises(click.BadParameter):
            _parse_thread_url("https://boardgamegeek.com/boardgame/307161")


# ---------------------------------------------------------------------------
# thread command
# ---------------------------------------------------------------------------

class TestThreadCommand:
    def _run(self, tmp_path, url, extra_args=None):
        runner = CliRunner()
        client = _make_mock_client()
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "thread", url,
                "--output-dir", str(tmp_path),
                *(extra_args or []),
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})
        return result, client

    def test_creates_md_file(self, tmp_path):
        result, _ = self._run(
            tmp_path, "https://boardgamegeek.com/thread/3006560/article/41505990"
        )
        assert result.exit_code == 0, result.output
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].name.startswith("3006560_")

    def test_file_written_directly_into_output_dir(self, tmp_path):
        result, _ = self._run(
            tmp_path, "https://boardgamegeek.com/thread/3006560/article/41505990"
        )
        assert result.exit_code == 0
        # No subdirectories — file sits directly in output_dir
        assert len(list(tmp_path.iterdir())) == 1
        assert list(tmp_path.iterdir())[0].is_file()

    def test_skips_existing_file(self, tmp_path):
        url = "https://boardgamegeek.com/thread/3006560/article/41505990"
        self._run(tmp_path, url)
        result, client = self._run(tmp_path, url)
        assert result.exit_code == 0
        assert "Skipped" in result.output
        # second run creates a fresh mock — articles should not have been fetched
        assert client.get_thread_articles.call_count == 0

    def test_designer_flag_propagated(self, tmp_path):
        result, _ = self._run(
            tmp_path,
            "https://boardgamegeek.com/thread/3006560/article/41505990",
            extra_args=["--designer", "designer1"],
        )
        assert result.exit_code == 0
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "GAME DESIGNER" in content

    def test_designer_env_var_propagated(self, tmp_path):
        runner = CliRunner()
        client = _make_mock_client()
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "thread",
                "https://boardgamegeek.com/thread/3006560/article/41505990",
                "--output-dir", str(tmp_path),
            ], env={
                "BGG_USERNAME": "user", "BGG_PASSWORD": "pass",
                "BGG_DESIGNER": "designer1",
            })
        assert result.exit_code == 0
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "GAME DESIGNER" in content

    def test_invalid_url_exits_with_error(self, tmp_path):
        result, _ = self._run(tmp_path, "https://boardgamegeek.com/not/a/thread")
        assert result.exit_code != 0

    def test_canonical_thread_url_uses_slug_as_subject_hint(self, tmp_path):
        result, _ = self._run(
            tmp_path, "https://boardgamegeek.com/thread/3006560/how-do-i-win"
        )
        assert result.exit_code == 0, result.output
        md_files = list(tmp_path.glob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].name == "3006560_how-do-i-win.md"
        assert md_files[0].read_text().startswith("# How Do I Win")

    def test_multi_page_thread_fetches_all_articles(self, tmp_path):
        # Simulate a thread whose articles span two pages (perPage=2, 2+1 articles)
        def _article(n):
            return {
                "id": str(5000 + n),
                "author": "player1",
                "postdate": "2024-01-01T10:00:00+00:00",
                "editdate": None,
                "body": f"Article {n}",
            }

        page1 = {"articles": [_article(1), _article(2)], "perPage": 2, "pageid": 1}
        page2 = {"articles": [_article(3)], "perPage": 2, "pageid": 2}

        runner = CliRunner()
        client = MagicMock()
        client.get_thread_articles.side_effect = [page1, page2]
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "thread",
                "https://boardgamegeek.com/thread/3006560/article/41505990",
                "--output-dir", str(tmp_path),
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})

        assert result.exit_code == 0, result.output
        assert client.get_thread_articles.call_count == 2
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "Article 1" in content
        assert "Article 2" in content
        assert "Article 3" in content

    def test_login_failure_exits_with_error(self, tmp_path):
        from bgg_scraper.client import AuthError
        runner = CliRunner()
        client = MagicMock()
        client.login.side_effect = AuthError("bad credentials")
        with patch("bgg_scraper.cli.BGGClient", return_value=client):
            result = runner.invoke(main, [
                "thread",
                "https://boardgamegeek.com/thread/3006560/article/41505990",
                "--output-dir", str(tmp_path),
            ], env={"BGG_USERNAME": "user", "BGG_PASSWORD": "pass"})
        assert result.exit_code != 0
