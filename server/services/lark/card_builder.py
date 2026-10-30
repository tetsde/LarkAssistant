"""
HiLark Lark Card Builder
========================
Vị trí: server/services/lark/card_builder.py

Mục đích:
    Xây dựng cấu trúc dữ liệu Thẻ tin nhắn tương tác (Interactive Card) chuẩn của Lark:
      1. build_draft_card        - Thẻ phê duyệt bản nháp câu trả lời
      2. build_claim_card        - Thẻ phê duyệt thông tin đề xuất mới (Claims / Facts)
      3. build_digest_card       - Thẻ phê duyệt báo cáo ngày cấp điều hành (Master Daily Digest)
      4. build_updated_status_card - Thẻ cập nhật trạng thái sau khi đã xử lý (In-place update)

Quy tắc trình bày:
    - Thuần tiếng Việt, rõ ràng, gãy gọn, thân thiện và gần gũi.
    - Hạn chế tối đa từ ngữ sáo rỗng hoặc thuật ngữ không cần thiết.
    - Tuyệt đối không sử dụng biểu tượng cảm xúc (icon/emoji).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.memory import VIETNAM_TZ


def _format_time_badge(ts_str: Optional[str]) -> str:
    """
    Định dạng hiển thị mốc thời gian dạng ' (lúc HH:MM)'.
    Nếu không có giờ hợp lệ, trả về chuỗi rỗng ''.
    """
    if not ts_str:
        return ""
    ts_clean = str(ts_str).strip()
    try:
        if "T" in ts_clean:
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo:
                dt = dt.astimezone(VIETNAM_TZ)
            return f" (lúc {dt.strftime('%H:%M')})"
    except Exception:
        pass

    m = re.search(r"\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b", ts_clean)
    if m:
        hh = int(m.group(1))
        mm = m.group(2)
        return f" (lúc {hh:02d}:{mm})"
    return ""


def _extract_source_time(item: Any) -> str:
    """Trích xuất timestamp an toàn từ item (Pydantic model hoặc dict)."""
    if not item:
        return ""
    src = getattr(item, "source", None)
    if src is None and isinstance(item, dict):
        src = item.get("source")
    if not src:
        return ""
    ts = getattr(src, "timestamp", None)
    if ts is None and isinstance(src, dict):
        ts = src.get("timestamp")
    return str(ts or "").strip()


def _clean_group_name(raw_name: Optional[str]) -> str:
    """Làm sạch tên nhóm thảo luận, loại bỏ các tiền tố gắn nhãn trong ngoặc vuông."""
    if not raw_name:
        return "Nhóm thảo luận"
    clean = re.sub(r"^\[.*?\]\s*", "", raw_name).strip()
    return clean if clean else raw_name.strip()


# Bản đồ nhãn thuộc tính sang tiếng Việt thân thiện
PROPERTY_LABELS: Dict[str, str] = {
    "budget": "Ngân sách",
    "deadline": "Thời hạn hoàn thành",
    "lead": "Người phụ trách chính",
    "pm": "Quản lý dự án",
    "role": "Vai trò phân công",
    "scope": "Phạm vi công việc",
    "status": "Trạng thái tiến độ",
    "priority": "Mức độ ưu tiên",
    "milestone": "Cột mốc thực hiện",
    "tech_stack": "Công nghệ sử dụng",
    "blocker": "Điểm nghẽn cần tháo gỡ",
}


def build_draft_card(
    draft_id: str,
    chat_title: str,
    user_name: str,
    query: str,
    draft_answer: str,
    reason: str,
    is_confidential: bool = False,
    security_level: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt bản nháp câu trả lời.
    """
    clean_chat = _clean_group_name(chat_title)
    clean_user = user_name.strip() if user_name else "Thành viên"
    sec_label = "Bảo mật cao" if is_confidential else (security_level or "Tiêu chuẩn")
    header_template = "orange" if is_confidential else "blue"
    header_title = "Soạn nháp câu trả lời - Dự án bảo mật" if is_confidential else "Soạn nháp câu trả lời"

    elements: List[Dict[str, Any]] = [
        # Thông tin cơ bản
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Nhóm:** {clean_chat}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Mức độ:** {sec_label}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Người hỏi:** {clean_user}",
                    },
                },
            ],
        },
        {"tag": "hr"},
        # Nội dung câu hỏi
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Câu hỏi:**\n\"{query.strip()}\"",
            },
        },
        # Bản nháp câu trả lời
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Bản nháp gợi ý:**\n> {draft_answer.strip()}",
            },
        },
        # Lý do cần duyệt
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Lý do cần duyệt:** {reason.strip()}",
            },
        },
        {"tag": "hr"},
        # Hàng nút thao tác
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Duyệt và gửi",
                    },
                    "type": "primary",
                    "value": {
                        "action": "approve_draft",
                        "draft_id": draft_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Nhờ AI sửa lại",
                    },
                    "type": "default",
                    "value": {
                        "action": "ai_rewrite_draft",
                        "draft_id": draft_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Tự sửa",
                    },
                    "type": "default",
                    "value": {
                        "action": "manual_edit_draft",
                        "draft_id": draft_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Hủy bỏ",
                    },
                    "type": "danger",
                    "value": {
                        "action": "discard_draft",
                        "draft_id": draft_id,
                    },
                },
            ],
        },
        # Hướng dẫn thao tác nhanh bằng tin nhắn
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Thao tác nhanh bằng tin nhắn: Gửi / Bỏ / Sửa: <nội dung> / Sửa AI: <yêu cầu>",
                }
            ],
        },
    ]

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": header_template,
            "title": {
                "tag": "plain_text",
                "content": header_title,
            },
        },
        "elements": elements,
    }


def build_claim_approval_card(
    claim_id: str,
    chat_title: str,
    speaker_name: str,
    entity_name: str,
    property_name: str,
    value: str,
    source_text: str,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt thông tin đề xuất mới (Fact/Claim).
    """
    clean_chat = _clean_group_name(chat_title)
    clean_speaker = speaker_name.strip() if speaker_name else "Thành viên"
    clean_prop_label = PROPERTY_LABELS.get(property_name.lower(), property_name)

    elements: List[Dict[str, Any]] = [
        # Thông tin người đề xuất và nhóm
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Nhóm:** {clean_chat}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Người đề xuất:** {clean_speaker}",
                    },
                },
            ],
        },
        {"tag": "hr"},
        # Nội dung thông tin đề xuất
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Thực thể:** {entity_name}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Thuộc tính:** {clean_prop_label}",
                    },
                },
            ],
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Giá trị đề xuất:**\n> **{value.strip()}**",
            },
        },
        # Câu nói gốc
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Nội dung thảo luận gốc:**\n\"{source_text.strip()}\"",
            },
        },
        {"tag": "hr"},
        # Hàng nút thao tác
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Duyệt thông tin",
                    },
                    "type": "primary",
                    "value": {
                        "action": "approve_claim",
                        "claim_id": claim_id,
                        "message_id": message_id or "",
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Sửa giá trị",
                    },
                    "type": "default",
                    "value": {
                        "action": "edit_claim",
                        "claim_id": claim_id,
                        "message_id": message_id or "",
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Từ chối",
                    },
                    "type": "danger",
                    "value": {
                        "action": "reject_claim",
                        "claim_id": claim_id,
                        "message_id": message_id or "",
                    },
                },
            ],
        },
        # Hướng dẫn thao tác nhanh bằng tin nhắn
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Thao tác nhanh bằng tin nhắn: Duyệt fact / Bỏ fact / Sửa fact: <giá trị mới>",
                }
            ],
        },
    ]

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "turquoise",
            "title": {
                "tag": "plain_text",
                "content": "Thông tin đề xuất mới cần duyệt",
            },
        },
        "elements": elements,
    }


def build_digest_approval_card(
    master_digest: Any,
    pending_claims: Optional[List[Dict[str, Any]]] = None,
    cost_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt báo cáo ngày cấp điều hành (Master Daily Digest).
    Bao gồm tổng quan điều hành, các điểm nghẽn, quyết định mới và Bảng thông tin đề xuất trong ngày.
    """
    raw_id = getattr(master_digest, "id", "")
    digest_id = str(raw_id) if isinstance(raw_id, str) and raw_id else "latest"
    raw_date = getattr(master_digest, "date", "")
    date_str = str(raw_date) if isinstance(raw_date, str) and raw_date else "Hôm nay"
    raw_groups = getattr(master_digest, "total_groups", 0)
    total_groups = raw_groups if isinstance(raw_groups, int) else 0
    raw_msgs = getattr(master_digest, "total_messages", 0)
    total_messages = raw_msgs if isinstance(raw_msgs, int) else 0
    raw_summary = getattr(master_digest, "executive_summary", "")
    executive_summary = (
        str(raw_summary) if isinstance(raw_summary, str) and raw_summary
        else "Ghi nhận các hoạt động trao đổi và cập nhật tiến độ công việc trong ngày."
    )

    raw_gd = getattr(master_digest, "group_digests", [])
    group_digests = raw_gd if isinstance(raw_gd, list) else []


    # Thu thập các điểm nghẽn (Blockers) và quyết định nổi bật
    blockers: List[str] = []
    decisions: List[str] = []

    for gd in group_digests:
        cname = _clean_group_name(getattr(gd, "chat_name", None) or (gd.get("chat_name") if isinstance(gd, dict) else None) or getattr(gd, "chat_id", "Nhóm"))
        raw_sc = getattr(gd, "status_changes", []) or (gd.get("status_changes") if isinstance(gd, dict) else []) or []
        for sc in raw_sc:
            cat = str(getattr(sc, "category", None) or (sc.get("category") if isinstance(sc, dict) else "")).lower()
            if "blocker" in cat:
                summary = getattr(sc, "summary", None) or (sc.get("summary") if isinstance(sc, dict) else "")
                reason = getattr(sc, "blocker_reason", None) or (sc.get("blocker_reason") if isinstance(sc, dict) else "")
                r_text = f" (Lý do: {reason})" if reason else ""
                t_badge = _format_time_badge(_extract_source_time(sc))
                blockers.append(f"[{cname}]{t_badge} {summary}{r_text}")

        raw_dec = getattr(gd, "decisions", []) or (gd.get("decisions") if isinstance(gd, dict) else []) or []
        for d in raw_dec:
            d_title = getattr(d, "title", None) or (d.get("title") if isinstance(d, dict) else "")
            d_content = getattr(d, "content", None) or (d.get("content") if isinstance(d, dict) else "")
            t_badge = _format_time_badge(_extract_source_time(d))
            decisions.append(f"[{cname}]{t_badge} {d_title}: {d_content}")

    # Lấy pending claims nếu chưa truyền trực tiếp
    actual_pending_claims = pending_claims
    if actual_pending_claims is None:
        actual_pending_claims = getattr(master_digest, "pending_claims", None) or []

    elements: List[Dict[str, Any]] = [
        # Thông tin thống kê
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Ngày:** {date_str}",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Số nhóm:** {total_groups} nhóm",
                    },
                },
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**Tin nhắn:** {total_messages} tin",
                    },
                },
            ],
        },
        {"tag": "hr"},
        # Tóm tắt điều hành
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Tổng quan điều hành:**\n{executive_summary.strip()}",
            },
        },
    ]

    # Điểm nghẽn cần chú ý (nếu có)
    if blockers:
        blocker_text = "\n".join(f"- {b}" for b in blockers[:3])
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Điểm nghẽn cần lưu ý:**\n{blocker_text}",
            },
        })

    # Quyết định ghi nhận (nếu có)
    if decisions:
        decision_text = "\n".join(f"- {d}" for d in decisions[:3])
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Quyết định mới ghi nhận:**\n{decision_text}",
            },
        })

    # Danh sách thông tin đề xuất (Claims/Facts) trong ngày dạng phân cấp tinh gọn
    if actual_pending_claims:
        claim_lines: List[str] = []
        for c in actual_pending_claims[:8]:
            raw_ent = str(c.get("entity_name") or c.get("entity_id") or c.get("project_id") or "Dự án").strip()
            # Nếu tên vẫn dính tiền tố ent_ mã hash mà không có tên thực, dùng project_tag/chat_name hoặc Dự án
            if raw_ent.startswith("ent_"):
                raw_ent = str(c.get("project_tag") or c.get("chat_name") or "Dự án / Hạng mục").strip()

            raw_p = str(c.get("property") or c.get("predicate") or "thông tin").strip()
            prop = PROPERTY_LABELS.get(raw_p.lower(), raw_p)
            val = str(c.get("value") or "").strip()
            speaker = str(c.get("speaker_name") or "").strip()
            speaker_tag = f" *(Người gửi: {speaker})*" if speaker and speaker.lower() not in ("thành viên", "user") else ""

            claim_lines.append(f"• **[{raw_ent}]** {prop}: `{val}`{speaker_tag}")

        if len(actual_pending_claims) > 8:
            claim_lines.append(f"\n*(... và còn {len(actual_pending_claims) - 8} thông tin đề xuất khác)*")

        elements.extend([
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Thông tin đề xuất mới trong ngày ({len(actual_pending_claims)} mục):**\n" + "\n".join(claim_lines),
                },
            },
        ])
    else:
        elements.extend([
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**Thông tin đề xuất mới:** Không có thông tin đề xuất mới cần duyệt hôm nay.",
                },
            },
        ])

    # Khối thống kê chi phí và hiệu năng AI (nếu có cost_summary)
    if cost_summary:
        total_calls = cost_summary.get("total_calls", 0)
        total_tokens = cost_summary.get("total_tokens", 0)
        total_usd = cost_summary.get("total_cost_usd", 0.0)
        total_vnd = cost_summary.get("total_cost_vnd", 0.0)
        by_service = cost_summary.get("by_service", {})

        if total_calls > 0:
            gemini_info = by_service.get("gemini", {})
            jev_info = by_service.get("jev", {})

            gemini_calls = gemini_info.get("total_calls", 0)
            gemini_tokens = gemini_info.get("total_tokens", 0)
            gemini_cost_usd = gemini_info.get("total_cost_usd", 0.0)
            gemini_latency = int(gemini_info.get("avg_latency_ms", 0.0))

            jev_calls = jev_info.get("total_calls", 0)
            jev_latency = int(jev_info.get("avg_latency_ms", 0.0))

            fastlane_ratio = int((jev_calls / total_calls) * 100) if total_calls > 0 else 0

            cost_lines = [
                "**Thống kê Chi phí AI hôm nay:**",
                f"- **Tổng ngân sách:** ${total_usd:.4f} USD (~{int(total_vnd):,} VND) | **Tokens:** {total_tokens:,}",
                f"- **Gemini LLM:** {gemini_calls} lượt ({gemini_tokens:,} tokens) - ${gemini_cost_usd:.4f} - Phản hồi TB: {gemini_latency}ms",
                f"- **JEV System 1:** {jev_calls} lượt phân loại nhanh - Phản hồi TB: {jev_latency}ms",
                f"- **Tiết kiệm Fast-lane:** {fastlane_ratio}% tác vụ được lọc sơ bộ qua JEV giúp tối ưu token gọi LLM.",
            ]
            elements.extend([
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n".join(cost_lines),
                    },
                },
            ])
        else:
            elements.extend([
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**Thống kê Chi phí AI hôm nay:** Chưa ghi nhận lượt gọi AI/LLM nào phát sinh trong chu kỳ này.",
                    },
                },
            ])

    elements.extend([
        {"tag": "hr"},
        # Hàng nút thao tác
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Duyệt toàn bộ thông tin hôm nay",
                    },
                    "type": "primary",
                    "value": {
                        "action": "approve_all_digest_claims",
                        "digest_id": digest_id,
                        "date": date_str,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Xem chi tiết",
                    },
                    "type": "default",
                    "value": {
                        "action": "view_digest_detail",
                        "digest_id": digest_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Nhờ AI tóm tắt ngắn",
                    },
                    "type": "default",
                    "value": {
                        "action": "summarize_digest",
                        "digest_id": digest_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Hủy báo cáo",
                    },
                    "type": "danger",
                    "value": {
                        "action": "reject_digest",
                        "digest_id": digest_id,
                    },
                },
            ],
        },
        # Hướng dẫn nhắn nhanh
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Thao tác nhanh bằng tin nhắn: Duyệt digest / Hủy digest / Xem digest",
                }
            ],
        },
    ])

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "indigo",
            "title": {
                "tag": "plain_text",
                "content": "Báo cáo tổng hợp hoạt động trong ngày",
            },
        },
        "elements": elements,
    }


def build_project_digest_detail_card(master_digest: Any) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác xem chi tiết hoạt động từng dự án / nhóm trong ngày.
    """
    digest_id = getattr(master_digest, "id", None) or (master_digest.get("id") if isinstance(master_digest, dict) else "") or "latest"
    date_str = getattr(master_digest, "date", None) or (master_digest.get("date") if isinstance(master_digest, dict) else "") or "Hôm nay"
    group_digests = getattr(master_digest, "group_digests", None) or (master_digest.get("group_digests") if isinstance(master_digest, dict) else []) or []

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Chi tiết hoạt động các nhóm ngày {date_str}**\nTổng cộng: {len(group_digests)} nhóm thảo luận",
            },
        },
        {"tag": "hr"},
    ]

    if not group_digests:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "Không có dữ liệu chi tiết từng nhóm.",
            },
        })
    else:
        for idx, gd in enumerate(group_digests):
            cname = _clean_group_name(
                getattr(gd, "chat_name", None)
                or (gd.get("chat_name") if isinstance(gd, dict) else None)
                or getattr(gd, "chat_id", None)
                or (gd.get("chat_id") if isinstance(gd, dict) else None)
                or "Nhóm"
            )
            msg_count = getattr(gd, "message_count", None) or (gd.get("message_count") if isinstance(gd, dict) else 0) or 0
            summary = (
                getattr(gd, "summary", None)
                or (gd.get("summary") if isinstance(gd, dict) else None)
                or (getattr(gd, "overview_summary", None) if hasattr(gd, "overview_summary") else None)
                or (gd.get("overview_summary") if isinstance(gd, dict) else None)
                or "Không có tóm tắt riêng."
            )

            group_lines = [
                f"**{idx + 1}. Nhóm: {cname}** ({msg_count} tin nhắn)",
                f"> {summary.strip()}",
            ]

            # Quyết định
            decisions = getattr(gd, "decisions", []) or (gd.get("decisions") if isinstance(gd, dict) else []) or []
            if decisions:
                d_items = []
                for d in decisions[:3]:
                    t = getattr(d, "title", None) or (d.get("title") if isinstance(d, dict) else "")
                    c = getattr(d, "content", None) or (d.get("content") if isinstance(d, dict) else "")
                    t_badge = _format_time_badge(_extract_source_time(d))
                    d_items.append(f"- Quyết định{t_badge}: {t} - {c}" if t else f"- Quyết định{t_badge}: {c}")
                group_lines.append("\n".join(d_items))

            # Điểm nghẽn
            status_changes = getattr(gd, "status_changes", []) or (gd.get("status_changes") if isinstance(gd, dict) else []) or []
            blockers = [
                sc for sc in status_changes
                if "blocker" in str(getattr(sc, "category", None) or (sc.get("category") if isinstance(sc, dict) else "")).lower()
            ]
            if blockers:
                b_items = []
                for sc in blockers[:2]:
                    summary = getattr(sc, "summary", None) or (sc.get("summary") if isinstance(sc, dict) else "")
                    t_badge = _format_time_badge(_extract_source_time(sc))
                    b_items.append(f"- Điểm nghẽn{t_badge}: {summary}")
                group_lines.append("\n".join(b_items))

            # Cam kết
            commitments = getattr(gd, "commitments", []) or (gd.get("commitments") if isinstance(gd, dict) else []) or []
            if commitments:
                c_items = []
                for cmt in commitments[:2]:
                    p_name = getattr(cmt, "promiser_name", None) or (cmt.get("promiser_name") if isinstance(cmt, dict) else "") or "Thành viên"
                    task = getattr(cmt, "task", None) or (cmt.get("task") if isinstance(cmt, dict) else "")
                    dl = getattr(cmt, "deadline", None) or (cmt.get("deadline") if isinstance(cmt, dict) else "")
                    t_badge = _format_time_badge(_extract_source_time(cmt))
                    dl_text = f" (Hạn chót: {dl})" if dl else ""
                    c_items.append(f"- Cam kết{t_badge}: {p_name} - {task}{dl_text}")
                group_lines.append("\n".join(c_items))

            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "\n".join(group_lines),
                },
            })
            if idx < len(group_digests) - 1:
                elements.append({"tag": "hr"})

    elements.extend([
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Duyệt toàn bộ thông tin hôm nay",
                    },
                    "type": "primary",
                    "value": {
                        "action": "approve_all_digest_claims",
                        "digest_id": digest_id,
                        "date": date_str,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Quay lại báo cáo tổng quan",
                    },
                    "type": "default",
                    "value": {
                        "action": "view_master_digest",
                        "digest_id": digest_id,
                    },
                },
            ],
        },
    ])

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "indigo",
            "title": {
                "tag": "plain_text",
                "content": f"Chi tiết báo cáo các nhóm - {date_str}",
            },
        },
        "elements": elements,
    }


def build_updated_status_card(
    title: str,
    status_message: str,
    detail_lines: Optional[List[str]] = None,
    template: str = "grey",
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ cập nhật trạng thái tại chỗ (In-place update) sau khi lãnh đạo đã hoàn tất thao tác.
    Loại bỏ các nút bấm để tránh việc bấm lặp lại.
    """
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Trạng thái:** {status_message}",
            },
        }
    ]

    if detail_lines:
        content = "\n".join(detail_lines)
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content,
            },
        })

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": title,
            },
        },
        "elements": elements,
    }


# Các tên hàm viết tắt tương thích
build_claim_card = build_claim_approval_card
build_digest_card = build_digest_approval_card
build_draft_approval_card = build_draft_card


def build_onboarding_welcome_card(
    open_id: str,
    user_name: str = "",
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ chào mừng & Điều hướng thiết lập cá nhân hóa (Onboarding Screen Guide).
    Bao gồm nút bấm mở Webview Dialog (Popup Modal) trực tiếp trong ứng dụng Lark
    và liên kết dự phòng qua trình duyệt.
    """
    import urllib.parse
    from core.config import settings

    resolved_base = (base_url or settings.APP_BASE_URL).rstrip("/")
    display_name = user_name.strip() if user_name else "bạn"
    wizard_url = f"{resolved_base}/onboarding/wizard?open_id={open_id}&user_name={urllib.parse.quote(display_name)}"
    
    # Chuỗi mở Modal Webview tiêu chuẩn của Lark Applink
    applink_url = f"https://applink.larksuite.com/client/web_url/open?url={urllib.parse.quote(wizard_url)}&mode=window&height=660&width=560"

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**Xin chào {display_name}!**\n\n"
                    "Chào mừng bạn đến với **Trợ lý Doanh nghiệp HiLark**. "
                    "Để cá nhân hóa trải nghiệm và kích hoạt đầy đủ các tính năng thông minh, "
                    "bạn có thể thiết lập nhanh qua **Screen Guide** (4 bước ngắn gọn):"
                ),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "• **AI Engine & BYOK:** Tùy chọn sử dụng Google Gemini API Key riêng hoặc dùng chung hệ thống.\n"
                    "• **Daily Digest & HITL:** Cấu hình khung giờ nhận báo cáo tóm tắt và phê duyệt tri thức.\n"
                    "• **Lark OAuth 1-Click:** Ủy quyền truy cập tài liệu và nhóm an toàn theo quyền hạn của bạn."
                ),
            },
        },
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Mọi thông tin cá nhân và khóa API của bạn đều được mã hóa chuẩn quân đội AES-256 bảo mật tuyệt đối.",
                }
            ],
        },
        {
            "tag": "hr",
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Bắt đầu thiết lập (Screen Guide)",
                    },
                    "type": "primary",
                    "url": applink_url,
                    "multi_url": {
                        "url": applink_url,
                        "pc_url": applink_url,
                        "android_url": applink_url,
                        "ios_url": applink_url,
                    },
                    "value": {
                        "action": "open_onboarding",
                        "open_id": open_id,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Mở bằng trình duyệt",
                    },
                    "type": "default",
                    "url": wizard_url,
                    "multi_url": {
                        "url": wizard_url,
                        "pc_url": wizard_url,
                        "android_url": wizard_url,
                        "ios_url": wizard_url,
                    },
                    "value": {
                        "action": "open_onboarding_web",
                        "open_id": open_id,
                    },
                },
            ],
        },
    ]

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "indigo",
            "title": {
                "tag": "plain_text",
                "content": "Trung tâm Thiết lập & Cấu hình HiLark",
            },
        },
        "elements": elements,
    }


