from typing import Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import User, UserPreferences, Subscription, AuthProvider, SubscriptionPlan, SubscriptionStatus, UserRole

class UserService:
    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        stmt = select(User).options(selectinload(User.preferences), selectinload(User.subscription)).where(User.email == email)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_google_id(db: AsyncSession, google_id: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.preferences), selectinload(User.subscription))
            .where(User.google_id == google_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_apple_id(db: AsyncSession, apple_id: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.preferences), selectinload(User.subscription))
            .where(User.apple_id == apple_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
        stmt = select(User).options(selectinload(User.preferences), selectinload(User.subscription)).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(
        db: AsyncSession,
        email: str,
        auth_provider: AuthProvider,
        name: str = None,
        google_id: str = None,
        apple_id: str = None,
    ) -> User:
        db_user = User(
            email=email,
            auth_provider=auth_provider,
            name=name,
            google_id=google_id,
            apple_id=apple_id,
            role=UserRole.USER,
        )
        db.add(db_user)
        await db.flush()
        
        prefs = UserPreferences(user_id=db_user.id)
        sub = Subscription(user_id=db_user.id, plan_type=SubscriptionPlan.TRIAL, status=SubscriptionStatus.ACTIVE)
        db.add(prefs)
        db.add(sub)
        
        await db.commit()
        await db.refresh(db_user)
        return db_user

    @staticmethod
    async def update_user(db: AsyncSession, user_id: int, **kwargs) -> User:
        stmt = update(User).where(User.id == user_id).values(**kwargs)
        await db.execute(stmt)
        await db.commit()
        return await UserService.get_user(db, user_id)

    @staticmethod
    async def delete_user(db: AsyncSession, user_id: int):
        stmt = delete(User).where(User.id == user_id)
        await db.execute(stmt)
        await db.commit()
        
    @staticmethod
    async def update_user_preferences(db: AsyncSession, user_id: int, **kwargs):
        stmt = update(UserPreferences).where(UserPreferences.user_id == user_id).values(**kwargs)
        await db.execute(stmt)
        await db.commit()
        return await UserService.get_user(db, user_id)
