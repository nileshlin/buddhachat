from pydantic import BaseModel
from typing import List, Optional

class MusicBase(BaseModel):
    display_name: str
    path: str
    category: str
    mood: List[str]
    description: Optional[str] = None
    tags: Optional[List[str]] = None

class MusicCreate(MusicBase):
    pass

class MusicUpdate(BaseModel):
    display_name: Optional[str] = None
    path: Optional[str] = None
    category: Optional[str] = None
    mood: Optional[List[str]] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None

class MusicResponse(MusicBase):
    id: int
    url: Optional[str] = None
