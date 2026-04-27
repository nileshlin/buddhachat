import asyncio
import json
from pathlib import Path

# Adjust sys path so we can run directly as python scripts/seed_music.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database.db import engine
from app.database.models import Base, Music
from app.services.s3_storage import S3Storage
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def seed_music():
    print("Initializing Database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    storage = S3Storage()
    
    json_file_path = Path("storage/music_catalog.json")
    if not json_file_path.exists():
        print(f"Catalog not found at {json_file_path}")
        return

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    print(f"Reading catalog: {json_file_path}")
    
    with open(json_file_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
        async with async_session() as session:
            for item in catalog:
                local_rel_path = item["path"] # e.g. "music/mindfulness_01.mp3"
                local_path = Path("storage") / local_rel_path
                
                print(f"Processing {item['display_name']} ...")
                
                if not local_path.exists():
                    print(f" -> Local file missing at {local_path}. Skipping upload.")
                    continue
                else:
                    print(f" -> Uploading {local_path} to S3 at {local_rel_path}...")
                    s3_key = await storage.upload_file_path(local_path, local_rel_path)
                    print(f" -> Upload complete! Key: {s3_key}")

                moods = item["mood"]
                tags = item["tags"]

                # Check if exists
                stmt = select(Music).where(Music.display_name == item["display_name"])
                result = await session.execute(stmt)
                existing = result.scalars().first()
                
                if existing:
                    print(f" -> Updating existing DB record for {item['display_name']}")
                    existing.path = s3_key
                    existing.category = item["category"]
                    existing.mood = moods
                    existing.description = item["description"]
                    existing.tags = tags
                else:
                    print(f" -> Creating new DB record for {item['display_name']}")
                    new_music = Music(
                        display_name=item["display_name"],
                        path=s3_key,
                        category=item["category"],
                        mood=moods,
                        description=item["description"],
                        tags=tags
                    )
                    session.add(new_music)
            
            await session.commit()
    print("\nDatabase Seeding Complete!")

if __name__ == "__main__":
    asyncio.run(seed_music())
