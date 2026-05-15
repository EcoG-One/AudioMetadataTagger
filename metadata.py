"""Metadata reading/writing & fuzzy matching."""
import os
import mutagen
from mutagen import File
from mutagen.id3 import ID3, APIC, ID3NoHeaderError, TIT2, TPE1, TALB, TCON, TDRC
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TYER, TCON, APIC as ID3_APIC
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from fuzzywuzzy import fuzz
from typing import List, Dict, Tuple
import requests
import logging

from discogs_client import DiscogsClient


logger = logging.getLogger(__name__)

def fuzzy_match_track(local_filename: str, track_titles: List[str], threshold: int = 75) -> Tuple[str, int]:
    """Match local filename to Discogs track titles using fuzzy logic."""
    local_clean = os.path.splitext(local_filename)[0].replace('-', ' ').replace('_', ' ').lower()
    words = set(local_clean.split())
    
    best_match = ""
    best_score = 0
    
    for title in track_titles:
        title_clean = title.replace('-', ' ').replace('_', ' ').lower()
        # Boost if all words from filename appear in title
        word_match = sum(1 for w in words if w in title_clean) / max(len(words), 1) * 100
        
        partial = fuzz.partial_ratio(local_clean, title_clean)
        score = (partial * 0.6) + (word_match * 0.4)
        
        if score > best_score:
            best_score = score
            best_match = title
            
    return best_match if best_score >= threshold else "", int(best_score)

def embed_artwork(file_path, artwork_bytes: bytes, format_name: str):
    """Embed album art into audio file based on format."""
    try:
        audio = mutagen.File(file_path, easy=False)
        if not audio: return
        
        if format_name == "MP3":
            if not isinstance(audio, ID3):
                audio = ID3(file_path)
            audio.add(ID3_APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=artwork_bytes))
        elif format_name == "FLAC":
            if not isinstance(audio, FLAC):
                audio = FLAC(file_path)
            audio.add_picture(artwork_bytes)
        elif format_name in ("M4A", "MP4"):
            if not isinstance(audio, MP4):
                audio = MP4(file_path)
            audio['covr'] = [artwork_bytes]
        elif format_name == "OGG":
            if not isinstance(audio, OggVorbis):
                audio = OggVorbis(file_path)
            audio['metadata_block_picture'] = mutagen.ogg.vorbis.encode_picture(artwork_bytes)
        elif format_name == "WAV":
            # WAV has limited tag support, often handled by WAVE or skipped gracefully
            pass
        audio.save()
    except Exception as e:
        logger.warning(f"Artwork embedding failed for {file_path}: {e}")


def detect_format(ext: str) -> str:
    fmt_map = {".mp3": "MP3", ".flac": "FLAC", ".m4a": "M4A", ".wav": "WAV", ".ogg": "OGG", ".mp4": "MP4", ".wv": "WAVPACK"}
    return fmt_map.get(ext.lower(), "UNKNOWN")

def write_tags(
    filepath: str,
    tags: dict | None = None,
    artwork_bytes: bytes = None,
):
    """
    Unified metadata writer for MP3, FLAC, M4A/MP4, OGG/Opus.

    Parameters:
        filepath (str): Path to audio file.
        tags (dict): {"title": "...", "artist": "...", "album": "...", "genre": "...", "date": "..."}
        artwork_bytes (bytes): Image data for the album cover.

    Returns:
        bool: True if successful, False otherwise.
    """

    tags = tags or {}

    audio = File(filepath, easy=False)
    if audio is None:
        print(f"Unsupported or unreadable file: {filepath}")
        return False

    ext = os.path.splitext(filepath)[1].lower()
    format_name = detect_format(ext)
    if artwork_bytes and format_name:
        embed_artwork(filepath, artwork_bytes, format_name)

    try:
        # ---------------------------
        # MP3 / ID3
        # ---------------------------
        if ext == ".mp3":
            try:
                id3 = ID3(filepath)
            except ID3NoHeaderError:
                id3 = ID3()

            if "title" in tags:
                id3["TIT2"] = TIT2(encoding=3, text=tags["title"])
            if "artist" in tags:
                id3["TPE1"] = TPE1(encoding=3, text=tags["artist"])
            if "album" in tags:
                id3["TALB"] = TALB(encoding=3, text=tags["album"])
            if "genre" in tags:
                id3["TCON"] = TCON(encoding=3, text=tags["genre"])
            if "date" in tags:
                id3["TDRC"] = TDRC(encoding=3, text=tags["date"])

            id3.save(filepath)
            return True

        # ---------------------------
        # FLAC
        # ---------------------------
        if ext == ".flac":
            for key, value in tags.items():
                audio[key] = value

            audio.save()
            return True

        # ---------------------------
        # M4A / MP4
        # ---------------------------
        if ext in (".m4a", ".mp4"):
            if "title" in tags:
                audio["\xa9nam"] = [tags["title"]]
            if "artist" in tags:
                audio["\xa9ART"] = [tags["artist"]]
            if "album" in tags:
                audio["\xa9alb"] = [tags["album"]]
            if "genre" in tags:
                audio["\xa9gen"] = [tags["genre"]]
            if "date" in tags:
                audio["\xa9day"] = [tags["date"]]

            audio.save()
            return True

        # ---------------------------
        # OGG Vorbis / Opus
        # ---------------------------
        if ext in (".ogg", ".opus"):
            for key, value in tags.items():
                audio[key] = value

            # OGG does not support embedded cover art in Mutagen
            # (requires external metadata block)
            # if cover_path:
            # print("Warning: OGG/Opus does not support embedded cover art via Mutagen.")

            audio.save()
            return True

    except Exception as e:
        print(f"Error writing tags: {e}")
        return False

    return False
