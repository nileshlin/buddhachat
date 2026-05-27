from pydantic import BaseModel
from typing import List, Optional

class AudioBlock(BaseModel):
    block: int
    duration: int
    key: Optional[str] = None
    url: Optional[str] = None
    background_music_key: Optional[str] = None
    background_music_url: Optional[str] = None
    type: Optional[str] = None
    has_voice: Optional[bool] = False
    background_audio: Optional[str] = None

class AudioFile(BaseModel):
    duration: Optional[int] = None
    key: Optional[str] = None
    url: Optional[str] = None
    type: Optional[str] = None
    background_audio: Optional[str] = None
    source_background_music_key: Optional[str] = None

class MeditationResponse(BaseModel):
    id: int
    session_id: int
    name: Optional[str] = None
    summary: Optional[str] = None
    script: Optional[List[str]] = None
    audio_blocks: Optional[List[AudioBlock]] = None
    merged_tts_layer: Optional[AudioFile] = None
    merged_music_layer: Optional[AudioFile] = None
    status: str
    progress: int = 0
    is_liked: bool = False

    class Config:
        from_attributes = True
