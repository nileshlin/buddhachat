from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.meditation_service import MeditationService
from app.services.session_service import SessionService
from app.services.auth import get_current_user
from app.schemas.meditation import MeditationResponse
from app.database.models import User
from app.database.db import get_db
from app.celery_app import generate_meditation_task
from app.services.s3_storage import S3Storage
from app.config.logger import logger

router = APIRouter()

async def _hydrate_meditation_response(meditation) -> MeditationResponse:
    storage = S3Storage()
    audio_blocks_out = None
    merged_tts_layer_out = None
    merged_music_layer_out = None
    raw_audio = meditation.audio_blocks

    async def resolve_presigned_url(key: str | None, legacy_url: str | None = None) -> tuple[str | None, str | None]:
        if not key and legacy_url and not str(legacy_url).startswith("http"):
            key = legacy_url

        url = None
        if key:
            url = await storage.create_presigned_get_url(key)
        elif legacy_url and str(legacy_url).startswith("http"):
            url = legacy_url

        return key, url

    async def hydrate_audio_file(audio_file: dict | None):
        if not audio_file:
            return None

        key, url = await resolve_presigned_url(audio_file.get("key"), audio_file.get("url"))

        return {
            "duration": audio_file.get("duration"),
            "type": audio_file.get("type"),
            "background_audio": audio_file.get("background_audio"),
            "source_background_music_key": audio_file.get("source_background_music_key"),
            "key": key,
            "url": url,
        }

    if isinstance(raw_audio, dict):
        audio_entries = raw_audio.get("blocks") or []
        merged_tts_layer_out = await hydrate_audio_file(raw_audio.get("merged_tts_layer"))
        merged_music_layer_out = await hydrate_audio_file(raw_audio.get("merged_music_layer"))
    else:
        audio_entries = raw_audio or []

    if audio_entries:
        audio_blocks_out = []
        for block in audio_entries:
            key, url = await resolve_presigned_url(block.get("key"), block.get("url"))
            background_music_key, background_music_url = await resolve_presigned_url(
                block.get("background_music_key"),
                block.get("background_music_url"),
            )

            audio_blocks_out.append(
                {
                    "block": block.get("block"),
                    "duration": block.get("duration"),
                    "type": block.get("type"),
                    "has_voice": block.get("has_voice"),
                    "background_audio": block.get("background_audio"),
                    "key": key,
                    "url": url,
                    "background_music_key": background_music_key,
                    "background_music_url": background_music_url,
                }
            )

    status = meditation.status.value if hasattr(meditation.status, "value") else str(meditation.status)

    return MeditationResponse(
        id=meditation.id,
        session_id=meditation.session_id,
        name=meditation.name,
        summary=meditation.summary,
        script=meditation.script,
        audio_blocks=audio_blocks_out,
        merged_tts_layer=merged_tts_layer_out,
        merged_music_layer=merged_music_layer_out,
        status=status,
        progress=meditation.progress or 0,
        is_liked=bool(meditation.is_liked),
    )
    
@router.post("/start", response_model=MeditationResponse)
async def start_meditation(session_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await SessionService.get_session(db, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found or unauthorized")
    
    meditation = await MeditationService.create_meditation(db, session_id)
    
    # Offload the heavy generation to Celery Worker
    async_result = generate_meditation_task.delay(meditation.id, session_id, current_user.id)
    logger.info(f"Queued meditation generation task_id={async_result.id} med_id={meditation.id} session_id={session_id} user_id={current_user.id}")
    
    return await _hydrate_meditation_response(meditation)


@router.post("/{med_id}/like", response_model=MeditationResponse)
async def toggle_like_meditation(med_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    meditation = await MeditationService.get_meditation(db, med_id)
    if not meditation:
        raise HTTPException(status_code=404, detail="Meditation not found")
        
    session = await SessionService.get_session(db, meditation.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    updated = await MeditationService.update_meditation(db, med_id, is_liked=not meditation.is_liked)
    return await _hydrate_meditation_response(updated)


@router.get("/list", response_model=List[MeditationResponse])
async def list_completed_meditations(
    query: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    meditations = await MeditationService.get_user_meditations(db, user_id=current_user.id, query=query, limit=limit, offset=offset)
    return [await _hydrate_meditation_response(m) for m in meditations]


@router.get("/search", response_model=List[MeditationResponse])
async def search_meditations(
    title: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    meditations = await MeditationService.search_user_meditations_by_name(
        db=db,
        user_id=current_user.id,
        title=title,
        limit=limit,
        offset=offset,
    )
    return [await _hydrate_meditation_response(m) for m in meditations]


@router.get("/{med_id}", response_model=MeditationResponse)
async def get_meditation(med_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    meditation = await MeditationService.get_meditation(db, med_id)
    if not meditation:
        raise HTTPException(status_code=404, detail="Meditation not found")

    session = await SessionService.get_session(db, meditation.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    return await _hydrate_meditation_response(meditation)
