from pydantic import BaseModel
from typing import Optional

class UserPreferencesBase(BaseModel):
    theme: Optional[str] = None
    language: Optional[str] = None
    voice_volume: Optional[str] = None
    bg_volume: Optional[str] = None
    notifications: Optional[dict] = None

class UserPreferencesResponse(UserPreferencesBase):
    id: int

    class Config:
        from_attributes = True

class UserBase(BaseModel):
    email: str
    name: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class UserResponse(UserBase):
    id: int
    auth_provider: str
    preferences: Optional[UserPreferencesResponse] = None

    class Config:
        from_attributes = True

class UserStatsResponse(BaseModel):
    total_minutes: float
    total_sessions: int
    average_length: float
    longest_streak: int
