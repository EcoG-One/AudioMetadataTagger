"""Metadata reading/writing & fuzzy matching."""
import os
import music_tag
from fuzzywuzzy import fuzz
from typing import List, Dict, Optional, Tuple
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


def write_tags(file_path: str, metadata: Dict, artwork_bytes: Optional[bytes] = None,
                   overwrite: bool = False) -> bool:
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

    try:
        logger.info(f"Writing tags to: {file_path}")
        audio_file = music_tag.load(file_path)

        # Map metadata to tag fields
        tag_mapping = {
            "title": "title",
            "album": "album",
            "artist": "artist",
            "albumartist": "albumartist",
            "tracknumber": "tracknumber",
            "date": "year",
            "genre": "genre",
            "comment": "comments"
        }

        for meta_key, tag_key in tag_mapping.items():
            if meta_key in metadata and metadata[meta_key]:
                existing_value = str(audio_file.get(tag_key, "")).strip()

                # Only write if empty or overwrite is True
                if overwrite or not existing_value:
                    audio_file[tag_key] = str(metadata[meta_key])
                    logger.debug(f"  {tag_key}: {metadata[meta_key]}")

        # Write album art if provided
        if artwork_bytes:
            try:
                logger.debug("Writing album artwork...")
                audio_file["artwork"] = artwork_bytes
            except Exception as e:
                logger.warning(f"Could not write artwork: {e}")

        # Save the audio_file
        audio_file.save()
        logger.info(f"Successfully saved tags to: {file_path.name}")
        return True

    except Exception as e:
        logger.error(f"Error writing tags to {file_path}: {e}")
        return False
