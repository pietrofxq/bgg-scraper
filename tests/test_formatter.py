from bgg_scraper.formatter import output_filename, slug, thread_to_markdown
from bgg_scraper.models import Post, Thread


def _make_thread() -> Thread:
    return Thread(
        id=1001,
        subject="How do I set up the board?",
        author="player1",
        num_articles=3,
        posts=[
            Post(id=5001, author="player1", date="2023-04-15T10:00:00+00:00",
                 body="The rulebook says face-down but diagram says face-up. Which is correct?"),
            Post(id=5002, author="designer_jane", date="2023-04-16T09:00:00+00:00",
                 body="Diagram is correct — tiles go face-up."),
            Post(id=5003, author="player1", date="2023-04-16T12:00:00+00:00",
                 body="Thanks!"),
        ],
    )


def test_slug_basic():
    assert slug("How do I set up the board?") == "how-do-i-set-up-the-board"


def test_slug_special_chars():
    result = slug("Q&A: Setup / Rules")
    assert result  # non-empty
    assert len(result) <= 60


def test_slug_truncation():
    long = "a" * 100
    assert len(slug(long)) <= 60


def test_output_filename():
    thread = _make_thread()
    name = output_filename(thread)
    assert name == "1001_how-do-i-set-up-the-board.md"


def test_thread_to_markdown_structure():
    thread = _make_thread()
    md = thread_to_markdown(thread)

    assert md.startswith("# How do I set up the board?")
    assert "## Question" in md
    assert "## Reply 1" in md
    assert "## Reply 2" in md
    assert "*player1*" in md
    assert "*designer_jane*" in md


def test_thread_to_markdown_body_preserved():
    thread = _make_thread()
    md = thread_to_markdown(thread)
    assert "face-down" in md
    assert "face-up" in md


def test_thread_to_markdown_has_separators():
    thread = _make_thread()
    md = thread_to_markdown(thread)
    # Three posts → at least 3 separators (---) in output
    assert md.count("---") >= 3
