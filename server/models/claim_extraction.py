from pydantic import BaseModel
import os
import re
import json
import uuid
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Optional, List, Union, Dict, Tuple
import httpx
from pydantic import BaseModel, Field

class Claim(BaseModel):
    """
    Schema đại diện cho một Claim tương ứng với bảng trong PostgreSQL:
    Field               Kiểu PostgreSQL     Ý nghĩa
    id                  UUID                ID của Claim
    entity              TEXT                Đối tượng, ví dụ project_atlas
    predicate           TEXT                Thuộc tính, ví dụ deadline
    value               JSONB               Giá trị của Claim
    source_message_id   TEXT                Tin nhắn Lark tạo ra Claim
    status              TEXT                Trạng thái Claim
    superseded_by       UUID, nullable      Claim mới thay thế Claim này
    created_at          TIMESTAMPTZ         Thời điểm tạo Claim
    """
    id: UUID = Field(default_factory=uuid4, description="ID của Claim (UUID)")
    entity: str = Field(..., description="Đối tượng, ví dụ project_atlas")
    predicate: str = Field(..., description="Thuộc tính, ví dụ deadline")
    value: Any = Field(..., description="Giá trị của Claim (JSONB compatible)")
    source_message_id: Optional[str] = Field(default=None, description="Tin nhắn Lark tạo ra Claim")
    status: str = Field(default="active", description="Trạng thái Claim")
    superseded_by: Optional[UUID] = Field(default=None, description="Claim mới thay thế Claim này")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Thời điểm tạo Claim (TIMESTAMPTZ)"
    )