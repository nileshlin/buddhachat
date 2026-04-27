# Meditation Guide Services

A robust backend service for generating personalized meditation audio sessions through conversational AI, text-to-speech synthesis, and audio mixing. This service transforms user conversations into structured meditation scripts, generates voice audio, and combines it with background music for a seamless meditation experience.

## Table of Contents

- [Highlights](#highlights)
- [Technology Stack](#technology-stack)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Scripts and Utilities](#scripts-and-utilities)
- [Database and Migrations](#database-and-migrations)
- [Production Deployment](#production-deployment)
- [Docker](#docker)

## Highlights

- **Conversational AI Integration**: Leverages OpenAI to convert user dialogues into coherent meditation scripts.
- **Audio Synthesis**: Utilizes ElevenLabs for high-quality text-to-speech voice generation.
- **Audio Mixing**: Employs FFmpeg to blend voice audio with background music tracks.
- **Asynchronous Processing**: Handles long-running tasks via Celery and Redis for scalable background job processing.
- **Secure Cloud Storage**: Stores generated audio files in AWS S3 with presigned URLs for temporary access.
- **Multi-Platform Authentication**: Supports email OTP via AWS SES, Google OAuth, and Apple Sign-In.

## Technology Stack

- **API Framework**: FastAPI (`app/main.py`) - Modern, fast web framework for building APIs with Python 3.7+.
- **Task Queue**: Celery + Redis (`app/celery_app.py`) - Distributed task queue for asynchronous job processing.
- **Database**: PostgreSQL with SQLAlchemy asyncio and asyncpg for high-performance database operations.
- **Storage**: AWS S3 with presigned URLs (`app/services/s3_storage.py`) for secure file access.
- **AI Services**: OpenAI API (`app/services/openai_service.py`) for script generation.
- **Audio Processing**: ElevenLabs TTS + FFmpeg (`app/services/audio.py`) for voice synthesis and audio mixing.
- **Email Service**: AWS SES (`app/services/email_service.py`) for OTP authentication.

## Architecture

```
app/
  main.py                  # FastAPI application entry point, route registration, and database table initialization
  celery_app.py             # Celery application configuration for background task processing
  config/                   # Application settings, logging configuration, and custom exceptions
  database/                 # Database connection engine, session management, and SQLAlchemy models
  routes/                   # HTTP endpoint definitions and request handlers
  schemas/                  # Pydantic data models for request/response validation
  services/                 # Business logic, external API integrations, and core services
scripts/                    # Utility scripts for testing, seeding, and maintenance
storage/                    # Local asset storage and music catalog data
```

## Prerequisites

- Python 3.11 or higher (Docker image uses `python:3.11-slim`)
- PostgreSQL database
- Redis server
- FFmpeg and FFprobe installed and available in PATH (included in Docker image)
- API keys for:
  - OpenAI
  - ElevenLabs
  - AWS (S3 for storage; SES for email OTP if using email authentication)

## Quick Start (Local Development)

1. **Set up Python Environment**:
   ```bash
   python -m venv venv
   # On Windows
   venv\Scripts\activate
   # On macOS/Linux
   source venv/bin/activate

   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**:
   ```bash
   # On macOS/Linux
   cp .env.example .env
   # On Windows PowerShell
   Copy-Item .env.example .env
   ```
   Edit `.env` with your API keys and configuration settings.

3. **Start Dependencies** (using Docker for convenience):
   ```bash
   # PostgreSQL
   docker run --name meditation-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=meditation_db -p 5432:5432 -d postgres:16

   # Redis
   docker run --name meditation-redis -p 6379:6379 -d redis:7
   ```

4. **Launch the API Server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Start the Background Worker** (required for meditation generation):
   ```bash
   celery -A app.celery_app.celery_app worker -l info -B
   ```

**Access Points**:
- API Documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health Check: `GET /health`

## Configuration

Application settings are managed via environment variables loaded from `.env` using `pydantic-settings` (see `app/config/settings.py`).

**Important**: If a key exists in `.env` but is set to an empty value (e.g., `OPENAI_MODEL=`), it will override the default with an empty string. Remove optional keys that you are not configuring.

### Required Configuration

- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql+asyncpg://user:password@localhost:5432/meditation_db`)
- `REDIS_URL`: Redis connection URL (e.g., `redis://localhost:6379/0`)
- `OPENAI_API_KEY`: Your OpenAI API key
- `ELEVENLABS_API_KEY`: ElevenLabs API key
- `ELEVENLABS_MODEL`: TTS model identifier
- `AWS_REGION`: AWS region for services
- `AWS_S3_BUCKET`: S3 bucket name for audio storage
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: AWS credentials (or use IAM roles in production)

### Optional Configuration

#### S3 Storage
- `AWS_S3_PRESIGN_EXPIRES_SECONDS`: Presigned URL expiration time (default: 3600 seconds)
- `AWS_S3_ENDPOINT_URL`: Custom S3 endpoint (defaults to standard AWS S3 URL)

#### Authentication
- `JWT_SECRET`: Secret key for JWT token generation
- `SES_SENDER_EMAIL`: Verified sender email for OTP (required for email authentication)
- `GOOGLE_CLIENT_ID`: Google OAuth client ID
- `APPLE_BUNDLE_ID`: Apple app bundle identifier for Sign-In

#### Audio Processing
- `FFMPEG_PATH` and `FFPROBE_PATH`: Paths to FFmpeg executables (defaults: `ffmpeg`, `ffprobe`)
- `TEMP_DIR`: Temporary directory for processing (default: `tmp`)
- `DEFAULT_VOICE_VOLUME`: Voice audio volume adjustment (default: `+6.0`)
- `DEFAULT_BG_VOLUME`: Background music volume (default: `0.35`)

## API Endpoints

### Authentication
- `POST /auth/google` - Google OAuth authentication
- `POST /auth/apple` - Apple Sign-In authentication
- `POST /auth/email/request-code` - Request email OTP
- `POST /auth/email/verify-code` - Verify email OTP
- `POST /auth/refresh` - Refresh JWT token

### Sessions
- `POST /session` - Create a new chat session
- `POST /session/{session_id}/messages` - Add message to session

### Meditation
- `POST /meditation/start` - Initiate meditation generation
- `GET /meditation/{med_id}` - Retrieve meditation details
- `GET /meditation` - List user's meditations

### Music
- `POST /music` - Upload or update music metadata
- `GET /music/list` - Retrieve music catalog

## Scripts and Utilities

- `scripts/test_s3_upload.py`: Test S3 upload functionality and generate presigned URLs
- `scripts/test_email_service.py`: Send test OTP email via SES
- `scripts/test_openai.py`: Validate OpenAI API configuration
- `scripts/seed_music.py`: Populate database with background music metadata

## Database and Migrations

The application automatically creates database tables on startup using `Base.metadata.create_all()` in `app/main.py`. This approach creates missing tables but does not handle schema migrations for existing databases.

For schema changes in production:
- Apply DDL statements manually
- Consider implementing Alembic for proper migration management

## Production Deployment

### Security Considerations
- Restrict CORS origins (currently defaults to `["*"]` in `app/main.py`)
- Use IAM roles instead of long-lived AWS access keys
- Enable SSL/TLS for all communications

### Infrastructure Recommendations
- Run Celery Beat separately from workers for production environments
- Use managed Redis (AWS ElastiCache) for scalability
- Deploy on AWS ECS/Fargate for containerized workloads

### Additional Notes
- **S3 Security**: Keep buckets private and use presigned URLs for temporary access
- **SES Limitations**: In sandbox mode, emails can only be sent to verified recipients

## Docker

Build and run the application using Docker:

```bash
# Build the image
docker build -t meditation-guide-services .

# Run the container
docker run --rm -p 8000:8000 --env-file .env meditation-guide-services
```

The Docker image includes all dependencies, including FFmpeg, and is based on `python:3.11-slim`.
