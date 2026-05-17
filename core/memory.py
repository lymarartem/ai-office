import aiosqlite
from pathlib import Path

DB_PATH = Path("ai_office.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_history(user_id: int, agent_name: str, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT role, content FROM conversations
               WHERE user_id = ? AND agent_name = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, agent_name, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


async def save_message(user_id: int, agent_name: str, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, agent_name, role, content) VALUES (?, ?, ?, ?)",
            (user_id, agent_name, role, content),
        )
        await db.commit()


async def clear_history(user_id: int, agent_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM conversations WHERE user_id = ? AND agent_name = ?",
            (user_id, agent_name),
        )
        await db.commit()
