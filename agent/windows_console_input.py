from __future__ import annotations

import ctypes
from ctypes import wintypes


STD_INPUT_HANDLE = -10
KEY_EVENT = 0x0001


class _CharUnion(ctypes.Union):
    _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]


class _KeyEventRecord(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", _CharUnion),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _InputRecordUnion(ctypes.Union):
    _fields_ = [("KeyEvent", _KeyEventRecord)]


class _InputRecord(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", _InputRecordUnion)]


def _key_record(char: str, *, key_down: bool) -> _InputRecord:
    event = _KeyEventRecord()
    event.bKeyDown = 1 if key_down else 0
    event.wRepeatCount = 1
    event.wVirtualKeyCode = 0x0D if char == "\r" else 0
    event.wVirtualScanCode = 0
    event.uChar.UnicodeChar = char
    event.dwControlKeyState = 0

    record = _InputRecord()
    record.EventType = KEY_EVENT
    record.Event = _InputRecordUnion()
    record.Event.KeyEvent = event
    return record


def write_console_text(text: str, *, submit: bool = True) -> None:
    cleaned = str(text or "")
    if not cleaned and not submit:
        return

    chars = list(cleaned)
    if submit:
        chars.append("\r")

    records = []
    for char in chars:
        records.append(_key_record(char, key_down=True))
        records.append(_key_record(char, key_down=False))

    handle = ctypes.windll.kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if handle in (0, -1):
        raise OSError("failed to open console input handle")

    written = wintypes.DWORD()
    array_type = _InputRecord * len(records)
    success = ctypes.windll.kernel32.WriteConsoleInputW(
        handle,
        array_type(*records),
        len(records),
        ctypes.byref(written),
    )
    if not success or written.value != len(records):
        raise OSError("failed to inject text into console input buffer")
