"""Closed values for stewardship files and their durable outcomes."""

from enum import StrEnum

from etl_craft.core.enums import RunStatus


class UploadStatus(StrEnum):
    """Durable disposition of one stewardship file."""

    QUEUED = RunStatus.QUEUED
    REFUSED = "REFUSED"
    LOADED = "LOADED"
    FAILED = RunStatus.FAILED


class UploadFormat(StrEnum):
    """The three formats accepted by stewardship validation."""

    CSV = "CSV"
    TXT = "TXT"
    XLSX = "XLSX"


class MultipartState(StrEnum):
    """Bounded input decoder phases."""

    INITIAL = "initial"
    HEADERS = "headers"
    BODY = "body"
    END = "end"


class SeedStatus(StrEnum):
    """The recorded outcome of applying one bundle seed table."""

    UNCHANGED = "UNCHANGED"
    LOADED = "LOADED"
    LOCKED = "LOCKED"
    FAILED = RunStatus.FAILED
