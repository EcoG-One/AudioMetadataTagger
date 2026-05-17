"""Audio file discovery & metadata extraction."""
import music_tag
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from config import SUPPORTED_EXTENSIONS
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
    fmt_map = {".mp3": "MP3", ".flac": "FLAC", ".m4a": "M4A", ".wav": "WAV", ".ogg": "OGG", ".mp4": "MP4", ".wv": "WAVPACK"}
    return fmt_map.get(ext.lower(), "UNKNOWN")

def get_existing_tags(file_path: Path) -> Dict[str, str]:
    tags = {}
    try:
        audio = music_tag.load_file(file_path)
        if not audio:
            return tags
        for key in [
            "album",
            "albumartist",
            "artist",
            "tracktitle",
            "tracknumber",
            "date",
            "genre",
        ]:
            val = audio.get(key, audio.get(key.upper(), None))
            if val:
                tags[key] = str(val[0]) if isinstance(val, (list, tuple)) else str(val)
    except Exception as e:
        logger.warning(f"Could not read tags for {file_path}: {e}")
    return tags

def scan_folder(root_dir: Path) -> tuple[List[AudioFile], List[str]]:
    """Recursively scan folder for audio files. Returns (valid_files, failed_files)."""

    valid_files = []
    failed_files = []
    root_dir = Path(root_dir).resolve()

    logger.info(f"Scanning folder: {root_dir}")

    for file_path in root_dir.rglob('*'):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        try:
            audio = music_tag.load_file(file_path)
            if not audio:
                folder_info = _extract_file_info(file_path, root_dir)
                if folder_info:
                    tags["albumartist"] = folder_info.get("folder_artist", "")
                    tags["album"] = folder_info.get("folder_album", "")
                valid_files.append(
                    AudioFile(
                        path=file_path,
                        filename=file_path.name,
                        extension=ext,
                        format_name=_detect_format(ext),
                        duration=0.0,
                        tags=tags,
                        is_valid=False,
                    )
                )
                continue

            # relative_path = file_path.relative_to(root_dir)
            duration = audio['#length'] if audio else 0.0
            tags = get_existing_tags(file_path)

            if not tags.get("albumartist") or not tags.get("album"):
                # Try to extract from folder structure if tags are missing or invalid
                folder_info = _extract_file_info(file_path, root_dir)
                if folder_info:
                    if not tags.get("albumartist"):
                        tags["albumartist"] = folder_info.get("folder_artist", "")
                    if not tags.get("album"):
                        tags["album"] = folder_info.get("folder_album", "")

            valid_files.append(
                AudioFile(
                    path=file_path,
                    filename=file_path.name,
                    extension=ext,
                    format_name=_detect_format(ext),
                    duration=duration,
                    tags=tags,
                    is_valid=True,
                ))

        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            failed_files.append(str(file_path))

    # Sort by path for consistent UI order
    valid_files.sort(key=lambda x: x.path)
    return valid_files, failed_files

def _extract_file_info(file_path: Path, root_path: Path) -> Optional[Dict]:
    """
    Extract file information including folder-based artist/album names.
    
    Assumes folder structure: RootPath/Artist/Album/Song.mp3
    
    Args:
        file_path: Path to audio file
        root_path: Root scanning path
        
    Returns:
        Dictionary with file info or None if extraction fails
    """
    try:
        # Get relative path from root
        relative_path = file_path.relative_to(root_path)
        parts = file_path.parts

        # Extract artist and album from folder structure
        artist = ""
        album = ""

        if len(parts) >= 3:
            # Assume: Artist/Album/Track.mp3
            artist = parts[-3]
            album = parts[-2]
        elif len(parts) == 2:
            # Assume: Album/Track.mp3 (no artist folder)
            album = parts[-2]

        file_info = {
            "file_path": file_path,
            "relative_path": str(relative_path),
            "filename": file_path.stem,
            "format_name": _detect_format(file_path.suffix.lower()),
            "duration": "--",
            "artist": artist,
            "folder_album": album,
        }

        return file_info

    except Exception as e:
        logger.error(f"Error extracting file info from {file_path}: {e}")
        return None

@staticmethod
def group_by_album(files: List[Dict]) -> Dict[tuple, List[Dict]]:
    """
    Group audio files by artist/album combination.
    
    Args:
        files: List of file info dictionaries
        
    Returns:
        Dictionary with (artist, album) tuples as keys and file lists as values
    """
    grouped = {}
    
    for file_info in files:
        artist = file_info.get("folder_artist", "Unknown Artist")
        album = file_info.get("folder_album", "Unknown Album")
        key = (artist, album)
        
        if key not in grouped:
            grouped[key] = []
        
        grouped[key].append(file_info)
    
    logger.info(f"Grouped {len(files)} files into {len(grouped)} album(s)")
    return grouped

@staticmethod
def verify_artist_album(artist: str, album: str) -> bool:
    """
    Verify that artist and album names are valid (non-empty and reasonable length).
    
    Args:
        artist: Artist name
        album: Album name
        
    Returns:
        True if both are valid, False otherwise
    """
    if not artist or not album:
        return False
    
    if len(artist.strip()) == 0 or len(album.strip()) == 0:
        return False
    
    # Reject names that are just track numbers or single characters
    if artist.strip().isdigit() or album.strip().isdigit():
        return False
    
    if len(artist.strip()) < 2 or len(album.strip()) < 2:
        return False
    
    return True
