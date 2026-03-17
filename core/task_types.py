"""Canonical task type taxonomy for memory tagging.

NOTE: dashboard/server.py has a separate TaskType enum for UI task creation.
This enum is for memory layer tagging. They coexist independently.
"""

from enum import Enum


class TaskType(Enum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    CONTENT = "content"
    STRATEGY = "strategy"
    APP_CREATE = "app_create"
    MARKETING = "marketing"
    GENERAL = "general"
