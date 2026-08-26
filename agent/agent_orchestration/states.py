from enum import Enum


class TaskStatus(Enum):
    CREATED = "created"
    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"
    COMPLETED = "completed"
    FAILED = "failed"
