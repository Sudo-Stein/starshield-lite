"""Object index schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ObjectRecordOut(BaseModel):
    norad: int
    name: str
    groups: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    epoch: Optional[str] = None
    primary_group: str = ""


class ObjectSearchResponse(BaseModel):
    query: str
    count: int
    results: List[ObjectRecordOut]
