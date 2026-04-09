from bgg_scraper.parser import parse_articles, parse_forum_threads_page

FORUM_RESPONSE = {
    "threads": [
        {
            "threadid": "1001",
            "subject": "How do I set up the board?",
            "user": {"username": "player1"},
            "numposts": "3",
            "postdate": "2023-04-15 10:00:00",
            "lastpostdate": "2023-04-16 12:00:00",
            "href": "/thread/1001/how-do-i-set-up-the-board",
        },
        {
            "threadid": "1002",
            "subject": "What happens when tiles run out?",
            "user": {"username": "player2"},
            "numposts": "2",
            "postdate": "2023-04-17 09:00:00",
            "lastpostdate": "2023-04-17 15:00:00",
            "href": "/thread/1002/what-happens-when-tiles-run-out",
        },
    ],
    "forums": [],
    "config": {
        "forumtitle": "Rules",
        "numthreads": "3",
        "endpage": 1,
        "forumid": "66",
    },
}

ARTICLE_RESPONSE = {
    "articles": [
        {
            "id": "5001",
            "author": "player1",   # string username (already resolved)
            "postdate": "2023-04-15T10:00:00+00:00",
            "editdate": None,
            "body": "The rulebook says face-down but diagram says face-up. Which is correct?",
        },
        {
            "id": "5002",
            "author": "designer_jane",
            "postdate": "2023-04-16T09:00:00+00:00",
            "editdate": "2023-04-16T10:00:00+00:00",
            "body": "Diagram is correct — tiles go face-up.",
        },
        {
            "id": "5003",
            "author": "player1",
            "postdate": "2023-04-16T12:00:00+00:00",
            "editdate": None,
            "body": "Thanks!",
        },
    ],
    "total": 3,
    "perPage": 100,
    "pageid": 1,
}


def test_parse_forum_page_meta():
    page = parse_forum_threads_page(FORUM_RESPONSE, game_id=307161, forum_id=66)

    assert page.forum_id == 66
    assert page.title == "Rules"
    assert page.num_threads == 3
    assert page.end_page == 1
    assert len(page.threads) == 2


def test_parse_forum_page_thread_stubs():
    page = parse_forum_threads_page(FORUM_RESPONSE, game_id=307161, forum_id=66)

    first = page.threads[0]
    assert first["id"] == 1001
    assert first["subject"] == "How do I set up the board?"
    assert first["author"] == "player1"
    assert first["num_posts"] == 3


def test_parse_articles_meta():
    thread = parse_articles(1001, "How do I set up the board?", ARTICLE_RESPONSE)

    assert thread.id == 1001
    assert thread.subject == "How do I set up the board?"
    assert thread.author == "player1"
    assert thread.num_articles == 3


def test_parse_articles_posts():
    thread = parse_articles(1001, "How do I set up the board?", ARTICLE_RESPONSE)

    assert len(thread.posts) == 3

    q = thread.posts[0]
    assert q.id == 5001
    assert q.author == "player1"
    assert q.date == "2023-04-15T10:00:00+00:00"
    assert "face-down" in q.body

    reply = thread.posts[1]
    assert reply.author == "designer_jane"
    assert reply.edit_date == "2023-04-16T10:00:00+00:00"

    last = thread.posts[2]
    assert last.edit_date is None


def test_parse_articles_uses_subject_from_response_when_available():
    response = {
        "title": "Official Thread Title",
        "articles": ARTICLE_RESPONSE["articles"],
        "total": 3,
    }

    thread = parse_articles(1001, "", response)

    assert thread.subject == "Official Thread Title"
