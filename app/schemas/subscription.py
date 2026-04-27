from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SubscriptionResponse(BaseModel):
    status: str
    plan_type: str
    start_date: datetime
    end_date: Optional[datetime] = None

    class Config:
        from_attributes = True

class AppleReceiptRequest(BaseModel):
    receipt_data: str
