from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class EntityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MERGED = "merged"


class ClaimStatus(str, Enum):
    CURRENT = "current"        # Thông tin hiện tại còn hiệu lực
    SUPERSEDED = "superseded"  # Đã bị thay thế bởi claim mới hơn
    CONFLICTED = "conflicted"  # Có mâu thuẫn trực tiếp giữa các nguồn
    UNCERTAIN = "uncertain"    # Mơ hồ, chưa chốt, phỏng đoán (hình như, có thể...)


class MemoryEntity(BaseModel):
    """
    Schema đại diện cho một thực thể (Memory Node) trong bộ nhớ.
    
    Ý nghĩa các trường:
      - _id: ID ổn định do Python tạo (deterministic theo workspace + canonical_name)
      - workspace_id: Phạm vi thực thể, tránh nhầm giữa các workspace
      - canonical_name: Tên chuẩn của thực thể
      - entity_type: person, project, team, customer, document, ...
      - aliases: Những tên gọi khác đã có bằng chứng rõ ràng
      - description: Tóm tắt ngữ cảnh để nhận diện
      - attributes: Thông tin bổ sung có cấu trúc linh hoạt
      - status: active, inactive, merged
      - source_message_ids: Danh sách ID tin nhắn làm căn cứ tạo/cập nhật entity
    """
    id: str = Field(..., alias="_id", description="ID ổn định do Python tạo")
    workspace_id: str = Field(default="default", description="Phạm vi thực thể, tránh nhầm giữa các workspace")
    canonical_name: str = Field(..., description="Tên chuẩn của thực thể")
    entity_type: str = Field(..., description="person, project, team, customer, document...")
    aliases: List[str] = Field(default_factory=list, description="Những tên gọi khác đã có bằng chứng")
    description: str = Field(default="", description="Tóm tắt ngữ cảnh để nhận diện")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Thông tin bổ sung có cấu trúc linh hoạt")
    status: EntityStatus = Field(default=EntityStatus.ACTIVE, description="active, inactive, merged")
    source_message_ids: List[str] = Field(default_factory=list, description="Tin nhắn làm căn cứ tạo/cập nhật entity")

    model_config = {
        "populate_by_name": True,
        "use_enum_values": True,
    }

    def to_dict(self) -> Dict[str, Any]:
        """Xuất ra dict đúng chuẩn với key '_id'."""
        return self.model_dump(by_alias=True)


class Claim(BaseModel):
    """
    Schema đại diện cho một mệnh đề thông tin (Claim).
    
    Mục tiêu: Trả lời:
      "Thông tin gì đã được nói, áp dụng cho entity nào, còn hiệu lực không và lấy từ đâu?"
      
    Ý nghĩa các trường:
      - _id: ID của claim (vd: clm_001, clm_xxxx)
      - entity_id: Liên kết đến entity chuẩn (_id trong MemoryEntity)
      - predicate: Thuộc tính/sự kiện, ví dụ deadline, owner, budget, role...
      - value: Giá trị có cấu trúc linh hoạt (string, int, float, dict, list...)
      - status: current, superseded, conflicted, uncertain
      - confidence: Độ tin cậy do hệ thống đánh giá (0.0 đến 1.0)
      - source: Nguồn để kiểm chứng claim (text snippet, message_id, sender...)
      - supersedes: ID claim cũ mà claim mới thay thế (hoặc None)
      - created_at: Thời điểm hệ thống ghi nhận (ISO-8601)
      - updated_at: Thời điểm document được cập nhật (ISO-8601)
    """
    id: str = Field(..., alias="_id", description="ID của claim (vd: clm_001)")
    entity_id: str = Field(..., description="Liên kết đến entity chuẩn")
    predicate: str = Field(..., description="Thuộc tính/sự kiện, ví dụ deadline, owner, budget")
    value: Any = Field(..., description="Giá trị có cấu trúc linh hoạt")
    status: ClaimStatus = Field(default=ClaimStatus.CURRENT, description="current, superseded, conflicted, uncertain")
    confidence: Optional[float] = Field(default=None, description="Độ tin cậy nếu có")
    source: Union[str, Dict[str, Any]] = Field(default="", description="Nguồn để kiểm chứng claim")
    supersedes: Optional[str] = Field(default=None, description="ID claim cũ mà claim mới thay thế")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Thời điểm hệ thống ghi nhận"
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Thời điểm document được cập nhật"
    )

    model_config = {
        "populate_by_name": True,
        "use_enum_values": True,
    }

    def to_dict(self) -> Dict[str, Any]:
        """Xuất ra dict đúng chuẩn với key '_id'."""
        return self.model_dump(by_alias=True)
