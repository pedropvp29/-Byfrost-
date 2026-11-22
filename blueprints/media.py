"""Byfrost media utilities: photos, animated comment GIFs, authorized audio,
private video files and associated upload validation.

The media implementation is intentionally centralized in this single module.
No dependency on historical media_v9.py or media_v10.py remains.
"""

from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_POST_PHOTOS = 15
MAX_CHAT_PHOTOS = 5
MAX_RAW_IMAGE = 18 * 1024 * 1024
MAX_AUDIO = 12 * 1024 * 1024
MAX_PIXEL_COUNT = 36_000_000
MAX_EDGE = 4096


def jpeg_photo(upload):
    if upload is None or not upload.filename:
        return None
    raw = upload.read(MAX_RAW_IMAGE + 1)
    if len(raw) > MAX_RAW_IMAGE:
        raise ValueError('Photo too large. Choose a file under 18 MB or use the editor to optimize it.')
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Use a JPG, PNG or WebP photo.')
            if im.width * im.height > MAX_PIXEL_COUNT:
                raise ValueError('Photo dimensions are too large. Maximum is 36 megapixels.')
            im = ImageOps.exif_transpose(im)
            if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
                rgba = im.convert('RGBA')
                rgb = Image.new('RGB', rgba.size, '#ffffff')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
            else:
                rgb = im.convert('RGB')
            rgb.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            rgb.save(buffer, 'JPEG', quality=86, optimize=True, progressive=True)
            # Compress further only if needed, while retaining 4K dimensions.
            if buffer.tell() > 5 * 1024 * 1024:
                buffer = BytesIO()
                rgb.save(buffer, 'JPEG', quality=76, optimize=True, progressive=True)
            return buffer.getvalue()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError('Could not read image. Use a valid JPG, PNG or WebP file.') from error


def read_photos(files, max_count):
    uploads = [item for item in files if item and item.filename]
    if len(uploads) > max_count:
        raise ValueError(f'Choose up to {max_count} photos.')
    return [jpeg_photo(file) for file in uploads]


def read_authorized_audio(upload):
    if not upload or not upload.filename:
        return None
    raw = upload.read(MAX_AUDIO + 1)
    if len(raw) > MAX_AUDIO:
        raise ValueError('Audio exceeds 12 MB. Use a shorter licensed/original recording.')
    if len(raw) < 12:
        raise ValueError('Audio file is empty or invalid.')
    if raw[:3] == b'ID3' or (raw[0] == 0xff and raw[1] & 0xe0 == 0xe0):
        mime = 'audio/mpeg'
    elif raw[:4] == b'OggS':
        mime = 'audio/ogg'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WAVE':
        mime = 'audio/wav'
    elif raw[4:8] == b'ftyp' and b'M4A' in raw[8:32]:
        mime = 'audio/mp4'
    else:
        raise ValueError('Unsupported audio format. Use MP3, OGG or WAV.')
    return raw, mime


# Comment image/GIF and protected post-video helpers

from io import BytesIO
from pathlib import Path
import os
import secrets
import tempfile

from PIL import Image, UnidentifiedImageError


MAX_COMMENT_IMAGE = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_COMMENT_PIXELS = 14_000_000


def read_comment_media(upload):
    """Returns (bytes, mime, filename) or None. Preserve GIF animation."""
    if not upload or not upload.filename:
        return None
    raw = upload.read(MAX_COMMENT_IMAGE + 1)
    if len(raw) > MAX_COMMENT_IMAGE:
        raise ValueError('Comment image or GIF must be 8 MB or smaller.')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_COMMENT_PIXELS:
                raise ValueError('Comment image is too large (maximum 14 megapixels).')
            if image.format == 'GIF':
                if getattr(image, 'n_frames', 1) > 180:
                    raise ValueError('GIF has too many frames (maximum 180).')
                # Decode first and last frame to reject obviously truncated files.
                image.seek(0)
                image.load()
                if getattr(image, 'n_frames', 1) > 1:
                    image.seek(image.n_frames - 1)
                    image.load()
                return raw, 'image/gif', 'comment.gif'
            if image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Only JPG, PNG, WebP and animated GIF are supported.')
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError('Invalid photo or GIF file.') from exc
    # Re-open stream as JPEG using V9's sanitizing image processor.
    upload.stream.seek(0)
    return jpeg_photo(upload), 'image/jpeg', 'comment.jpg'


def video_folder(database_path):
    folder = Path(database_path).resolve().parent / 'byfrost_post_videos'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def store_post_video(upload, database_path):
    """Write to a private location, using a random server-side filename.

    Returns (storage_key, mime, filesize), or None. Remove with delete_post_video
    if a subsequent SQL commit fails.
    """
    if not upload or not upload.filename:
        return None
    folder = video_folder(database_path)
    header = upload.stream.read(32)
    upload.stream.seek(0)
    if len(header) >= 12 and header[4:8] == b'ftyp':
        mime, extension = 'video/mp4', '.mp4'
    elif header.startswith(b'\x1a\x45\xdf\xa3'):
        mime, extension = 'video/webm', '.webm'
    else:
        raise ValueError('Upload a valid MP4 or WebM video. Other formats are not supported.')
    token = secrets.token_hex(20) + extension
    target = folder / token
    size = 0
    with tempfile.NamedTemporaryFile(mode='w+b', dir=folder, prefix='.upload-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise ValueError('Video exceeds 64 MB. Choose a shorter or compressed MP4/WebM.')
                stream.write(chunk)
            if size < 1024:
                raise ValueError('Video file is empty or invalid.')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, target)
    target.chmod(0o600)
    return token, mime, size


def video_path(database_path, storage_key):
    # Keys only come from the database; still enforce random key form.
    import re
    if not re.fullmatch(r'[0-9a-f]{40}\.(?:mp4|webm)', storage_key or ''):
        raise ValueError('Invalid media key')
    return video_folder(database_path) / storage_key


def delete_post_video(database_path, storage_key):
    if storage_key:
        video_path(database_path, storage_key).unlink(missing_ok=True)
