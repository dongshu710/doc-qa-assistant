"""智能体笔记存储：文件是唯一真相，索引只是可重建的缓存。

对外只暴露少数几个名字，方便后续 MCP / HTTP 复用同一套用例层。
"""

from .model import KINDS, SECTION_ORDER, STATUSES, Note, NoteError, Section
from .service import NoteConflict, NoteService
from .store import NoteNotFound, NoteStore, SaveResult, StoreBusy

__all__ = [
    "KINDS", "SECTION_ORDER", "STATUSES",
    "Note", "NoteError", "Section",
    "NoteConflict", "NoteService", "NoteNotFound", "NoteStore", "SaveResult", "StoreBusy",
]
