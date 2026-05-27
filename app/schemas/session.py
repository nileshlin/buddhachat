from pydantic import BaseModel
from typing import Optional

from app.schemas.message import MessageResponse


class SessionCreate(BaseModel):
    pass

class SessionResponse(BaseModel):
    id: int
    user_id: int
    initial_message: Optional[MessageResponse] = None

    class Config:
        from_attributes = True
