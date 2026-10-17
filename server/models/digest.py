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

    # Claims / Mệnh đề & Sự thật bóc tách từ tin nhắn
    claims: List[Dict[str, Any]] = Field(default_factory=list, description="Danh sách Claims/Facts đã bóc tách và xác thực trong ngày")

    # Metadata & Đồng bộ WeKnora
    message_count: int = Field(default=0, description="Tổng số tin nhắn staging đã tổng hợp")
    weknora_doc_id: Optional[str] = Field(default=None, description="ID tài liệu trên WeKnora")
    weknora_kb_id: Optional[str] = Field(default=None, description="KB ID của WeKnora chứa doc này")
    sync_status: str = Field(default="pending", description="pending / synced / failed")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_weknora_markdown(self) -> str:
        """Render thành văn bản Markdown chuẩn Entity-Centric để nạp vào WeKnora Wiki Knowledge Base."""
        project_name = self.project_tag or "Nội bộ"
        group_display = self.chat_name or f"Nhóm {self.chat_id}"

        lines = [
            f"# WIKI KNOWLEDGE BASE: [[DỰ ÁN {project_name.upper()}]]",
            f"**Nhóm trao đổi (Chat Group):** [[{group_display}]] (ID: `{self.chat_id}`)",
            f"**Dự án trực thuộc (Parent Project):** [[{project_name}]]",
            f"**Ngày ghi nhận:** `{self.date}` | **Tin nhắn tổng hợp:** {self.message_count} | **Số lượng Claims:** {len(self.claims)}",
            "",
            "## 1. TỔNG QUAN DIỄN BIẾN (EXECUTIVE OVERVIEW)",
            self.overview_summary or "Ghi nhận các trao đổi về quyết định, cam kết tiến độ và cập nhật trạng thái trong ngày.",
            "",
            "---",
            "## 2. THỰC THỂ & MỆNH ĐỀ CẬP NHẬT (ENTITIES & CLAIMS)",
        ]

        # Nhóm claims theo Entity
        if not self.claims:
            lines.append("*(Không có claims bổ sung nào trong ngày)*")
        else:
            # Gom claims theo entity_id
            claims_by_entity: Dict[str, List[Dict[str, Any]]] = {}
            for cl in self.claims:
                eid = cl.get("entity_id") or project_name
                claims_by_entity.setdefault(eid, []).append(cl)

            for eid, cl_list in claims_by_entity.items():
                lines.append(f"\n### 📌 Thực thể: [[{eid}]]")
                lines.append(f"- **Thuộc nhóm chat:** [[{group_display}]] | **Dự án:** [[{project_name}]]")
                for c in cl_list:
                    status = (c.get("status") or "current").upper()
                    prop = c.get("property") or "info"
                    val = c.get("value") or ""
                    asserted = c.get("asserted_by") or {}
                    speaker = asserted.get("user_name") or asserted.get("user_id") or "Thành viên"
                    role = asserted.get("role") or "member"
                    src = c.get("source") or ""
                    lines.append(f"  • `[{status}]` **{prop}**: {val}")
                    lines.append(f"    - *Khẳng định bởi:* {speaker} ({role})")
                    if src:
                        lines.append(f"    - *Bằng chứng:* > *\"{src}\"*")

        lines.extend([
            "",
            "---",
            "## 3. CÁC QUYẾT ĐỊNH ĐÃ THỐNG NHẤT (DECISIONS)",
        ])

        if not self.decisions:
            lines.append("*Không có quyết định mới nào được chốt trong ngày.*")
        else:
            for i, d in enumerate(self.decisions, 1):
                lines.append(f"### 3.{i}. {d.title}")
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
            "## 4. MA TRẬN CAM KẾT & HẠN CHÓT (COMMITMENT MATRIX)",
        ])
        if not self.commitments:
            lines.append("*Không có cam kết nào phát sinh trong ngày.*")
        else:
            lines.append("| Người cam kết | Nhiệm vụ | Hạn chót (Deadline) | Cam kết với | Nguồn tin |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for c in self.commitments:
                deadline = c.deadline or "Chưa rõ"
                recipient = c.recipient_name or "Nhóm"
                link_str = f"[{c.source.speaker_name}]({c.source.message_link})"
                lines.append(f"| **{c.promiser_name}** | {c.task} | `{deadline}` | {recipient} | {link_str} |")
            lines.append("")

        lines.extend([
            "---",
            "## 5. THAY ĐỔI TRẠNG THÁI & BLOCKERS (STATUS & BLOCKERS)",
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
                lines.append(f"### 5.{i}. [{tag}] {s.target_object}: {s.summary}")
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


# ==============================================================================
# BẢN GHI MASTER DAILY DIGEST (CẤP ĐIỀU HÀNH TOÀN CÔNG TY)
# ==============================================================================

class MasterDailyDigestRecord(BaseModel):
    """
    Bản ghi Tổng hợp Ngày Cấp Điều Hành (Master Executive Daily Digest):
      - Gom toàn bộ group digests trong ngày thành 1 báo cáo duy nhất gửi DM cho Chủ nhân.
      - Phần 1: TỔNG QUAN ĐIỀU HÀNH (High-level Executive Summary).
      - Phần 2: CHI TIẾT TỪNG NHÓM / DỰ ÁN (Mỗi nhóm có: Quyết định, Cam kết & Hạn chót, Thay đổi trạng thái/Blocker).
      - Lưu trong collection 'master_daily_digests' trên MongoDB.
      - Khi Chủ nhân duyệt: Tự động phân tách và nạp từng group digest vào đúng KB WeKnora của nhóm tương ứng.
    """
    id: str = Field(..., description="Mã master digest: master_digest_YYYYMMDD")
    date: str = Field(..., description="Ngày ghi nhận: YYYY-MM-DD")
    executive_summary: str = Field(default="", description="Bức tranh toàn cảnh cấp điều hành về tất cả các dự án trong ngày")
    group_digests: List[DailyDigestRecord] = Field(default_factory=list, description="Danh sách digest chi tiết của từng nhóm chat")
    total_messages: int = Field(default=0, description="Tổng số tin nhắn staging đã xử lý trên toàn bộ các nhóm")
    total_groups: int = Field(default=0, description="Số lượng nhóm chat có hoạt động trong ngày")
    status: str = Field(default="pending_approval", description="pending_approval / approved / rejected / synced")
    approved_by: Optional[str] = Field(default=None, description="Lark open_id của chủ nhân khi duyệt")
    approved_at: Optional[str] = Field(default=None, description="Thời điểm duyệt")
    created_at: str = Field(default_factory=get_vietnam_now_iso)
    updated_at: str = Field(default_factory=get_vietnam_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_executive_dm_text(self) -> str:
        """
        Render tin nhắn DM gửi cho Chủ nhân theo định dạng trực quan, phân cấp:
        - Header ngày & số nhóm
        - Bức tranh toàn cảnh (Executive Summary)
        - Chi tiết từng nhóm: Quyết định, Cam kết & Hạn chót, Trạng thái & Blocker
        - Lời nhắc lệnh duyệt/hủy
        """
        lines = [
            f"📊 **BÁO CÁO TỔNG HỢP TOÀN BỘ CÁC NHÓM (DAILY MASTER DIGEST)**",
            f"📅 **Ngày:** {self.date} | 👥 **Số nhóm hoạt động:** {self.total_groups} | 💬 **Tổng tin nhắn:** {self.total_messages}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "🏢 **I. TỔNG QUAN ĐIỀU HÀNH (EXECUTIVE OVERVIEW)**",
            self.executive_summary or "Hôm nay ghi nhận hoạt động trao đổi và cập nhật tiến độ trên các nhóm dự án.",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📂 **II. CHI TIẾT TỪNG NHÓM DỰ ÁN**",
        ]

        if not self.group_digests:
            lines.append("*(Không có nhóm nào phát sinh dữ liệu trao đổi quan trọng trong ngày)*")
        else:
            for idx, gd in enumerate(self.group_digests, 1):
                grp_title = gd.chat_name or gd.project_tag or gd.chat_id
                proj_title = gd.project_tag or "Nội bộ"
                lines.extend([
                    f"\n### 📌 Nhóm {idx}: [[{grp_title}]] (ID: `{gd.chat_id}`)",
                    f"🏢 *Dự án trực thuộc:* [[{proj_title}]] | 💬 *Tin nhắn:* {gd.message_count} | 🧠 *Claims:* {len(gd.claims)}",
                ])
                if gd.overview_summary:
                    lines.append(f"📝 *Tóm tắt:* {gd.overview_summary}")

                # 0. Mệnh đề / Đề xuất từ thành viên (Claims)
                proposed_claims = [c for c in gd.claims if (c.get("status") or "").lower() == "proposed"]
                if proposed_claims:
                    lines.append("\n  💡 **Đề xuất từ thành viên (Proposed Claims):**")
                    for p in proposed_claims[:3]:
                        prop = p.get("property") or "idea"
                        val = p.get("value") or ""
                        asserted = p.get("asserted_by") or {}
                        spk = asserted.get("user_name") or asserted.get("user_id") or "Thành viên"
                        lines.append(f"    • {spk} đề xuất: **{prop}** = {val}")

                # 1. Quyết định
                if gd.decisions:
                    lines.append("\n  🔹 **Quyết định đã thống nhất:**")
                    for d in gd.decisions:
                        lines.append(f"    • **{d.title}**: {d.content} *(Chốt bởi {d.source.speaker_name})*")
                else:
                    lines.append("  🔹 **Quyết định:** *(Không có)*")

                # 2. Cam kết & Hạn chót
                if gd.commitments:
                    lines.append("  ⏰ **Cam kết & Hạn chót:**")
                    for c in gd.commitments:
                        deadline_str = f" [Hạn: {c.deadline}]" if c.deadline else ""
                        lines.append(f"    • **{c.promiser_name}**: {c.task}{deadline_str}")
                else:
                    lines.append("  ⏰ **Cam kết:** *(Không có)*")

                # 3. Thay đổi trạng thái & Blocker
                if gd.status_changes:
                    lines.append("  🔄 **Trạng thái & Tiến độ:**")
                    for s in gd.status_changes:
                        prefix = (
                            "🔴 [BLOCKER]"
                            if s.category == StatusCategory.BLOCKER
                            else ("🟢 [MILESTONE]" if s.category == StatusCategory.MILESTONE else "🔵 [TIẾN ĐỘ]")
                        )
                        reason = f" - *Lý do:* {s.blocker_reason}" if s.blocker_reason else ""
                        lines.append(f"    • {prefix} **{s.target_object}**: {s.new_state} ({s.summary}){reason}")
                else:
                    lines.append("  🔄 **Trạng thái:** *(Không có thay đổi đặc biệt)*")

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "💡 **HƯỚNG DẪN THAO TÁC:**",
            "👉 Nhắn tin **\"duyệt digest\"** để phê duyệt và đồng bộ tri thức của từng nhóm vào đúng Knowledge Base WeKnora tương ứng.",
            "👉 Nhắn tin **\"hủy digest\"** nếu không muốn lưu trữ bản tổng hợp này.",
        ])

        return "\n".join(lines)
