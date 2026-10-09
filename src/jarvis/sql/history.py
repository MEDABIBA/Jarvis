import sqlite3
from pathlib import Path

from jarvis.llm.schemas import SessionData

path = Path(__file__).parents[3] / "memory" / "history.db"

SCHEMA = """
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY,
        turn_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS fts_messages USING fts5(
        question,
        answer,
        content='messages',
        content_rowid='id'
    );

    CREATE TRIGGER IF NOT EXISTS sync_fts AFTER INSERT ON messages BEGIN
        INSERT INTO fts_messages(rowid, question, answer) 
        VALUES(new.id, new.question, new.answer);
        END;"""


def quote_for_fts(text: str) -> str:
    """Wrap each word in double quotes: FTS5 then matches it as a literal,
    so `?`, `,`, `*` lose their meaning."""
    return " ".join(f'"{w}"' for w in text.replace('"', " ").split())


class Database:
    def __init__(self):
        self.con = sqlite3.connect(path)

    def initialize(self) -> None:
        """ "Create database if dont exist"""
        self.con.executescript(SCHEMA)

    def push(self, data: SessionData) -> None:
        """Append one finished turn. Called once per user request"""
        self.con.execute(
            """INSERT INTO messages(
            question, answer, turn_id
        ) 
        VALUES(
            :question , :answer, :turn_id
        )""",
            data.model_dump(),
        )
        self.con.commit()

    def read(self, match: str, limit: int = 2) -> list[sqlite3.Row]:
        """Past turns matching `answer_tokens_match`, best matches first

        bm25(): https://sqlite.org/fts5.html#the_bm25_function
        snippet(): https://sqlite.org/fts5.html#the_snippet_function"""

        match = quote_for_fts(match)
        if not match:
            return []
        return self.con.execute(
            """
    SELECT m.id,
    m.question,
    snippet(fts_messages, 1, '**', '**', ' ... ', 32) AS answer,
    m.created_at,
    bm25(fts_messages) AS score
    FROM fts_messages
    JOIN messages m ON m.id = fts_messages.rowid
    WHERE fts_messages MATCH ?
    ORDER BY score
    LIMIT ?
""",
            [match, limit],
        ).fetchall()