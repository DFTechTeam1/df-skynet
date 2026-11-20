from enum import StrEnum, auto


class QueueStatuses(StrEnum):
    queued = auto()
    processing = auto()
    success = auto()
    failed = auto()
