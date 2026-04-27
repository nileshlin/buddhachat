from typing import List, Optional
from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Meditation, Session, MeditationStatus

class MeditationService:
    @staticmethod
    async def create_meditation(db: AsyncSession, session_id: int) -> Meditation:
        db_med = Meditation(session_id=session_id)  
        db.add(db_med)
        await db.commit()
        await db.refresh(db_med)
        return db_med

    @staticmethod
    async def update_meditation(
        db: AsyncSession,
        med_id: int,
        *,
        return_entity: bool = True,
        **kwargs
    ) -> Optional[Meditation]:
        stmt = update(Meditation).where(Meditation.id == med_id).values(**kwargs)
        await db.execute(stmt)
        await db.commit()
        if not return_entity:
            return None
        return await MeditationService.get_meditation(db, med_id)

    @staticmethod
    async def get_meditation(db: AsyncSession, med_id: int) -> Optional[Meditation]:
        stmt = select(Meditation).where(Meditation.id == med_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
        
    @staticmethod
    async def get_user_meditations(db: AsyncSession, user_id: int, query: Optional[str] = None, limit: int = 20, offset: int = 0) -> List[Meditation]:
        stmt = (
            select(Meditation)
            .join(Session, Meditation.session_id == Session.id)
            .where(Session.user_id == user_id)
            .where(Meditation.status == MeditationStatus.COMPLETED)
            .order_by(Meditation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if query:
            stmt = stmt.where(or_(Meditation.name.ilike(f"%{query}%"), Meditation.summary.ilike(f"%{query}%")))
            
        result = await db.execute(stmt)
        return result.scalars().all()
