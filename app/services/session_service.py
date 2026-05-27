from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Session, Message, MessageRole

class SessionService:
    @staticmethod
    async def create_session(db: AsyncSession, user_id: int) -> Session:
        db_session = Session(user_id=user_id)
        db.add(db_session)

        await db.flush()
        await db.refresh(db_session)
        await db.commit()

        return db_session

    @staticmethod
    async def get_session(db: AsyncSession, session_id: int) -> Optional[Session]:
        stmt = select(Session).where(Session.id == session_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_message(db: AsyncSession, session_id: int, role: MessageRole, content: str) -> Message:
        db_message = Message(session_id=session_id, role=role, content=content)
        db.add(db_message)
        await db.commit()
        await db.refresh(db_message)
        return db_message

    @staticmethod
    async def get_session_messages(db: AsyncSession, session_id: int) -> List[Message]:
        stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        result = await db.execute(stmt)
        return result.scalars().all()
