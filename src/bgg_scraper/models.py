from dataclasses import dataclass, field


@dataclass
class Post:
    id: int
    author: str
    date: str        # ISO 8601 string from API
    body: str        # plain text body
    edit_date: str | None = None


@dataclass
class Thread:
    id: int
    subject: str
    author: str
    num_articles: int
    posts: list[Post] = field(default_factory=list)


@dataclass
class ForumPage:
    forum_id: int
    title: str
    description: str
    num_threads: int
    threads: list[dict] = field(default_factory=list)  # thread stubs from listing
    end_page: int = 1
