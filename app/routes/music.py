from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.services.music_service import MusicService
from app.schemas.music import MusicCreate, MusicUpdate, MusicResponse
from app.services.s3_storage import S3Storage
from typing import List, Optional
import uuid


router = APIRouter()

def _music_to_dict(music) -> dict:
    return {
        "id": music.id,
        "display_name": music.display_name,
        "path": music.path,
        "category": music.category,
        "mood": music.mood,
        "description": music.description,
        "tags": music.tags,
    }


@router.post("/add", response_model=MusicResponse)
async def add_music(
    display_name: str = Form(...),
    category: str = Form(...),
    mood: str = Form(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    mood_list = [m.strip() for m in mood.split(',')] if mood else []
    tags_list = [t.strip() for t in tags.split(',')] if tags else []

    storage = S3Storage()
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'mp3'
    bucket_path = f"music/{uuid.uuid4()}.{file_extension}"
    file_bytes = await file.read()
    
    s3_key = await storage.upload_file_bytes(file_bytes, bucket_path, file.content_type)
    
    music_data = MusicCreate(
        display_name=display_name,
        path=s3_key,
        category=category,
        mood=mood_list,
        description=description,
        tags=tags_list
    )
    created = await MusicService.create_music(db, music_data)
    return MusicResponse(**_music_to_dict(created), url=await storage.create_presigned_get_url(created.path))


@router.put("/{music_id}", response_model=MusicResponse)
async def update_music(
    music_id: int,
    display_name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    mood: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    db_music = await MusicService.get_music(db, music_id)
    if not db_music:
        raise HTTPException(status_code=404, detail="Music track not found")
        
    update_data = {}
    if display_name is not None: update_data["display_name"] = display_name
    if category is not None: update_data["category"] = category
    if mood is not None: update_data["mood"] = [m.strip() for m in mood.split(',')]
    if description is not None: update_data["description"] = description
    if tags is not None: update_data["tags"] = [t.strip() for t in tags.split(',')]
    
    if file:
        storage = S3Storage()
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'mp3'
        bucket_path = f"music/{uuid.uuid4()}.{file_extension}"
        file_bytes = await file.read()
        s3_key = await storage.upload_file_bytes(file_bytes, bucket_path, file.content_type)
        update_data["path"] = s3_key
        
    music_update = MusicUpdate(**update_data)
    updated = await MusicService.update_music(db, music_id, music_update)
    if not updated:
        raise HTTPException(status_code=404, detail="Music track not found")
    storage = S3Storage()
    return MusicResponse(**_music_to_dict(updated), url=await storage.create_presigned_get_url(updated.path))


@router.get("/list", response_model=List[MusicResponse])
async def list_music(db: AsyncSession = Depends(get_db)):
    items = await MusicService.list_music(db)
    storage = S3Storage()
    results: List[MusicResponse] = []
    for item in items:
        results.append(MusicResponse(**_music_to_dict(item), url=await storage.create_presigned_get_url(item.path)))
    return results


@router.get("/{music_id}", response_model=MusicResponse)
async def get_music(music_id: int, db: AsyncSession = Depends(get_db)):
    music = await MusicService.get_music(db, music_id)
    if not music:
        raise HTTPException(status_code=404, detail="Music not found")
    storage = S3Storage()
    return MusicResponse(**_music_to_dict(music), url=await storage.create_presigned_get_url(music.path))
