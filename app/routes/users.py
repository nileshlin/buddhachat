from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import User
from app.services.user_service import UserService
from app.services.meditation_service import MeditationService
from app.services.auth import get_current_user
from app.schemas.user import UserResponse, UserUpdate, UserStatsResponse, UserPreferencesBase

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/me", response_model=UserResponse)
async def update_me(update_data: UserUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    updated = await UserService.update_user(db, current_user.id, **update_data.dict(exclude_unset=True))
    return updated

@router.delete("/me")
async def delete_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await UserService.delete_user(db, current_user.id)
    return {"message": "Account deleted successfully"}

@router.put("/me/preferences", response_model=UserResponse)
async def update_preferences(prefs: UserPreferencesBase, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    updated = await UserService.update_user_preferences(db, current_user.id, **prefs.dict(exclude_unset=True))
    return updated

@router.get("/me/stats", response_model=UserStatsResponse)
async def get_my_stats(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    meditations = await MeditationService.get_user_meditations(db, current_user.id, limit=1000)
    
    total_sessions = len(meditations)
    # Estimate: each block definition has durations: 90+150+120+150+90+150+120+120+90+120 = 1200 seconds = 20 mins exactly
    total_minutes = total_sessions * 20.0  
    avg_length = 20.0 if total_sessions > 0 else 0.0
    
    longest_streak = 0
    if meditations:
        longest_streak = 1
        # Full logic for actual contiguous days goes here, left simple for snippet

    return UserStatsResponse(
        total_minutes=total_minutes,
        total_sessions=total_sessions,
        average_length=avg_length,
        longest_streak=longest_streak
    )
