from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import jwt
import requests
from sqlalchemy.ext.asyncio import AsyncSession
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from datetime import datetime, timedelta
import secrets
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError, PyJWKClientError

from app.database.db import get_db
from app.database.models import AuthProvider
from app.services.user_service import UserService
from app.services.otp_service import OTPService
from app.services.email_service import email_service
from app.services.auth import create_access_token, create_refresh_token, decode_token
from app.schemas.auth import (
    GoogleAuthRequest, AppleAuthRequest, EmailOTPRequest, 
    EmailOTPVerifyRequest, AuthTokenResponse, RefreshTokenRequest
)
from app.config.settings import settings

router = APIRouter()
_apple_jwk_client = PyJWKClient(settings.APPLE_PUBLIC_KEY_URL)

def _decode_apple_identity_token(identity_token: str) -> dict:
    signing_key = _apple_jwk_client.get_signing_key_from_jwt(identity_token).key
    return jwt.decode(
        identity_token,
        signing_key,
        audience=settings.APPLE_BUNDLE_ID,
        issuer=settings.APPLE_ISSUER,
        algorithms=["RS256"],
    )

@router.post("/google", response_model=AuthTokenResponse)
async def authenticate_google(request: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        id_info = id_token.verify_oauth2_token(
            request.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        # Ensure email is verified by Google
        if not id_info.get("email_verified"):
            raise HTTPException(status_code=401, detail="Google email not verified")
        
        email = id_info.get("email")
        name = id_info.get("name")
        google_id = id_info.get("sub")
        if not google_id:
            raise HTTPException(status_code=401, detail="Invalid Google token")
        
        user = await UserService.get_user_by_google_id(db, google_id)
        if not user and email:
            user = await UserService.get_user_by_email(db, email)
            if user and not getattr(user, "google_id", None):
                user = await UserService.update_user(db, user.id, google_id=google_id)
        if not user:
            if not email:
                raise HTTPException(status_code=401, detail="Google token missing email")
            user = await UserService.create_user(
                db,
                email=email,
                auth_provider=AuthProvider.GOOGLE,
                name=name,
                google_id=google_id,
            )
            
        access_token = create_access_token(data={"sub": str(user.id)})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})
        return AuthTokenResponse(access_token=access_token, refresh_token=refresh_token)
        
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

@router.post("/apple", response_model=AuthTokenResponse)
async def authenticate_apple(request: AppleAuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = _decode_apple_identity_token(request.identity_token)

        apple_id = payload.get("sub")
        if not apple_id:
            raise HTTPException(status_code=401, detail="Invalid Apple token")

        email = payload.get("email") or request.email
        if not email:
            raise HTTPException(
                status_code=400,
                detail="Apple token did not include an email; provide email or re-authorize with email scope",
            )

        email_verified = payload.get("email_verified")
        if email_verified is not None and str(email_verified).lower() not in {"true", "1"}:
            raise HTTPException(status_code=401, detail="Apple email not verified")

        name = request.name or "Unknown"

        user = await UserService.get_user_by_apple_id(db, apple_id)
        if not user:
            user = await UserService.get_user_by_email(db, email)
            if user and not getattr(user, "apple_id", None):
                user = await UserService.update_user(db, user.id, apple_id=apple_id)
        if not user:
            user = await UserService.create_user(
                db,
                email=email,
                auth_provider=AuthProvider.APPLE,
                name=name,
                apple_id=apple_id,
            )
            
        access_token = create_access_token(data={"sub": str(user.id)})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})
        return AuthTokenResponse(access_token=access_token, refresh_token=refresh_token)

    except (PyJWKClientError, PyJWTError, requests.RequestException):
        raise HTTPException(status_code=401, detail="Invalid Apple token")

@router.post("/email/request-code")
async def request_email_code(request: EmailOTPRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    code = f"{secrets.randbelow(100000):05d}"
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    
    await OTPService.create_otp(db, email=request.email, code=code, expires_at=expires_at)
    
    # Offload the SES email sending to background tasks
    background_tasks.add_task(email_service.send_otp_email, request.email, code)
    
    return {"message": "OTP sent to email"}

@router.post("/email/verify-code", response_model=AuthTokenResponse)
async def verify_email_code(request: EmailOTPVerifyRequest, db: AsyncSession = Depends(get_db)):
    otp = await OTPService.get_otp(db, email=request.email, code=request.code)
    
    if not otp:
        raise HTTPException(status_code=401, detail="Invalid code")
    if otp.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Code expired")
        
    user = await UserService.get_user_by_email(db, request.email)
    if not user:
        user = await UserService.create_user(db, email=request.email, auth_provider=AuthProvider.EMAIL)
        
    await OTPService.delete_otp(db, email=request.email)
    
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    return AuthTokenResponse(access_token=access_token, refresh_token=refresh_token)

@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
            
        user_id = payload.get("sub")
        user = await UserService.get_user(db, user_id=int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
            
        access_token = create_access_token(data={"sub": str(user.id)})
        new_refresh = create_refresh_token(data={"sub": str(user.id)})
        return AuthTokenResponse(access_token=access_token, refresh_token=new_refresh)
        
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/logout")
async def logout():
    return {"message": "Logged out successfully"}
