import httpx
import subprocess
import os
import asyncio
from pathlib import Path
from app.config.settings import settings
from app.config.logger import logger
from app.services.s3_storage import S3Storage
from typing import Any, List, Dict, Optional


class AudioBlockService:
    def __init__(self):
        self.settings = settings
        self.voice_id = self.settings.ELEVENLABS_VOICE_ID
        self.storage = S3Storage()
        logger.info(f"AudioBlockService initialized with voice_id: {self.voice_id}")
        self.base_storage = Path(self.settings.TEMP_DIR) / "audio_blocks"
        self.base_storage.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _format_volume(value: str, *, signed_values_are_db: bool = False) -> str:
        volume = str(value).strip()
        if signed_values_are_db and volume and volume[0] in "+-" and not volume.lower().endswith("db"):
            return f"{volume}dB"
        return volume

    async def generate_audio_blocks(
        self,
        scripts: List[str],
        meditation_id: int,
        music_path: Optional[Path] = None,
        music_key: Optional[str] = None,
        progress_callback=None,
        voice_volume: str = "+6.0",
        bg_volume: str = "0.35"
    ) -> Dict[str, Any]:

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
        block_paths: list[Path] = []
        background_block_paths: list[Path] = []
        tts_layer_paths: list[Path] = []
        temp_layer_paths: list[Path] = []

        try:
            for block_def in block_definitions:
                block_num = block_def["number"]
                duration_sec = block_def["duration"]
                is_tts = block_def["type"] == "tts"

                logger.info(f"Processing block {block_num} ({'TTS' if is_tts else 'Music'}) - {duration_sec}s")

                final_filename = f"block_{block_num}.mp3"
                final_path = med_dir / final_filename

                if is_tts:
                    # Generate voice-only TTS blocks. 
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
                        tts=True,
                        voice_volume=voice_volume,
                        bg_volume=bg_volume,
                        pan_effect=block_num == 8
                    )

                    background_music_key = None
                    if music_path and music_path.exists():
                        background_filename = f"block_{block_num}_background.mp3"
                        background_path = med_dir / background_filename
                        await self._loop_audio(
                            input_path=music_path,
                            output_path=background_path,
                            duration_seconds=duration_sec,
                            tts=False,
                            voice_volume=voice_volume,
                            bg_volume=bg_volume
                        )
                        background_block_paths.append(background_path)
                        background_bucket_path = f"meditation_{meditation_id}/{background_filename}"
                        background_music_key = await self.storage.upload_file_path(
                            background_path,
                            background_bucket_path
                        )

                    tts_layer_paths.append(final_path)
                else:
                    background_music_key = None
                    if music_path and music_path.exists():
                        await self._loop_audio(
                            input_path=music_path,
                            output_path=final_path,
                            duration_seconds=duration_sec,
                            tts=False,
                            voice_volume=voice_volume,
                            bg_volume=bg_volume
                        )
                    else:
                        # Fallback: create silence if no music available
                        logger.warning(f"No music available for block {block_num}; generating silence")
                        await self._generate_silence(
                            output_path=final_path,
                            duration_seconds=duration_sec
                        )

                    silence_path = med_dir / f"block_{block_num}_tts_silence.mp3"
                    await self._generate_silence(
                        output_path=silence_path,
                        duration_seconds=duration_sec
                    )
                    temp_layer_paths.append(silence_path)
                    tts_layer_paths.append(silence_path)

                block_paths.append(final_path)

                bucket_path = f"meditation_{meditation_id}/{final_filename}"
                s3_key = await self.storage.upload_file_path(final_path, bucket_path)

                results.append({
                    "block": block_num,
                    "duration": duration_sec,
                    "key": s3_key,
                    "type": block_def["type"],
                    "has_voice": is_tts,
                    "background_audio": (
                        music_path.name if (not is_tts and music_path) else None
                    ),
                    "background_music_key": background_music_key,
                    "source_background_music_key": music_key,
                })

                if progress_callback:
                    prog = int(40 + (50 * block_num / len(block_definitions)))
                    await progress_callback(prog)

            total_duration = sum(block["duration"] for block in results)

            merged_tts_layer_filename = "merged_tts_layer.mp3"
            merged_tts_layer_path = med_dir / merged_tts_layer_filename
            await self._merge_audio_blocks(tts_layer_paths, merged_tts_layer_path)
            merged_tts_layer_bucket_path = f"meditation_{meditation_id}/{merged_tts_layer_filename}"
            merged_tts_layer_s3_key = await self.storage.upload_file_path(
                merged_tts_layer_path,
                merged_tts_layer_bucket_path
            )

            merged_music_layer_filename = "merged_music_layer.mp3"
            merged_music_layer_path = med_dir / merged_music_layer_filename
            if music_path and music_path.exists():
                await self._loop_audio(
                    input_path=music_path,
                    output_path=merged_music_layer_path,
                    duration_seconds=total_duration,
                    tts=False,
                    voice_volume=voice_volume,
                    bg_volume=bg_volume
                )
            else:
                logger.warning("No music available for merged music layer; generating silence")
                await self._generate_silence(
                    output_path=merged_music_layer_path,
                    duration_seconds=total_duration
                )

            merged_music_layer_bucket_path = f"meditation_{meditation_id}/{merged_music_layer_filename}"
            merged_music_layer_s3_key = await self.storage.upload_file_path(
                merged_music_layer_path,
                merged_music_layer_bucket_path
            )

            if progress_callback:
                await progress_callback(95)

            return {
                "blocks": results,
                "merged_tts_layer": {
                    "key": merged_tts_layer_s3_key,
                    "duration": total_duration,
                    "type": "tts_layer",
                    "background_audio": None
                },
                "merged_music_layer": {
                    "key": merged_music_layer_s3_key,
                    "duration": total_duration,
                    "type": "music_layer",
                    "background_audio": music_path.name if music_path else None,
                    "source_background_music_key": music_key,
                }
            }
        finally:
            cleanup_paths = [
                *block_paths,
                *background_block_paths,
                *temp_layer_paths,
                med_dir / "merged_tts_layer.mp3",
                med_dir / "merged_music_layer.mp3",
                med_dir / "concat_blocks.txt",
            ]
            for path in cleanup_paths:
                if path.exists():
                    try:
                        os.remove(path)
                    except OSError:
                        logger.exception(f"Failed to remove temporary audio file: {path}")

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

    @staticmethod
    def _escape_concat_path(path: Path) -> str:
        return path.resolve().as_posix().replace("'", r"'\''")

    async def _merge_audio_blocks(self, block_paths: list[Path], output_path: Path):
        if not block_paths:
            raise RuntimeError("No audio blocks available to merge")

        concat_file = output_path.parent / "concat_blocks.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for path in block_paths:
                f.write(f"file '{self._escape_concat_path(path)}'\n")

        cmd = [
            self.settings.FFMPEG_PATH, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ac", "2",
            "-ar", "44100",
            str(output_path)
        ]

        def _run():
            logger.info(f"[FFMPEG] {' '.join(cmd)}")
            return subprocess.run(cmd, capture_output=True, text=True)

        result = await asyncio.to_thread(_run)

        if result.returncode != 0:
            logger.error(f"Audio merge failed: {result.stderr}")
            raise RuntimeError("Failed to merge audio blocks")

        logger.info(f"Generated merged audio: {output_path}")

    async def _loop_audio(
        self,
        input_path: Path,
        output_path: Path,
        duration_seconds: int,
        tts: bool = False,
        voice_volume: str = "+6.0",
        bg_volume: str = "0.35",
        pan_effect: bool = False
    ):
        duration_f = float(duration_seconds)
        VOICE_VOLUME_DB = self._format_volume(voice_volume, signed_values_are_db=True)
        BG_VOLUME_VAR = self._format_volume(bg_volume)

        cmd = [self.settings.FFMPEG_PATH, "-y"]

        if tts:
            pan_filter = ",apulsator=hz=0.08:width=0.55" if pan_effect else ""
            # TTS ONLY
            cmd.extend([
                "-i", str(input_path),
                "-filter_complex",
                f"[0:a]volume={VOICE_VOLUME_DB},apad,aformat=channel_layouts=stereo{pan_filter}[a]",
                "-map", "[a]",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-ac", "2",
                "-t", str(duration_f),
                str(output_path)
            ])

        else:
            # MUSIC ONLY
            cmd.extend([
                "-stream_loop", "-1", "-i", str(input_path),
                "-filter_complex", f"[0:a]volume={BG_VOLUME_VAR},aformat=channel_layouts=stereo[a]",
                "-map", "[a]",
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-ac", "2",
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
            "-i", f"anullsrc=r=44100:cl=stereo:d={duration_f}",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ac", "2",
            "-ar", "44100",
            str(output_path)
        ]

        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Silence generation failed: {result.stderr}")
            raise RuntimeError("Failed to generate silence")

        logger.info(f"Generated silence block: {output_path} ({duration_f}s)")
