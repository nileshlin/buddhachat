from pydantic import BaseModel


class SessionCreate(BaseModel):
    pass

class SessionResponse(BaseModel):
    id: int
    user_id: int

    class Config:
        from_attributes = True