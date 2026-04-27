from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import User, SubscriptionStatus
from app.services.auth import get_current_user
from app.schemas.subscription import SubscriptionResponse, AppleReceiptRequest

router = APIRouter()

@router.get("/me", response_model=SubscriptionResponse)
async def get_my_subscription(current_user: User = Depends(get_current_user)):
    if not current_user.subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return current_user.subscription

@router.post("/verify-receipt", response_model=SubscriptionResponse)
async def verify_apple_receipt(request: AppleReceiptRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # In production, call Apple's verifyReceipt endpoint:
    # POST https://buy.itunes.apple.com/verifyReceipt
    # For now, we simulate success and update the user's subscription record
    
    if not request.receipt_data:
        raise HTTPException(status_code=400, detail="Missing receipt data")
        
    # Simulated validation response parsing:
    apple_original_transaction_id = "simulated_" + request.receipt_data[:10]
    
    sub = current_user.subscription
    if sub:
        sub.status = SubscriptionStatus.ACTIVE
        sub.apple_original_transaction_id = apple_original_transaction_id
        # Update end_date based on receipt
        await db.commit()
    
    return sub

@router.post("/webhook")
async def apple_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    # In production, Apple Server-to-Server notifications hit this webhook.
    # We parse the notification_type (e.g. CANCEL, DID_RENEW) and update matching `apple_original_transaction_id` in DB.
    # Return 200 immediately to Apple
    return {"status": "received"}
