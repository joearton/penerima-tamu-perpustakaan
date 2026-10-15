"""Bunyi notifikasi dan sapaan suara (gTTS, dengan cache MP3 di disk)."""

from __future__ import annotations

import hashlib
import logging
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from library_visitor.config import Settings

log = logging.getLogger(__name__)

MAX_QUEUE = 4
MAX_CACHE_FILES = 500
TTS_LANGUAGES = {
    "id": "Indonesia",
    "en": "Inggris",
    "ar": "Arab",
    "jw": "Jawa",
    "su": "Sunda",
    "ms": "Melayu",
}


def tts_file(cache_dir: Path, text: str, lang: str, slow: bool) -> Path:
    """Hasilkan MP3 lewat gTTS (butuh internet). Teks yang sama diambil dari cache."""
    key = hashlib.sha1(f"{lang}|{slow}|{text}".encode()).hexdigest()
    path = cache_dir / f"{key}.mp3"
    if not path.exists():
        from gtts import gTTS

        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        gTTS(text, lang=lang, slow=slow, timeout=6).save(str(tmp))
        tmp.replace(path)
    return path


def prune_cache(cache_dir: Path, keep: int = MAX_CACHE_FILES) -> None:
    files = sorted(cache_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def ensure_chime(path: Path) -> Path:
    """Buat bunyi 'ding-dong' bawaan sebagai WAV bila belum ada."""
    if path.exists():
        return path
    rate = 44100
    tones = []
    for freq, dur in ((1046.5, 0.18), (784.0, 0.35)):  # C6 lalu G5
        t = np.linspace(0, dur, int(rate * dur), endpoint=False)
        envelope = np.exp(-4 * t / dur)
        tones.append(np.sin(2 * np.pi * freq * t) * envelope)
    samples = (np.concatenate(tones) * 0.5 * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


class Announcer(QObject):
    """Memutar antrean audio satu per satu; TTS dibuat di thread latar."""

    failed = Signal(str)
    _tts_ready = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._queue: deque[Path] = deque()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")
        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        self._tts_ready.connect(self._on_tts_ready)
        self._chime = ensure_chime(settings.data_dir / "sounds" / "chime.wav")
        if settings.tts_cache_dir.exists():
            prune_cache(settings.tts_cache_dir)
        self.apply_settings()

    def apply_settings(self) -> None:
        self._output.setVolume(self._settings.volume / 100)

    def announce(self, text: str, speak: bool = True, chime: bool = True) -> None:
        s = self._settings
        if chime and s.sound_enabled:
            custom = Path(s.sound_file) if s.sound_file else None
            self._enqueue(custom if custom and custom.exists() else self._chime)
        if speak and s.tts_enabled and text:
            self._executor.submit(self._generate, text, s.tts_lang, s.tts_slow)

    def _generate(self, text: str, lang: str, slow: bool) -> None:
        try:
            path = tts_file(self._settings.tts_cache_dir, text, lang, slow)
        except Exception as exc:  # offline, diblokir, bahasa tidak didukung, dll.
            log.warning("TTS gagal: %s", exc)
            self.failed.emit(f"Sapaan suara gagal (cek koneksi internet): {exc}")
            return
        self._tts_ready.emit(str(path))

    def _on_tts_ready(self, path: str) -> None:
        self._enqueue(Path(path))

    def _enqueue(self, path: Path) -> None:
        if len(self._queue) >= MAX_QUEUE:
            self._queue.popleft()
        self._queue.append(path)
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._play_next()

    def _play_next(self) -> None:
        if not self._queue:
            return
        self._player.setSource(QUrl.fromLocalFile(str(self._queue.popleft())))
        self._player.play()

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self._play_next()

    def _on_error(self, _error, message: str) -> None:
        log.warning("Gagal memutar audio: %s", message)
        self._play_next()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._player.stop()
