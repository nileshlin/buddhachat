from typing import Optional
from datetime import datetime
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import OTP

class OTPService:
    @staticmethod
    async def create_otp(db: AsyncSession, email: str, code: str, expires_at: datetime) -> OTP:
        await db.execute(delete(OTP).where(OTP.email == email))
        db_otp = OTP(email=email, code=code, expires_at=expires_at)
        db.add(db_otp)
        await db.commit()
        return db_otp
        
    @staticmethod
    async def get_otp(db: AsyncSession, email: str, code: str) -> Optional[OTP]:
        stmt = select(OTP).where(OTP.email == email, OTP.code == code)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
        
    @staticmethod
    async def delete_otp(db: AsyncSession, email: str):
        await db.execute(delete(OTP).where(OTP.email == email))
        await db.commit()
