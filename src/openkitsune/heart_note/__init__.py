"""心笺写入器 — 将感受写到 data/heart_notes/，同步到 emotion_engine"""

from openkitsune.heart_note.writer import HeartNoteWriter, get_heart_note_writer

__all__ = ["HeartNoteWriter", "get_heart_note_writer"]
