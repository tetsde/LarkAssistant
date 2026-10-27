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
from typing import Any, Dict, List, Optional


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
        cname = _clean_group_name(getattr(gd, "chat_name", None) or getattr(gd, "chat_id", "Nhóm"))
        for sc in getattr(gd, "status_changes", []) or []:
            cat = str(getattr(sc, "category", "")).lower()
            if "blocker" in cat:
                summary = getattr(sc, "summary", "")
                reason = getattr(sc, "blocker_reason", "")
                r_text = f" (Lý do: {reason})" if reason else ""
                blockers.append(f"[{cname}] {summary}{r_text}")

        for d in getattr(gd, "decisions", []) or []:
            d_title = getattr(d, "title", "")
            d_content = getattr(d, "content", "")
            decisions.append(f"[{cname}] {d_title}: {d_content}")

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

    # Bảng thông tin đề xuất (Claims/Facts) trong ngày
    if actual_pending_claims:
        table_lines = [
            "| Dự án / Thực thể | Thuộc tính | Giá trị đề xuất | Người gửi |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for c in actual_pending_claims[:8]:
            ent = str(c.get("entity_id") or c.get("project_id") or "Chung").replace("|", "/").strip()
            raw_p = str(c.get("property") or c.get("predicate") or "thông tin").strip()
            prop = PROPERTY_LABELS.get(raw_p.lower(), raw_p).replace("|", "/")
            val = str(c.get("value") or "").replace("|", "/").strip()
            speaker = str(c.get("speaker_name") or "Thành viên").replace("|", "/").strip()
            table_lines.append(f"| {ent} | {prop} | {val} | {speaker} |")

        if len(actual_pending_claims) > 8:
            table_lines.append(f"\n*... và còn {len(actual_pending_claims) - 8} thông tin khác.*")

        elements.extend([
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Thông tin đề xuất mới trong ngày ({len(actual_pending_claims)} mục):**\n" + "\n".join(table_lines),
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
    digest_id = getattr(master_digest, "id", "") or "latest"
    date_str = getattr(master_digest, "date", "") or "Hôm nay"
    group_digests = getattr(master_digest, "group_digests", []) or []

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
            cname = _clean_group_name(getattr(gd, "chat_name", None) or getattr(gd, "chat_id", "Nhóm"))
            msg_count = getattr(gd, "message_count", 0)
            summary = getattr(gd, "summary", "") or "Không có tóm tắt riêng."

            group_lines = [
                f"**{idx + 1}. Nhóm: {cname}** ({msg_count} tin nhắn)",
                f"> {summary.strip()}",
            ]

            # Quyết định
            decisions = getattr(gd, "decisions", []) or []
            if decisions:
                d_items = []
                for d in decisions[:2]:
                    t = getattr(d, "title", "")
                    c = getattr(d, "content", "")
                    d_items.append(f"- Quyết định: {t} - {c}" if t else f"- Quyết định: {c}")
                group_lines.append("\n".join(d_items))

            # Điểm nghẽn
            status_changes = getattr(gd, "status_changes", []) or []
            blockers = [
                getattr(sc, "summary", "")
                for sc in status_changes
                if "blocker" in str(getattr(sc, "category", "")).lower()
            ]
            if blockers:
                b_items = [f"- Điểm nghẽn: {b}" for b in blockers[:2]]
                group_lines.append("\n".join(b_items))

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

