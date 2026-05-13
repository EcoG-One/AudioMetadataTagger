"""Audio file discovery & metadata extraction."""

import os
import mutagen
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class AudioFile:
    path: Path
    filename: str
    extension: str
    format_name: str = ""
    duration: float = 0.0
    tags: Dict[str, str] = field(default_factory=dict)
    is_valid: bool = True


def _detect_format(ext: str) -> str:
    fmt_map = {
        ".mp3": "MP3",
        ".flac": "FLAC",
        ".m4a": "M4A",
        ".wav": "WAV",
        ".ogg": "OGG",
        ".mp4": "MP4",
        ".wv": "WAVPACK",
    }
    return fmt_map.get(ext.lower(), "UNKNOWN")


def get_existing_tags(file_path: Path) -> Dict[str, str]:
    tags = {}
    try:
        audio = mutagen.File(file_path)
        if not audio:
            return tags
        if hasattr(audio, "tags"):
            tag_dict = audio.tags
            for key in [
                "title",
                "artist",
                "album",
                "tracknumber",
                "date",
                "genre",
                "artist",
                "albumartist",
            ]:
                val = tag_dict.get(key, tag_dict.get(key.upper(), None))
                if val:
                    tags[key] = (
                        str(val[0]) if isinstance(val, (list, tuple)) else str(val)
                    )
    except Exception as e:
        logger.warning(f"Could not read tags for {file_path}: {e}")
    return tags


def scan_folder(root_dir: Path) -> tuple[List[AudioFile], List[str]]:
    """Recursively scan folder for audio files. Returns (valid_files, failed_files)."""
    valid_files = []
    failed_files = []
    root_dir = Path(root_dir).resolve()

    logger.info(f"Scanning folder: {root_dir}")

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        try:
            audio = mutagen.File(file_path)
            if not audio:
                failed_files.append(str(file_path))
                continue

            duration = float(audio.info.length) if audio.info else 0.0
            tags = get_existing_tags(file_path)

            valid_files.append(
                AudioFile(
                    path=file_path,
                    filename=file_path.name,
                    extension=ext,
                    format_name=_detect_format(ext),
                    duration=duration,
                    tags=tags,
                    is_valid=True,
                )
            )
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            failed_files.append(str(file_path))

    # Sort by path for consistent UI order
    valid_files.sort(key=lambda x: x.path)
    return valid_files, failed_files
