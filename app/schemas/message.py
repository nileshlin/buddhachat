from pydantic import BaseModel
from enum import Enum

class MessageRole(str, Enum):
    user = "user"
    agent = "agent"

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: int
    role: MessageRole
    content: str
    created_at: str