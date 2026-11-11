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

from core.config import settings
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
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt bản nháp câu trả lời (có cô lập theo tenant_key).
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
        # Hàng nút thao tác chuẩn Card JSON 2.0 (thay thế tag action đã bị deprecate)
        {
            "tag": "column_set",
            "flex_mode": "none",
            "horizontal_spacing": "default",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_approve_draft",
                            "text": {
                                "tag": "plain_text",
                                "content": "Duyệt và gửi",
                            },
                            "type": "primary",
                            "value": {
                                "action": "approve_draft",
                                "draft_id": draft_id,
                                "tenant_key": tenant_key or "",
                            },
                        }
                    ],
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_manual_edit_draft",
                            "text": {
                                "tag": "plain_text",
                                "content": "Tự sửa",
                            },
                            "type": "default",
                            "value": {
                                "action": "manual_edit_draft",
                                "draft_id": draft_id,
                                "tenant_key": tenant_key or "",
                            },
                        }
                    ],
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_discard_draft",
                            "text": {
                                "tag": "plain_text",
                                "content": "Hủy bỏ",
                            },
                            "type": "danger",
                            "value": {
                                "action": "discard_draft",
                                "draft_id": draft_id,
                                "tenant_key": tenant_key or "",
                            },
                        }
                    ],
                },
            ],
        },
        # Hướng dẫn thao tác nhanh bằng tin nhắn
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "<font color='grey'>Thao tác nhanh bằng tin nhắn: Gửi / Bỏ / Sửa: &lt;nội dung&gt;</font>",
            },
        },
    ]

    return {
        "schema": "2.0",
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
        "body": {
            "elements": elements,
        },
    }


def build_draft_edit_form_card(
    draft_id: str,
    chat_title: str,
    user_name: str,
    query: str,
    draft_answer: str,
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ chỉnh sửa bản nháp câu trả lời trực tiếp (Card JSON 2.0 In-place Form).
    Điền sẵn toàn bộ nội dung bản nháp hiện tại (draft_answer) trong ô input nhiều dòng (multiline_text)
    để Lãnh đạo tiện sửa nhanh và submit gửi thẳng vào nhóm chat.
    """
    clean_chat = _clean_group_name(chat_title)
    clean_user = user_name.strip() if user_name else "Thành viên"

    elements: List[Dict[str, Any]] = [
        # Thông tin câu hỏi
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
                        "content": f"**Người hỏi:** {clean_user}",
                    },
                },
            ],
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Câu hỏi:**\n\"{query.strip()}\"",
            },
        },
        {"tag": "hr"},
        # Form chỉnh sửa Card JSON 2.0
        {
            "tag": "form",
            "name": "edit_draft_form",
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**Chỉnh sửa trực tiếp câu trả lời bên dưới:**",
                    },
                },
                {
                    "tag": "input",
                    "name": "edited_content",
                    "input_type": "multiline_text",
                    "rows": 4,
                    "auto_resize": True,
                    "max_rows": 10,
                    "default_value": draft_answer.strip(),
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "Nhập hoặc chỉnh sửa câu trả lời trước khi gửi...",
                    },
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "default",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "name": "submit_manual_edit",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "Lưu và gửi vào nhóm",
                                    },
                                    "type": "primary",
                                    "form_action_type": "submit",
                                    "value": {
                                        "action": "submit_manual_edit",
                                        "draft_id": draft_id,
                                        "tenant_key": tenant_key or "",
                                    },
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {
                                                "action": "submit_manual_edit",
                                                "draft_id": draft_id,
                                                "tenant_key": tenant_key or "",
                                            },
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "name": "cancel_manual_edit",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "Quay lại",
                                    },
                                    "type": "default",
                                    "value": {
                                        "action": "cancel_manual_edit",
                                        "draft_id": draft_id,
                                        "tenant_key": tenant_key or "",
                                    },
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": {
                                                "action": "cancel_manual_edit",
                                                "draft_id": draft_id,
                                                "tenant_key": tenant_key or "",
                                            },
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ]

    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "Chỉnh sửa câu trả lời",
            },
        },
        "body": {
            "elements": elements,
        },
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
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt thông tin đề xuất mới (Fact/Claim) có cô lập theo tenant_key.
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
                        "tenant_key": tenant_key or "",
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
                        "tenant_key": tenant_key or "",
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
                        "tenant_key": tenant_key or "",
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
    tenant_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác phê duyệt báo cáo ngày cấp điều hành (Master Daily Digest).
    Bao gồm tổng quan điều hành, các điểm nghẽn, quyết định mới và Bảng thông tin đề xuất trong ngày.
    """
    eff_tenant = tenant_key or getattr(master_digest, "tenant_key", None) or (master_digest.get("tenant_key") if isinstance(master_digest, dict) else None) or ""
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
    if isinstance(cost_summary, dict) and cost_summary:
        total_calls = int(cost_summary.get("total_calls", 0) or 0)
        total_tokens = int(cost_summary.get("total_tokens", 0) or 0)
        total_usd = float(cost_summary.get("total_cost_usd", 0.0) or 0.0)
        total_vnd = float(cost_summary.get("total_cost_vnd", 0.0) or 0.0)
        raw_by_service = cost_summary.get("by_service", {})
        by_service = raw_by_service if isinstance(raw_by_service, dict) else {}

        if total_calls > 0:
            jev_raw = by_service.get("jev", {})
            jev_info = jev_raw if isinstance(jev_raw, dict) else {}

            provider_labels = {
                "google": "Google Gemini",
                "gemini": "Google Gemini",
                "openai": "OpenAI",
                "chatgpt": "ChatGPT / OpenAI",
                "anthropic": "Anthropic Claude",
                "custom": "Custom LLM",
            }

            llm_calls = 0
            llm_tokens = 0
            llm_thinking_tokens = 0
            llm_cost_usd = 0.0
            llm_weighted_latency = 0.0
            active_provider_labels: List[str] = []

            for svc_name, svc_info in by_service.items():
                if not isinstance(svc_info, dict):
                    continue
                svc_key = str(svc_name or "").strip().lower()
                if svc_key == "jev":
                    continue

                svc_calls = int(svc_info.get("total_calls", 0) or 0)
                svc_tokens = int(svc_info.get("total_tokens", 0) or 0)
                svc_thinking = int(svc_info.get("thinking_tokens", 0) or 0)
                svc_cost_usd = float(svc_info.get("total_cost_usd", 0.0) or 0.0)
                svc_latency = float(svc_info.get("avg_latency_ms", 0.0) or 0.0)

                llm_calls += svc_calls
                llm_tokens += svc_tokens
                llm_thinking_tokens += svc_thinking
                llm_cost_usd += svc_cost_usd
                llm_weighted_latency += svc_latency * svc_calls

                if svc_calls > 0:
                    raw_label = str(svc_name or "").strip()
                    label = provider_labels.get(svc_key) or (raw_label or "Custom LLM")
                    if label not in active_provider_labels:
                        active_provider_labels.append(label)

            llm_latency = int(round(llm_weighted_latency / llm_calls)) if llm_calls > 0 else 0
            llm_label = f"LLM ({', '.join(active_provider_labels)})" if active_provider_labels else "LLM"
            thinking_part = f", thinking: {llm_thinking_tokens:,}" if llm_thinking_tokens > 0 else ""

            jev_calls = int(jev_info.get("total_calls", 0) or 0)
            jev_latency = int(float(jev_info.get("avg_latency_ms", 0.0) or 0.0))

            fastlane_ratio = int((jev_calls / total_calls) * 100) if total_calls > 0 else 0

            cost_lines = [
                "**Thống kê Chi phí AI hôm nay:**",
                f"- **Tổng ngân sách:** ${total_usd:.4f} USD (~{int(total_vnd):,} VND) | **Tokens:** {total_tokens:,}",
                f"- **{llm_label}:** {llm_calls} lượt ({llm_tokens:,} tokens{thinking_part}) - ${llm_cost_usd:.4f} - Phản hồi TB: {llm_latency}ms",
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
                        "tenant_key": eff_tenant,
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
                        "tenant_key": eff_tenant,
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
                        "tenant_key": eff_tenant,
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
                        "tenant_key": eff_tenant,
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
        "schema": "2.0",
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
        "body": {
            "elements": elements,
        },
    }


# Các tên hàm viết tắt tương thích
build_claim_card = build_claim_approval_card
build_digest_card = build_digest_approval_card
build_draft_approval_card = build_draft_card


def build_onboarding_welcome_card(
    open_id: str,
    user_name: str = "",
    base_url: Optional[str] = None,
    tenant_key: Optional[str] = None,
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
    tenant_param = f"&tenant_key={urllib.parse.quote(tenant_key)}" if tenant_key else ""
    wizard_url = f"{resolved_base}/onboarding/wizard?open_id={open_id}&user_name={urllib.parse.quote(display_name)}{tenant_param}"
    
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


def build_base_provisioned_card(
    app_url: str,
    admin_name: str = "",
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ thông báo khởi tạo thành công Lark Base Quản trị Doanh nghiệp.
    Bao gồm nút mở trực tiếp Base và hướng dẫn phân công dự án.
    """
    display_name = admin_name.strip() if admin_name else "Sếp"
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**Xin chúc mừng {display_name}!**\n\n"
                    "Trợ lý HiLark đã tự động khởi tạo thành công **Lark Base Quản Trị Doanh Nghiệp** "
                    "ngay trên Lark Drive của bạn với đầy đủ cấu trúc chuẩn:\n\n"
                    "• **Bảng 1: Danh mục Dự án & Nhóm chat** (Quản lý 3 dự án Atlas, Pulse, Sentinel)\n"
                    "• **Bảng 2: Chính sách & Quy định Công ty** (Sổ tay nhân viên & Quy chế)\n\n"
                    "Bạn đã được phân quyền **Toàn quyền Quản trị (Owner/Editor)** để phân công nhân sự và tài liệu."
                ),
            },
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
                        "content": "Mở Lark Base Quản Trị",
                    },
                    "type": "primary",
                    "url": app_url,
                    "multi_url": {
                        "url": app_url,
                        "pc_url": app_url,
                        "android_url": app_url,
                        "ios_url": app_url,
                    },
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
                "content": "Khởi Tạo Lark Base Quản Trị Thành Công",
            },
        },
        "elements": elements,
    }


def build_marketplace_welcome_card(
    tenant_config: Any,
    wizard_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ tương tác Chào mừng (Marketplace Welcome Card V2) gửi qua Lark DM cho Admin.
    Tự động hiển thị đường dẫn Lark Base trên Drive, tài khoản WeKnora Admin và nút mở Screen Guide.
    """
    def _val(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            val = obj.get(key)
            return val if val is not None else default
        val = getattr(obj, key, None)
        return val if val is not None else default

    ent_name = _val(tenant_config, "enterprise_name") or _val(tenant_config, "tenant_name") or "Doanh nghiệp"
    base_url = _val(tenant_config, "bitable_app_url", "") or "https://open.larksuite.com"
    creds = _val(tenant_config, "weknora_admin_user") or _val(tenant_config, "admin_credentials")
    
    username = _val(creds, "username", "")
    password = _val(creds, "initial_password", "")
    web_url = _val(creds, "web_url", "")
    tenant_key = _val(tenant_config, "tenant_key", "")

    # Nếu username hoặc password bị thiếu mà có tenant_key, tự động tra cứu từ MongoDB để hiển thị đầy đủ
    if (not username or not password) and tenant_key:
        try:
            from database.db import get_sync_client
            c = get_sync_client()
            db = c[settings.MONGO_DB] if c else None
            if db is not None:
                doc = db["tenants"].find_one({"tenant_key": tenant_key})
                if doc:
                    db_creds = doc.get("weknora_admin_user") or doc.get("admin_credentials")
                    if db_creds:
                        username = username or _val(db_creds, "username", "")
                        password = password or _val(db_creds, "initial_password", "")
                        web_url = web_url or _val(db_creds, "web_url", "")
                    if not base_url or base_url == "https://open.larksuite.com":
                        base_url = doc.get("bitable_app_url", "") or base_url
                    if ent_name == "Doanh nghiệp":
                        ent_name = doc.get("enterprise_name") or ent_name
        except Exception:
            pass

    # Đảm bảo không bao giờ để trống username hoặc password trong thẻ chào mừng gửi người dùng
    if not username and tenant_key:
        username = f"admin_{tenant_key[:8]}@hilark.internal"
    elif not username:
        username = "admin@hilark.internal"

    if not password and tenant_key:
        password = f"HLK@{tenant_key[:8].capitalize()}!2026"
    elif not password:
        password = "HLK@Default2026!"

    # Loại bỏ URL nội bộ/placeholder để tránh gửi localhost cho người dùng bên ngoài.
    invalid_web_url = (
        not web_url
        or ":8080" in str(web_url).lower()
        or "yourdomain.com" in str(web_url).lower()
        or "localhost" in str(web_url).lower()
        or "127.0.0.1" in str(web_url).lower()
        or "0.0.0.0" in str(web_url).lower()
    )
    if invalid_web_url:
        web_url = getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login")

    app_base = getattr(settings, "APP_BASE_URL", "http://localhost:8000").rstrip("/")
    raw_wizard_url = wizard_url or f"{app_base}/onboarding/wizard?tenant_key={tenant_key}"
    import urllib.parse
    effective_wizard_url = f"https://applink.larksuite.com/client/web_url/open?url={urllib.parse.quote(raw_wizard_url)}&mode=window&height=660&width=560"

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**Kính chào Quản trị viên {ent_name}!**\n\n"
                    "Trợ lý HiLark đã được kích hoạt thành công trên không gian làm việc của bạn từ Lark App Directory. "
                    "Hạ tầng quản trị và kho tri thức riêng biệt đã được thiết lập tự động 100%:"
                ),
            },
        },
        {
            "tag": "hr",
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**1. Trung Tâm Quản Trị Dự Án & Nhóm Chat (Lark Base)**\n"
                    "Đã tạo sẵn trên Lark Drive của bạn với cấu trúc 3 dự án (Atlas, Pulse, Sentinel) và Chính sách công ty. "
                    "Bạn có toàn quyền Owner/Editor để gán nhóm chat và tài liệu."
                ),
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**2. Không Gian Tri Thức & Wiki Báo Cáo (WeKnora Web)**\n"
                    f"• Cổng đăng nhập: [Mở WeKnora Web Console]({web_url})\n"
                    f"• Tài khoản: `{username}`\n"
                    f"• Mật khẩu ban đầu: `{password}`\n\n"
                    "Dùng để tra cứu và đọc lại toàn văn các bản tổng hợp công việc (Daily Digests) chi tiết của toàn công ty."
                ),
            },
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
                        "content": "Mở Lark Base Quản Trị",
                    },
                    "type": "primary",
                    "url": base_url,
                    "multi_url": {
                        "url": base_url,
                        "pc_url": base_url,
                        "android_url": base_url,
                        "ios_url": base_url,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Đăng Nhập WeKnora",
                    },
                    "type": "default",
                    "url": web_url,
                    "multi_url": {
                        "url": web_url,
                        "pc_url": web_url,
                        "android_url": web_url,
                        "ios_url": web_url,
                    },
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Tùy Chỉnh Thiết Lập",
                    },
                    "type": "default",
                    "url": effective_wizard_url,
                    "multi_url": {
                        "url": effective_wizard_url,
                        "pc_url": effective_wizard_url,
                        "android_url": effective_wizard_url,
                        "ios_url": effective_wizard_url,
                    },
                },
            ],
        },
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Thêm bot HiLark vào các nhóm chat cần hỗ trợ để bắt đầu nhận diện thảo luận và tổng hợp báo cáo tự động.",
                }
            ],
        },
    ]

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": f"HiLark — Trợ Lý AI {ent_name} Đã Sẵn Sàng",
            },
        },
        "elements": elements,
    }


def build_admin_status_card(
    tenant_config: Any,
    active_chat_count: int = 0,
    wizard_url: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ báo cáo trạng thái vận hành của doanh nghiệp cho Admin (/status).
    """
    if isinstance(tenant_config, dict):
        try:
            from models.tenant import TenantConfigRecord
            tenant_config = TenantConfigRecord.from_dict(tenant_config)
        except Exception:
            pass

    ent_name = getattr(tenant_config, "enterprise_name", None) or getattr(tenant_config, "tenant_name", None) or "Doanh nghiệp"
    base_url = getattr(tenant_config, "bitable_app_url", "") or ""
    tenant_key = getattr(tenant_config, "tenant_key", "")
    policy_kb = getattr(tenant_config, "weknora_policy_dataset_id", "") or "Đang kết nối"
    wiki_kb = getattr(tenant_config, "weknora_wiki_dataset_id", "") or "Đang kết nối"
    creds = getattr(tenant_config, "weknora_admin_user", None)
    web_url = getattr(creds, "web_url", "") if creds else getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login")

    effective_wizard_url = wizard_url or f"/onboarding/wizard?tenant_key={tenant_key}"

    content_lines = [
        f"**Báo Cáo Hiện Trạng Vận Hành — {ent_name}**",
        "",
        f"• **Mã Doanh Nghiệp (Tenant):** `{tenant_key}`",
    ]

    if metrics:
        total_scopes = metrics.get("chat_scopes", {}).get("total", active_chat_count)
        active_scopes = metrics.get("chat_scopes", {}).get("active", total_scopes)
        msg_today = metrics.get("messages", {}).get("today", 0)
        msg_total = metrics.get("messages", {}).get("total", 0)
        claims_curr = metrics.get("claims", {}).get("current", 0)
        claims_prop = metrics.get("claims", {}).get("proposed", 0)
        drafts_sent = metrics.get("drafts", {}).get("sent", 0)
        drafts_pending = metrics.get("drafts", {}).get("pending", 0)
        total_tokens = metrics.get("telemetry", {}).get("total_tokens", 0)
        est_cost = metrics.get("telemetry", {}).get("estimated_cost_usd", 0.0)

        content_lines.extend([
            f"• **Nhóm Chat Phân Quyền:** {total_scopes} nhóm ({active_scopes} đang hoạt động)",
            f"• **Tin Nhắn Hôm Nay:** {msg_today} tin (Tổng lịch sử: {msg_total})",
            f"• **Tri Thức Đã Tích Lũy:** {claims_curr} thông tin chính thức (+{claims_prop} đề xuất)",
            f"• **Bản Nháp Phê Duyệt:** {drafts_sent} đã gửi ({drafts_pending} đang chờ)",
            f"• **Chi Phí AI & Token:** {total_tokens:,} tokens (~${est_cost})",
        ])
    else:
        content_lines.extend([
            f"• **Nhóm Chat Phân Quyền:** {active_chat_count} nhóm đang hoạt động",
            f"• **Lark Base Quản Trị:** {'Đã kết nối' if base_url else 'Chưa khởi tạo'}",
            f"• **Kho Tri Thức Policy:** `{policy_kb}`",
            f"• **Kho Tri Thức Wiki:** `{wiki_kb}`",
        ])

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(content_lines),
            },
        },
        {
            "tag": "hr",
        },
    ]

    # Hàng nút 1: Nền tảng
    row1_actions: List[Dict[str, Any]] = [
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "Mở Lark Base",
            },
            "type": "primary",
            "url": base_url or "#",
        },
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "WeKnora Console",
            },
            "type": "default",
            "url": web_url,
        },
    ]
    elements.append({
        "tag": "action",
        "actions": row1_actions,
    })

    # Hàng nút 2: Điều phối
    row2_actions: List[Dict[str, Any]] = [
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "Cấu Hình (Wizard)",
            },
            "type": "default",
            "url": effective_wizard_url,
        },
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "⬅️ Bảng Điều Khiển",
            },
            "type": "default",
            "value": {
                "action": "view_owner_hub",
                "tenant_key": tenant_key,
            },
        },
    ]
    elements.append({
        "tag": "action",
        "actions": row2_actions,
    })

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "turquoise",
            "title": {
                "tag": "plain_text",
                "content": f"Bảng Điều Khiển Quản Trị — {ent_name}",
            },
        },
        "elements": elements,
    }


def build_owner_control_hub_card(
    tenant_config: Any,
    user_name: str = "",
    open_id: str = "",
    pending_digest: Any = None,
    pending_draft: Any = None,
    active_chat_count: int = 0,
    wizard_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây dựng Thẻ Bảng Điều Khiển Quản Trị (Owner Control Hub Card) 100% hướng nút bấm.
    Dành cho Lãnh đạo / Admin tương tác trong DM 1-1, thay thế toàn bộ dòng lệnh văn bản.
    """
    import urllib.parse
    from core.config import settings

    if isinstance(tenant_config, dict):
        try:
            from models.tenant import TenantConfigRecord
            tenant_config = TenantConfigRecord.from_dict(tenant_config)
        except Exception:
            pass

    ent_name = (
        getattr(tenant_config, "enterprise_name", None)
        or getattr(tenant_config, "tenant_name", None)
        or "Doanh nghiệp"
    )
    base_url = getattr(tenant_config, "bitable_app_url", "") or ""
    tenant_key = getattr(tenant_config, "tenant_key", "")
    creds = getattr(tenant_config, "weknora_admin_user", None)
    web_url = getattr(creds, "web_url", "") if creds else getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login")

    resolved_base = settings.APP_BASE_URL.rstrip("/")
    display_name = user_name.strip() if user_name else "Lãnh đạo"
    tenant_param = f"&tenant_key={urllib.parse.quote(tenant_key)}" if tenant_key else ""
    wizard_endpoint = wizard_url or f"{resolved_base}/onboarding/wizard?open_id={open_id}&user_name={urllib.parse.quote(display_name)}{tenant_param}"
    applink_wizard_url = f"https://applink.larksuite.com/client/web_url/open?url={urllib.parse.quote(wizard_endpoint)}&mode=window&height=660&width=560"

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**Kính chào {display_name}!**\n\n"
                    "Chào mừng bạn đến với **Trung Tâm Điều Phối HiLark**. "
                    "Hệ thống hoạt động hoàn toàn qua Thẻ tương tác 1-Click. "
                    "Mọi chức năng điều hành, kiểm duyệt và báo cáo đều được kích hoạt bằng các nút bấm bên dưới:"
                ),
            },
        },
        {
            "tag": "hr",
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"• **Doanh Nghiệp (Tenant):** {ent_name} (`{tenant_key}`)\n"
                    f"• **Nhóm Chat Phân Quyền:** {active_chat_count} nhóm đang hoạt động\n"
                    f"• **Lark Base Quản Trị:** {'Đã kết nối' if base_url else 'Chưa khởi tạo'}\n"
                    f"• **Kho Tri Thức WeKnora:** {'Sẵn sàng' if creds else 'Chưa kết nối'}\n"
                ),
            },
        },
    ]

    # Thông báo trạng thái đang chờ duyệt (nếu có)
    if pending_digest:
        digest_date = getattr(pending_digest, "date", "hôm nay")
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"Báo cáo tổng hợp ngày {digest_date} đang chờ bạn phê duyệt tri thức.",
                }
            ],
        })
    elif pending_draft:
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Có bản nháp câu trả lời đang chờ bạn phê duyệt gửi vào nhóm.",
                }
            ],
        })

    elements.append({"tag": "hr"})

    # Hàng nút 1: Truy cập nền tảng và Screen Guide
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "Mở Lark Base Quản Trị",
                },
                "type": "primary",
                "url": base_url or "#",
                "multi_url": {
                    "url": base_url or "#",
                    "pc_url": base_url or "#",
                    "android_url": base_url or "#",
                    "ios_url": base_url or "#",
                },
            },
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "WeKnora Console",
                },
                "type": "default",
                "url": web_url,
            },
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "Cấu Hình Trợ Lý",
                },
                "type": "default",
                "url": applink_wizard_url,
            },
        ],
    })

    # Hàng nút 2: Tác vụ điều hành
    row2_actions: List[Dict[str, Any]] = [
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "Tài Khoản WeKnora",
            },
            "type": "default",
            "value": {
                "action": "view_weknora_info",
                "tenant_key": tenant_key,
            },
        },
    ]

    elements.append({
        "tag": "action",
        "actions": row2_actions,
    })

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "turquoise",
            "title": {
                "tag": "plain_text",
                "content": f"Bảng Điều Khiển Trợ Lý — {ent_name}",
            },
        },
        "elements": elements,
    }


def build_user_reauth_card(
    tenant_key: Optional[str] = None,
    auth_url: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Thẻ DM gửi riêng cho Lãnh đạo khi User Access Token bị thiếu hoặc hết hạn,
    yêu cầu cấp lại quyền để tiếp tục gửi phản hồi nhân danh Lãnh đạo.
    """
    import urllib.parse

    clean_tenant = (tenant_key or "").strip()
    if not auth_url:
        base_url = getattr(settings, "APP_BASE_URL", "").rstrip("/")
        tenant_query = f"?tenant_key={urllib.parse.quote(clean_tenant)}" if clean_tenant else ""
        auth_url = f"{base_url}/auth/lark/login{tenant_query}" if base_url else f"/auth/lark/login{tenant_query}"

    reason_line = f"\n\nLý do chi tiết: {reason.strip()}" if reason and reason.strip() else ""

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "Phiên ủy quyền tài khoản Lark của bạn hiện chưa sẵn sàng hoặc đã hết hạn, "
                    "nên trợ lý tạm thời chưa thể gửi câu trả lời nhân danh bạn vào nhóm."
                    f"{reason_line}\n\n"
                    "Vui lòng nhấn nút bên dưới để đăng nhập và cấp lại quyền User Access Token. "
                    "Bản nháp câu trả lời hiện tại vẫn được giữ an toàn để bạn gửi lại ngay sau khi ủy quyền."
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Ủy Quyền Lại Tài Khoản Lark",
                    },
                    "type": "primary",
                    "url": auth_url,
                },
            ],
        },
    ]

    if clean_tenant:
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"Mã doanh nghiệp: {clean_tenant}",
                }
            ],
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {
                "tag": "plain_text",
                "content": "Cần Ủy Quyền Lại Tài Khoản Lark",
            },
        },
        "elements": elements,
    }


def build_admin_oauth_invite_card(
    tenant_key: str,
    app_id: str = "",
    auth_url: Optional[str] = None,
    enterprise_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Thẻ mời Admin hoàn tất bước OAuth User khi doanh nghiệp mở hoặc kích hoạt trợ lý HiLark.
    Quy tắc trình bày: thuần tiếng Việt, rõ ràng, không dùng emoji.
    """
    import urllib.parse

    clean_tenant = (tenant_key or "").strip()
    clean_app = (app_id or "").strip()
    ent_label = (enterprise_name or "").strip() or (f"Doanh nghiệp {clean_tenant}" if clean_tenant else "Doanh nghiệp")

    if not auth_url:
        base_url = getattr(settings, "APP_BASE_URL", "").rstrip("/")
        tenant_query = f"?tenant_key={urllib.parse.quote(clean_tenant)}" if clean_tenant else ""
        auth_url = f"{base_url}/auth/lark/login{tenant_query}" if base_url else f"/auth/lark/login{tenant_query}"

    app_line = f"\n• **Ứng dụng (App ID):** `{clean_app}`" if clean_app else ""

    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"Chào mừng **{ent_label}** đã cài đặt trợ lý HiLark.\n\n"
                    "Hệ thống đang tạm dừng ở cổng kích hoạt **Ủy quyền Quản trị viên** để liên kết "
                    "danh tính Lãnh đạo trước khi tự động khởi tạo hạ tầng Lark Base và kho tri thức WeKnora."
                    f"\n• **Mã doanh nghiệp:** `{clean_tenant}`"
                    f"{app_line}\n\n"
                    "Vui lòng nhấn nút bên dưới để đăng nhập Lark và cấp quyền. Ngay sau khi hoàn tất, "
                    "hệ thống sẽ tự động cấp phát tài nguyên và gửi thẻ bàn giao cho bạn."
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Ủy Quyền Tài Khoản Admin",
                    },
                    "type": "primary",
                    "url": auth_url,
                },
            ],
        },
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Quy trình kích hoạt: Cài đặt ứng dụng -> OAuth Admin -> Khởi tạo Base & WeKnora -> Sẵn sàng.",
                }
            ],
        },
    ]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "Kích Hoạt HiLark — Cần Ủy Quyền Tài Khoản Admin",
            },
        },
        "elements": elements,
    }




