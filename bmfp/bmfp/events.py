"""A heapq event queue with a deterministic tie-break.

Entries are ``(time, seq, kind, payload)``; ``seq`` is an insertion counter, so two events
at the same time always pop in the order they were pushed. No wall clock is involved.
"""

from __future__ import annotations

import heapq
from typing import Any

SEND = "SEND"
RETRY = "RETRY"
DELIVER = "DELIVER"
RESONANCE = "RESONANCE"
VSEPR = "VSEPR"
CHECKPOINT = "CHECKPOINT"
CAPTAIN_TERM = "CAPTAIN_TERM"
KILL = "KILL"
LEAVE = "LEAVE"
DETECT = "DETECT"
DEATH_EVENT = "DEATH_EVENT"
MITOSIS_DONE = "MITOSIS_DONE"
MEIOSIS_DONE = "MEIOSIS_DONE"
JOIN = "JOIN"
BIN = "BIN"

KINDS = (
    SEND,
    RETRY,
    DELIVER,
    RESONANCE,
    VSEPR,
    CHECKPOINT,
    CAPTAIN_TERM,
    KILL,
    LEAVE,
    DETECT,
    DEATH_EVENT,
    MITOSIS_DONE,
    MEIOSIS_DONE,
    JOIN,
    BIN,
)


class EventQueue:
    """Min-heap of ``(time, seq, kind, payload)``."""

    __slots__ = ("_heap", "_seq")

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, str, Any]] = []
        self._seq = 0

    def push(self, time: float, kind: str, payload: Any = None) -> int:
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        if time != time:  # NaN guard
            raise ValueError("event time is NaN")
        seq = self._seq
        self._seq += 1
        heapq.heappush(self._heap, (float(time), seq, kind, payload))
        return seq

    def pop(self) -> tuple[float, int, str, Any]:
        return heapq.heappop(self._heap)

    def peek_time(self) -> float | None:
        return self._heap[0][0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)

    @property
    def pushed(self) -> int:
        """Total number of events ever pushed."""
        return self._seq
