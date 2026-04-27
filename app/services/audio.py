import httpx
import subprocess
import os
import asyncio
from pathlib import Path
from app.config.settings import settings
from app.config.logger import logger
from app.services.s3_storage import S3Storage
from typing import List, Dict, Optional


class AudioBlockService:
    def __init__(self):
        self.settings = settings
        self.voice_id = self.settings.ELEVENLABS_VOICE_ID
        self.storage = S3Storage()
        logger.info(f"AudioBlockService initialized with voice_id: {self.voice_id}")
        self.base_storage = Path(self.settings.TEMP_DIR) / "audio_blocks"
        self.base_storage.mkdir(parents=True, exist_ok=True)

    async def generate_audio_blocks(
        self,
        scripts: List[str],
        meditation_id: int,
        music_path: Optional[Path] = None,
        progress_callback=None,
        voice_volume: str = "+6.0",
        bg_volume: str = "0.35"
    ) -> List[Dict]:

        med_dir = self.base_storage / f"meditation_{meditation_id}"
        med_dir.mkdir(parents=True, exist_ok=True)

        block_definitions = [
            {"number": 1,  "duration": 90,  "type": "tts",   "script_idx": 0},
            {"number": 2,  "duration": 150, "type": "music", "script_idx": None},
            {"number": 3,  "duration": 120, "type": "music", "script_idx": None},
            {"number": 4,  "duration": 150, "type": "tts",   "script_idx": 1},
            {"number": 5,  "duration": 90,  "type": "tts",   "script_idx": 2},
            {"number": 6,  "duration": 150, "type": "music", "script_idx": None},
            {"number": 7,  "duration": 120, "type": "tts",   "script_idx": 3},
            {"number": 8,  "duration": 120, "type": "tts",   "script_idx": 4},
            {"number": 9,  "duration": 90,  "type": "music", "script_idx": None},
            {"number": 10, "duration": 120, "type": "music", "script_idx": None},
        ]

        results = []

        for block_def in block_definitions:
            block_num = block_def["number"]
            duration_sec = block_def["duration"]
            is_tts = block_def["type"] == "tts"

            logger.info(f"Processing block {block_num} ({'TTS' if is_tts else 'Music'}) - {duration_sec}s")

            final_filename = f"block_{block_num}.mp3"
            final_path = med_dir / final_filename

            if is_tts:
                # Generate TTS + mix with background music
                script_text = scripts[block_def["script_idx"]]
                base_audio_path = await self._generate_base_clip(
                    text=script_text,
                    block_number=block_num,
                    med_dir=med_dir
                )
                await self._loop_audio(
                    input_path=base_audio_path,
                    output_path=final_path,
                    duration_seconds=duration_sec,
                    music_path=music_path,
                    tts=True,
                    voice_volume=voice_volume,
                    bg_volume=bg_volume
                )
            else:
                if music_path and music_path.exists():
                    await self._loop_audio(
                        input_path=music_path,
                        output_path=final_path,
                        duration_seconds=duration_sec,
                        music_path=music_path,
                        tts=False,
                        voice_volume=voice_volume,
                        bg_volume=bg_volume
                    )
                else:
                    # Fallback: create silence if no music available
                    logger.warning(f"No music available for block {block_num} → generating silence")
                    await self._generate_silence(
                        output_path=final_path,
                        duration_seconds=duration_sec
                    )

            bucket_path = f"meditation_{meditation_id}/{final_filename}"
            s3_key = await self.storage.upload_file_path(final_path, bucket_path)

            if final_path.exists():
                os.remove(final_path)

            results.append({
                "block": block_num,
                "duration": duration_sec,
                "key": s3_key,
                "type": block_def["type"],
                "has_voice": is_tts,
                "background_audio": music_path.name if music_path else None
            })
            
            if progress_callback:
                prog = int(40 + (50 * block_num / len(block_definitions)))
                await progress_callback(prog)

        return results

    async def _generate_base_clip(self, text: str, block_number: int, med_dir: Path) -> Path:
        headers = {
            "xi-api-key": self.settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": self.settings.ELEVENLABS_MODEL,
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.75,
                "style": 0.5,
                "use_speaker_boost": True,
            },
        }

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=mp3_44100_128"

        base_path = med_dir / f"base_clip_{block_number}.mp3"

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            with open(base_path, "wb") as f:
                f.write(response.content)

        return base_path

    async def _loop_audio(
        self,
        input_path: Path,
        output_path: Path,
        duration_seconds: int,
        music_path: Optional[Path] = None,
        tts: bool = False,
        voice_volume: str = "+6.0",
        bg_volume: str = "0.35"
    ):
        duration_f = float(duration_seconds)
        VOICE_VOLUME_DB = voice_volume
        BG_VOLUME_VAR = bg_volume

        cmd = [self.settings.FFMPEG_PATH, "-y"]

        if tts:
            if music_path and music_path.exists():
                # TTS + MUSIC
                cmd.extend([
                    "-i", str(input_path),
                    "-stream_loop", "-1", "-i", str(music_path),
                    "-filter_complex",
                    f"[0:a]volume={VOICE_VOLUME_DB}[v];"
                    f"[1:a]volume={BG_VOLUME_VAR}[m];"
                    f"[v][m]amix=inputs=2:duration=longest:dropout_transition=0",
                    "-c:a", "libmp3lame",
                    "-b:a", "128k",
                    "-t", str(duration_f),
                    str(output_path)
                ])
            else:
                # TTS ONLY (fallback)
                cmd.extend([
                    "-i", str(input_path),
                    "-filter_complex",
                    f"[0:a]volume={VOICE_VOLUME_DB},apad[a]",
                    "-map", "[a]",
                    "-c:a", "libmp3lame",
                    "-b:a", "128k",
                    "-t", str(duration_f),
                    str(output_path)
                ])

        else:
            # MUSIC ONLY
            cmd.extend([
                "-stream_loop", "-1", "-i", str(input_path),
                "-filter_complex", f"[0:a]volume={BG_VOLUME_VAR}[a]",
                "-map", "[a]",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-t", str(duration_f),
                str(output_path)
            ])

        def _run():
            logger.info(f"[FFMPEG] {' '.join(cmd)}")
            return subprocess.run(cmd, capture_output=True, text=True)

        res = await asyncio.to_thread(_run)

        if res.returncode != 0:
            logger.error(f"FFmpeg error: {res.stderr}")
            raise RuntimeError("Audio processing failed")

        logger.info(f"Generated audio: {output_path} ({duration_f}s)")

        if tts and input_path.exists():
            os.remove(input_path)

    async def _generate_silence(self, output_path: Path, duration_seconds: int):
        duration_f = float(duration_seconds)
        cmd = [
            self.settings.FFMPEG_PATH, "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono:d={duration_f}",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ar", "44100",
            str(output_path)
        ]

        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Silence generation failed: {result.stderr}")
            raise RuntimeError("Failed to generate silence")

        logger.info(f"Generated silence block: {output_path} ({duration_f}s)")
