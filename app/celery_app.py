import asyncio
import os
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError
from celery import Celery
from pathlib import Path
import httpx

from datetime import datetime, timedelta
from sqlalchemy import update

from app.config.settings import settings
from app.config.logger import logger
from app.database.db import AsyncSessionLocal
from app.database.models import MeditationStatus, Meditation
from app.services.openai_service import OpenAIService
from app.services.meditation_service import MeditationService
from app.services.session_service import SessionService
from app.services.user_service import UserService
from app.services.music_service import MusicService
from app.services.audio import AudioBlockService
from app.services.s3_storage import S3Storage

celery_app = Celery(
    "meditation_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# Optional celery configurations
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "recover-stuck-meditations": {
            "task": "recover_stuck_meditations_task",
            "schedule": 600.0, # Every 10 minutes
        }
    }
)

# Celery's default prefork pool is unreliable on Windows (billiard/multiprocessing handle/semaphore issues),
# often resulting in PermissionError: [WinError 5] Access is denied. Use the solo pool for local/dev on Windows.
if os.name == "nt":
    celery_app.conf.worker_pool = "solo"
    celery_app.conf.worker_concurrency = 1

_bg_loop = None
_bg_loop_thread = None
_bg_loop_ready = threading.Event()
_bg_loop_lock = threading.Lock()


def _run_background_loop():
    global _bg_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _bg_loop = loop
    _bg_loop_ready.set()
    loop.run_forever()


def _get_background_loop():
    global _bg_loop_thread
    if _bg_loop and _bg_loop.is_running():
        return _bg_loop

    with _bg_loop_lock:
        if _bg_loop and _bg_loop.is_running():
            return _bg_loop

        _bg_loop_ready.clear()
        _bg_loop_thread = threading.Thread(target=_run_background_loop, name="celery-asyncio-loop", daemon=True)
        _bg_loop_thread.start()
        _bg_loop_ready.wait(timeout=10)
        if not _bg_loop or not _bg_loop.is_running():
            raise RuntimeError("Failed to start background asyncio event loop")
        return _bg_loop


def _run_async(coro, timeout: float | None = None):
    loop = _get_background_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeoutError:
        fut.cancel()
        raise

async def async_generate_meditation(med_id: int, session_id: int, user_id: int):
    async def _mark_failed():
        async with AsyncSessionLocal() as db_fail:
            await MeditationService.update_meditation(
                db_fail,
                med_id,
                status=MeditationStatus.FAILED,
                return_entity=False
            )

    try:
        async with AsyncSessionLocal() as db:
            logger.info(f"[meditation:{med_id}] Generation started (session_id={session_id}, user_id={user_id})")
            await MeditationService.update_meditation(
                db,
                med_id,
                status=MeditationStatus.GENERATING,
                progress=5,
                return_entity=False
            )
            session = await SessionService.get_session(db, session_id)
            if not session or session.user_id != user_id:
                raise ValueError("Unauthorized or session missing")

            user = await UserService.get_user(db, user_id)
            prefs = user.preferences
            language = prefs.language if prefs else "English"
            voice_vol = prefs.voice_volume if prefs else settings.DEFAULT_VOICE_VOLUME
            bg_vol = prefs.bg_volume if prefs else settings.DEFAULT_BG_VOLUME

            messages = await SessionService.get_session_messages(db, session_id)

            ai_service = OpenAIService()
            summary = await ai_service.summarize_conversation(messages)
            logger.info(f"[meditation:{med_id}] Conversation summarized")
            await MeditationService.update_meditation(db, med_id, progress=15, return_entity=False)

            script_output = await ai_service.generate_meditation_script(summary, language=language)
            scripts = script_output.script
            med_name = script_output.name
            tags = script_output.music_tags

            await MeditationService.update_meditation(db, med_id, progress=30, name=med_name, return_entity=False)
            logger.info(f"[meditation:{med_id}] Script generated, selecting music")

            music = await MusicService.get_matching_music(db, tags=tags)
            music_path = None
            temp_music_path = None
            if music:
                try:
                    temp_music_path = Path(settings.TEMP_DIR) / f"temp_{music.id}.mp3"
                    temp_music_path.parent.mkdir(parents=True, exist_ok=True)
                    storage = S3Storage()
                    music_url = await storage.create_presigned_get_url(music.path)
                    async with httpx.AsyncClient(timeout=120) as client:
                        resp = await client.get(music_url)
                        resp.raise_for_status()
                        with open(temp_music_path, "wb") as f:
                            f.write(resp.content)
                    music_path = temp_music_path
                    logger.info(f"Downloaded remote background music to: {temp_music_path}")
                except Exception:
                    logger.exception(f"[meditation:{med_id}] Failed to download background music; continuing without it")
                    if temp_music_path:
                        try:
                            temp_music_path.unlink(missing_ok=True)
                        except Exception:
                            logger.exception(f"Failed to delete temp music file: {temp_music_path}")
                    temp_music_path = None
                    music_path = None

            await MeditationService.update_meditation(db, med_id, progress=40, return_entity=False)
            logger.info(f"[meditation:{med_id}] Generating audio blocks")

            db_lock = asyncio.Lock()

            async def safe_update(**kwargs):
                async with db_lock:
                    await MeditationService.update_meditation(db, med_id, return_entity=False, **kwargs)

            async def update_progress(p: int):
                try:
                    await safe_update(progress=p)
                except Exception:
                    logger.exception(f"[meditation:{med_id}] Failed to update progress={p}")

            audio_service = AudioBlockService()
            audio_blocks = await audio_service.generate_audio_blocks(
                scripts,
                meditation_id=med_id,
                music_path=music_path,
                progress_callback=update_progress,
                voice_volume=voice_vol,
                bg_volume=bg_vol
            )

            if temp_music_path:
                try:
                    temp_music_path.unlink(missing_ok=True)
                except Exception:
                    logger.exception(f"Failed to delete temp music file: {temp_music_path}")

            await MeditationService.update_meditation(
                db,
                med_id,
                summary=summary,
                script=scripts,
                audio_blocks=audio_blocks,
                status=MeditationStatus.COMPLETED,
                progress=100,
                return_entity=False
            )
            logger.info(f"[meditation:{med_id}] Generation completed")
    except Exception:
        logger.exception(f"[meditation:{med_id}] Meditation generation failed")
        try:
            await _mark_failed()
        except Exception:
            logger.exception(f"[meditation:{med_id}] Failed to mark meditation as FAILED")


@celery_app.task(name="generate_meditation_task")
def generate_meditation_task(med_id: int, session_id: int, user_id: int):
    logger.info(f"[meditation:{med_id}] Celery task invoked")
    _run_async(async_generate_meditation(med_id, session_id, user_id))


async def async_recover_stuck_meditations():
    async with AsyncSessionLocal() as db:
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        stmt = (
            update(Meditation)
            .where(Meditation.status == MeditationStatus.GENERATING)
            .where(Meditation.updated_at < cutoff)
            .values(status=MeditationStatus.FAILED)
        )
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount > 0:
            logger.info(f"Recovered {result.rowcount} stuck meditations to FAILED state.")

@celery_app.task(name="recover_stuck_meditations_task")
def recover_stuck_meditations_task():
    _run_async(async_recover_stuck_meditations())
