"""
HiLark - Daily Digest & Staging Models
=======================================
Vị trí: server/models/digest.py

Chứa các cấu trúc dữ liệu phục vụ:
  - Vùng đệm tin nhắn trong ngày (Staging Message)
  - Trích xuất 3 nhánh tri thức: Quyết định, Cam kết (hứa hẹn/deadline), Thay đổi trạng thái (tiến độ/mốc/blocker)
  - Thông tin truy vết bắt buộc: Link tin gốc (Lark deep link), người nói, thời điểm
  - Bản ghi tổng hợp Daily Digest xuất sang WeKnora Markdown
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from models.memory import get_vietnam_now_iso


class StatusCategory(str, Enum):
    """Phân loại thay đổi trạng thái."""
    PROGRESS = "progress"     # Cập nhật tiến độ (VD: Đã làm xong 80%)
    MILESTONE = "milestone"   # Đạt hoặc dời mốc quan trọng (VD: Hoàn thành Sprint 1)
    BLOCKER = "blocker"       # Điểm nghẽn / Rủi ro phát sinh (VD: Bị nghẽn do chờ API đối tác)


class SourceReference(BaseModel):
    """
    Thông tin truy vết bắt buộc gắn liền với từng mục trích xuất:
      - Link tin gốc (Lark deep link)
      - Người nói (Tên + ID)
      - Thời điểm phát ngôn
      - Trích dẫn câu nói gốc
    """
    message_id: str = Field(..., description="ID tin nhắn gốc trên Lark (om_xxx)")
    message_link: str = Field(..., description="Deep link mở thẳng tin nhắn trên client Lark")
    speaker_name: str = Field(..., description="Tên người nói (VD: Nam Lê)")
    speaker_id: str = Field(default="", description="Lark open_id của người nói (ou_xxx)")
    timestamp: str = Field(..., description="Thời điểm phát ngôn (HH:mm DD/MM/YYYY hoặc ISO)")
    quote: str = Field(default="", description="Trích đoạn câu nói gốc chứa ngữ cảnh")

    @classmethod
    def create(
        cls,
        message_id: str,
        speaker_name: str,
        speaker_id: str = "",
        timestamp: str = "",
        quote: str = "",
    ) -> SourceReference:
        """Tự động sinh link applink của Lark từ message_id."""
        link = f"https://applink.larksuite.com/client/message/open?open_message_id={message_id}"
        return cls(
            message_id=message_id,
            message_link=link,
            speaker_name=speaker_name,
            speaker_id=speaker_id,
            timestamp=timestamp or get_vietnam_now_iso(),
            quote=quote,
        )


class StagingMessage(BaseModel):
    """Bản ghi tin nhắn thô lọt qua filter, lưu tạm vào MongoDB staging trong ngày."""
    id: str = Field(..., description="Staging ID duy nhất")
    message_id: str = Field(..., description="ID tin nhắn Lark gốc")
    chat_id: str = Field(..., description="ID nhóm/cuộc trò chuyện Lark (oc_xxx)")
    chat_name: str = Field(default="", description="Tên nhóm chat")
    speaker_name: str = Field(default="", description="Tên người gửi")
    speaker_id: str = Field(default="", description="Lark open_id người gửi")
    text: str = Field(..., description="Nội dung tin nhắn")
    timestamp: str = Field(default_factory=get_vietnam_now_iso, description="Thời điểm gửi")
    message_link: str = Field(default="", description="Deep link mở tin nhắn trên Lark")
    project_tag: Optional[str] = Field(default=None, description="Tag dự án liên quan (nếu có)")
    processed: bool = Field(default=False, description="Đã tổng hợp vào digest chưa")
    created_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ==============================================================================
# 3 LOẠI THÔNG TIN BẮT BUỘC TRÍCH XUẤT
# ==============================================================================

class DecisionItem(BaseModel):
    """LOẠI 1: QUYẾT ĐỊNH (Đã chốt phương án / quy định gì)."""
    id: str = Field(..., description="Mã quyết định (VD: dec_01)")
    title: str = Field(..., description="Tóm tắt ngắn gọn quyết định")
    content: str = Field(..., description="Nội dung chi tiết quyết định đã được chốt")
    scope: Optional[str] = Field(default=None, description="Phạm vi áp dụng (VD: Module Payment, Toàn team)")
    source: SourceReference = Field(..., description="Nguồn tin gốc")


class CommitmentItem(BaseModel):
    """LOẠI 2: CAM KẾT (Ai hứa làm gì, hạn chót khi nào)."""
    id: str = Field(..., description="Mã cam kết (VD: cmt_01)")
    promiser_name: str = Field(..., description="Ai hứa (Họ tên người cam kết thực hiện)")
    promiser_id: Optional[str] = Field(default=None, description="Lark open_id của người hứa")
    task: str = Field(..., description="Nội dung công việc / kết quả cam kết bàn giao")
    deadline: str = Field(..., description="Hạn chót hoàn thành (VD: 17:00 ngày 15/10/2026, Thứ 6 tuần này)")
    recipient_name: Optional[str] = Field(default=None, description="Hứa với ai (VD: PM, Team, Khách hàng)")
    is_completed: bool = Field(default=False, description="Trạng thái đã hoàn thành hay chưa")
    source: SourceReference = Field(..., description="Nguồn tin gốc")


class StatusChangeItem(BaseModel):
    """LOẠI 3: THAY ĐỔI TRẠNG THÁI (Tiến độ, mốc thời gian, blocker)."""
    id: str = Field(..., description="Mã trạng thái (VD: stc_01)")
    category: StatusCategory = Field(..., description="progress | milestone | blocker")
    target_object: str = Field(..., description="Đối tượng/Tính năng/Module (VD: Cổng thanh toán VietQR)")
    summary: str = Field(..., description="Nội dung cập nhật trạng thái")
    previous_state: Optional[str] = Field(default=None, description="Trạng thái cũ nếu có")
    new_state: str = Field(..., description="Trạng thái mới")
    blocker_reason: Optional[str] = Field(default=None, description="Lý do nghẽn / Cần ai hỗ trợ (nếu là blocker)")
    source: SourceReference = Field(..., description="Nguồn tin gốc")


# ==============================================================================
# BẢN GHI DAILY DIGEST TỔNG THỂ
# ==============================================================================

class DailyDigestRecord(BaseModel):
    """
    Tài liệu tổng hợp ngày:
      - Lưu trữ đầy đủ trong MongoDB (Query API, lịch sử, dashboard)
      - Render thành Markdown chất lượng cao đẩy vào WeKnora làm tri thức RAG
    """
    id: str = Field(..., description="Mã bản ghi: digest_YYYYMMDD_chatId")
    date: str = Field(..., description="Ngày ghi nhận: YYYY-MM-DD")
    chat_id: str = Field(..., description="ID cuộc trò chuyện Lark (oc_xxx)")
    chat_name: str = Field(default="", description="Tên nhóm chat")
    project_tag: Optional[str] = Field(default=None, description="Mã dự án (nếu có)")
    overview_summary: str = Field(default="", description="Tóm tắt 1-2 câu tổng quan ngày")

    # 3 danh mục bắt buộc
    decisions: List[DecisionItem] = Field(default_factory=list)
    commitments: List[CommitmentItem] = Field(default_factory=list)
    status_changes: List[StatusChangeItem] = Field(default_factory=list)

    # Metadata & Đồng bộ WeKnora
    message_count: int = Field(default=0, description="Tổng số tin nhắn staging đã tổng hợp")
    weknora_doc_id: Optional[str] = Field(default=None, description="ID tài liệu trên WeKnora")
    weknora_kb_id: Optional[str] = Field(default=None, description="KB ID của WeKnora chứa doc này")
    sync_status: str = Field(default="pending", description="pending / synced / failed")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_weknora_markdown(self) -> str:
        """Render thành văn bản Markdown chuẩn để nạp vào WeKnora."""
        title_name = self.chat_name.upper() if self.chat_name else "LARK CHAT"
        lines = [
            f"# NHẬT KÝ TRAO ĐỔI LẬP TRÌNH & DỰ ÁN: {title_name}",
            f"**Ngày ghi nhận:** {self.date} | **Dự án:** {self.project_tag or 'Nội bộ'}",
            f"**Số lượng tin nhắn tổng hợp:** {self.message_count}",
            "",
            "## 1. TỔNG QUAN HÔM NAY",
            self.overview_summary or "Hôm nay ghi nhận các trao đổi về quyết định, cam kết tiến độ và cập nhật trạng thái dự án.",
            "",
            "---",
            "## 2. CÁC QUYẾT ĐỊNH ĐÃ THỐNG NHẤT (DECISIONS)",
        ]

        if not self.decisions:
            lines.append("*Không có quyết định mới nào được chốt trong ngày.*")
        else:
            for i, d in enumerate(self.decisions, 1):
                lines.append(f"### 2.{i}. {d.title}")
                lines.append(f"- **Nội dung:** {d.content}")
                if d.scope:
                    lines.append(f"- **Phạm vi áp dụng:** {d.scope}")
                lines.append(
                    f"- **Truy vết:** Chốt bởi **{d.source.speaker_name}** lúc `{d.source.timestamp}` | "
                    f"[📎 Xem tin nhắn gốc]({d.source.message_link})"
                )
                if d.source.quote:
                    lines.append(f"  > *\"{d.source.quote}\"*")
                lines.append("")

        lines.extend([
            "---",
            "## 3. CAM KẾT VÀ HẠN CHÓT (COMMITMENTS & PROMISES)",
        ])
        if not self.commitments:
            lines.append("*Không có cam kết nào phát sinh trong ngày.*")
        else:
            for i, c in enumerate(self.commitments, 1):
                lines.append(f"### 3.{i}. {c.promiser_name} cam kết: {c.task}")
                lines.append(f"- **Hạn chót (Deadline):** `{c.deadline}`")
                if c.recipient_name:
                    lines.append(f"- **Cam kết với:** {c.recipient_name}")
                lines.append(
                    f"- **Truy vết:** **{c.source.speaker_name}** phát ngôn lúc `{c.source.timestamp}` | "
                    f"[📎 Xem tin nhắn gốc]({c.source.message_link})"
                )
                if c.source.quote:
                    lines.append(f"  > *\"{c.source.quote}\"*")
                lines.append("")

        lines.extend([
            "---",
            "## 4. THAY ĐỔI TRẠNG THÁI (TIẾN ĐỘ, MỐC, BLOCKER)",
        ])
        if not self.status_changes:
            lines.append("*Không có cập nhật trạng thái nào trong ngày.*")
        else:
            for i, s in enumerate(self.status_changes, 1):
                tag = (
                    "🔴 BLOCKER"
                    if s.category == StatusCategory.BLOCKER
                    else ("🟢 MILESTONE" if s.category == StatusCategory.MILESTONE else "🔵 TIẾN ĐỘ")
                )
                lines.append(f"### 4.{i}. [{tag}] {s.target_object}: {s.summary}")
                lines.append(f"- **Trạng thái:** {s.previous_state or 'Ban đầu'} ➔ **{s.new_state}**")
                if s.blocker_reason:
                    lines.append(f"- **Vướng mắc / Cần hỗ trợ:** {s.blocker_reason}")
                lines.append(
                    f"- **Truy vết:** Báo cáo bởi: **{s.source.speaker_name}** lúc `{s.source.timestamp}` | "
                    f"[📎 Xem tin nhắn gốc]({s.source.message_link})"
                )
                if s.source.quote:
                    lines.append(f"  > *\"{s.source.quote}\"*")
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
