from typing import List, Optional
from sqlalchemy import select, update, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Music
from app.schemas.music import MusicCreate, MusicUpdate
from app.config.logger import logger

class MusicService:
    @staticmethod
    async def create_music(db: AsyncSession, music: MusicCreate) -> Music:
        db_music = Music(**music.dict())
        db.add(db_music)
        await db.commit()
        await db.refresh(db_music)
        return db_music

    @staticmethod
    async def update_music(db: AsyncSession, music_id: int, data: MusicUpdate) -> Optional[Music]:
        stmt = update(Music).where(Music.id == music_id).values(**data.dict(exclude_unset=True))
        await db.execute(stmt)
        await db.commit()
        return await MusicService.get_music(db, music_id)

    @staticmethod
    async def get_music(db: AsyncSession, music_id: int) -> Optional[Music]:
        stmt = select(Music).where(Music.id == music_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_music(db: AsyncSession) -> List[Music]:
        stmt = select(Music)
        result = await db.execute(stmt)
        return result.scalars().all()
    
    @staticmethod
    async def get_random_music(db: AsyncSession) -> Optional[Music]:
        stmt = select(Music).order_by(func.random()).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_matching_music(db: AsyncSession, tags: List[str]) -> Optional[Music]:
        conditions = []
        if tags:
            # Match directly via Postgres capabilities and dynamic attributes
            conditions.append(or_(*(Music.category.ilike(f"%{tag}%") for tag in tags)))
            conditions.append(or_(*(func.array_to_string(Music.mood, ',').ilike(f"%{tag}%") for tag in tags)))
            conditions.append(or_(*(func.array_to_string(Music.tags, ',').ilike(f"%{tag}%") for tag in tags)))

        stmt = select(Music)
        if conditions:
            stmt = stmt.where(or_(*conditions))
            
        stmt = stmt.order_by(func.random()).limit(1)

        result = await db.execute(stmt)
        music = result.scalar_one_or_none()

        if not music:
            logger.info("No matching music found → falling back to random track")
            music = await MusicService.get_random_music(db)

        return music
