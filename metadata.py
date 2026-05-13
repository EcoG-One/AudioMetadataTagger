"""Metadata reading/writing & fuzzy matching."""
import os
import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TYER, TCON, APIC as ID3_APIC
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from fuzzywuzzy import fuzz
from typing import List, Dict, Tuple
import logging

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

def write_metadata(file_path: str, tags: dict, artwork_bytes: bytes = None, format_name: str = ""):
    """Write tags to audio file."""
    try:
        audio = mutagen.File(file_path, easy=False)
        if not audio: return
        
        for key, val in tags.items():
            if hasattr(audio, 'tags'):
                if key == 'title': audio.tags.add(TIT2(encoding=3, text=str(val)))
                elif key == 'artist': audio.tags.add(TPE1(encoding=3, text=str(val)))
                elif key == 'album': audio.tags.add(TALB(encoding=3, text=str(val)))
                elif key == 'tracknumber': audio.tags.add(TRCK(encoding=3, text=str(val)))
                elif key == 'date': audio.tags.add(TYER(encoding=3, text=str(val)))
                elif key == 'genre': audio.tags.add(TCON(encoding=3, text=str(val)))
            elif hasattr(audio, 'tags'):
                audio.tags[key] = val
            else:
                audio[key] = val
                
        if artwork_bytes and format_name:
            embed_artwork(file_path, artwork_bytes, format_name)
            
        audio.save()
        return True
    except Exception as e:
        logger.error(f"Failed to write metadata to {file_path}: {e}")
        return False
