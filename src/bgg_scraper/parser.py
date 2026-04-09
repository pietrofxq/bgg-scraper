from __future__ import annotations

from typing import TYPE_CHECKING

from .models import ForumPage, Post, Thread

if TYPE_CHECKING:
    from .client import BGGClient


def parse_forum_threads_page(data: dict, game_id: int, forum_id: int) -> ForumPage:
    """Parse a /api/forums/threads response into a ForumPage."""
    config = data.get("config", {})
    title = config.get("forumtitle", "")
    num_threads = int(config.get("numthreads", 0))
    end_page = int(config.get("endpage", 1))

    stubs = []
    for t in data.get("threads", []):
        stubs.append(
            {
                "id": int(t["threadid"]),
                "subject": t.get("subject", ""),
                "author": (t.get("user") or {}).get("username", ""),
                "num_posts": int(t.get("numposts", 0)),
                "post_date": t.get("postdate", ""),
                "last_post_date": t.get("lastpostdate", ""),
                "href": t.get("href", ""),
            }
        )

    return ForumPage(
        forum_id=forum_id,
        title=title,
        description="",
        num_threads=num_threads,
        threads=stubs,
        end_page=end_page,
    )


def parse_articles(
    thread_id: int,
    subject: str,
    data: dict,
    client: BGGClient | None = None,
) -> Thread:
    """Parse a /api/article?threadid=... response into a Thread.

    If client is provided, numeric author IDs are resolved to usernames
    via the cached /api/user/{id} endpoint.
    """
    articles = data.get("articles", [])
    fallback_subject = data.get("subject") or data.get("title")
    if not fallback_subject and articles:
        fallback_subject = articles[0].get("subject")
    resolved_subject = str(fallback_subject or subject or "").strip()
    posts = []

    for a in articles:
        raw_author = a.get("author", "")
        if isinstance(raw_author, int) and client is not None:
            author = client.get_username(raw_author)
        else:
            author = str(raw_author)

        posts.append(
            Post(
                id=int(a["id"]),
                author=author,
                date=a.get("postdate", ""),
                body=a.get("body", ""),
                edit_date=a.get("editdate") or None,
            )
        )

    return Thread(
        id=thread_id,
        subject=resolved_subject,
        author=posts[0].author if posts else "",
        num_articles=int(data.get("total", len(posts))),
        posts=posts,
    )
