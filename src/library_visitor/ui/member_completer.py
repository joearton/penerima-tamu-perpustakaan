"""Auto-complete anggota untuk QLineEdit: anggota lokal + pencarian direktori (bila tersedia)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QModelIndex, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter, QLineEdit

from library_visitor.extensions import DirectoryPerson, ExtensionError, MemberDirectory
from library_visitor.services import VisitorService

log = logging.getLogger(__name__)

PERSON_ROLE = Qt.ItemDataRole.UserRole + 1
INSERT_ROLE = Qt.ItemDataRole.UserRole + 2  # teks yang dimasukkan ke QLineEdit saat dipilih
REGISTERED_ROLE = Qt.ItemDataRole.UserRole + 3
LOCAL_LIMIT = 6
REMOTE_LIMIT = 10
DEBOUNCE_MS = 350
MIN_LOCAL_CHARS = 2
MIN_REMOTE_CHARS = 3


class MemberCompleter(QObject):
    """`field` menentukan teks yang disisipkan: "member_no" atau "name"."""

    chosen = Signal(object, bool)  # DirectoryPerson, sudah terdaftar lokal?
    _remote_done = Signal(str, list)

    def __init__(
        self,
        line_edit: QLineEdit,
        service: VisitorService,
        directory: MemberDirectory | None,
        field: str,
    ) -> None:
        super().__init__(line_edit)
        self._edit = line_edit
        self._service = service
        self._directory = directory if getattr(directory, "supports_search", False) else None
        self._field = field
        self._local: list[tuple[DirectoryPerson, bool]] = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autocomplete")

        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setCompletionRole(INSERT_ROLE)
        self._completer.setMaxVisibleItems(10)
        self._completer.activated[QModelIndex].connect(self._on_activated)
        line_edit.setCompleter(self._completer)

        self._debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._debounce.timeout.connect(self._search_remote)
        self._remote_done.connect(self._on_remote_done)
        line_edit.textEdited.connect(self._on_edited)

    def _on_edited(self, text: str) -> None:
        text = text.strip()
        self._local = []
        if len(text) >= MIN_LOCAL_CHARS:
            self._local = [
                (_person(m), True) for m in self._service.list_members(text, limit=LOCAL_LIMIT)
            ]
        self._show(self._local)
        if self._directory is not None and len(text) >= MIN_REMOTE_CHARS:
            self._debounce.start()
        else:
            self._debounce.stop()

    def _search_remote(self) -> None:
        text = self._edit.text().strip()
        self._executor.submit(self._remote_worker, text)

    def _remote_worker(self, text: str) -> None:
        try:
            people = self._directory.search(text, limit=REMOTE_LIMIT)
        except ExtensionError as exc:
            log.warning("Pencarian direktori gagal: %s", exc)
            return
        self._remote_done.emit(text, people)

    def _on_remote_done(self, text: str, people: list[DirectoryPerson]) -> None:
        if text != self._edit.text().strip() or not self._edit.hasFocus():
            return  # sudah diketik ulang / pindah field
        local_nos = {p.member_no for p, _ in self._local}
        merged = self._local + [(p, False) for p in people if p.member_no not in local_nos]
        self._show(merged)

    def _show(self, entries: list[tuple[DirectoryPerson, bool]]) -> None:
        self._model.clear()
        for person, registered in entries:
            detail = " · ".join(x for x in (person.category, person.unit) if x)
            tag = "terdaftar" if registered else (person.status or "direktori")
            item = QStandardItem(f"{person.member_no} — {person.name}   ({detail}; {tag})")
            item.setData(person, PERSON_ROLE)
            item.setData(registered, REGISTERED_ROLE)
            item.setData(getattr(person, self._field), INSERT_ROLE)
            self._model.appendRow(item)
        if entries and self._edit.hasFocus():
            self._completer.complete()
        elif not entries:
            self._completer.popup().hide()

    def _on_activated(self, index: QModelIndex) -> None:
        person = index.data(PERSON_ROLE)
        if person is not None:
            self.chosen.emit(person, bool(index.data(REGISTERED_ROLE)))


def _person(member) -> DirectoryPerson:
    return DirectoryPerson(
        member.member_no,
        member.name,
        member.category,
        member.unit or "",
        member.directory_status or "",
    )
