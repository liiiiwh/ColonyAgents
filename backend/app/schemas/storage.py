"""对象存储 Pydantic schemas。"""

from __future__ import annotations

from pydantic import BaseModel


class StorageObject(BaseModel):
    key: str
    size: int
    last_modified: str


class UploadResponse(BaseModel):
    key: str
    size: int
    content_type: str


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int
