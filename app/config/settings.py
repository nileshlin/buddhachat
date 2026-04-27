from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    GOOGLE_CLIENT_ID: str = ""
    APPLE_PUBLIC_KEY_URL: str = "https://appleid.apple.com/auth/keys"
    APPLE_BUNDLE_ID: str = "your-apple-bundle-id"
    APPLE_ISSUER: str = "https://appleid.apple.com"
    
    ELEVENLABS_API_KEY: str
    ELEVENLABS_VOICE_ID: str = "1ok9oo8w0A9iIezS9imJ"
    ELEVENLABS_MODEL: str
    
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    REDIS_URL: str = "redis://localhost:6379/0"
    
    DEFAULT_VOICE_VOLUME: str = "+6.0"
    DEFAULT_BG_VOLUME: str = "0.35"
    DEFAULT_PAGINATION_LIMIT: int = 20
    OTP_EXPIRATION_MINUTES: int = 10
    
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-2"
    SES_SENDER_EMAIL: str = "noreply@yourdomain.com"

    SUPPORT_EMAIL: str = "support@yourdomain.com"
    
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"
    TEMP_DIR: Path = Path("tmp")
    
    AWS_S3_BUCKET: str = "buddhachat-storage"
    AWS_S3_PRESIGN_EXPIRES_SECONDS: int = 3600

    class Config:
        env_file = ".env"

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
