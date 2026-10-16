"""
HiLark - Lark Base (Bitable) Data Models
=========================================
Vị trí: server/models/larkbase.py

Chứa các cấu trúc dữ liệu cho Lark Base (Bitable):
  - BITABLE_FIELD_TYPE_MAP: Bản đồ ánh xạ mã kiểu dữ liệu số nguyên của Bitable sang tên hiển thị.
  - LarkBaseField: Metadata của cột/trường trong bảng.
  - LarkBaseRecord: Bản ghi dữ liệu (raw + clean fields).
  - LarkBaseQueryResult: Kết quả truy vấn tổng thể (schema + records + pagination).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Bản đồ mã kiểu dữ liệu Bitable sang tên hiển thị dễ hiểu
BITABLE_FIELD_TYPE_MAP: Dict[int, str] = {
    1: "Text (Văn bản)",
    2: "Number (Số)",
    3: "SingleSelect (Chọn một)",
    4: "MultiSelect (Chọn nhiều)",
    5: "DateTime (Ngày giờ)",
    7: "Checkbox (Hộp kiểm)",
    11: "User (Người dùng)",
    13: "Phone (Số điện thoại)",
    15: "Url (Đường dẫn)",
    17: "Attachment (Tệp đính kèm)",
    18: "SingleLink (Liên kết bảng)",
    19: "Lookup (Tra cứu)",
    20: "Formula (Công thức)",
    21: "DuplexLink (Liên kết hai chiều)",
    22: "Location (Vị trí)",
    23: "GroupChat (Nhóm chat)",
    1001: "CreatedTime (Thời gian tạo)",
    1002: "ModifiedTime (Thời gian sửa)",
    1003: "CreatedUser (Người tạo)",
    1004: "ModifiedUser (Người sửa)",
    1005: "AutoNumber (Tự động tăng)",
}


@dataclass
class LarkBaseField:
    """Thông tin một cột (trường) trong bảng Lark Base."""
    field_id: str
    field_name: str
    type: int
    type_name: str = ""
    is_primary: bool = False
    description: Optional[str] = None
    property: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.type_name:
            self.type_name = BITABLE_FIELD_TYPE_MAP.get(self.type, f"Unknown ({self.type})")


@dataclass
class LarkBaseRecord:
    """Bản ghi dữ liệu từ Lark Base."""
    record_id: str
    fields: Dict[str, Any]
    clean_fields: Dict[str, Any] = field(default_factory=dict)
    created_time: Optional[int] = None
    last_modified_time: Optional[int] = None
    record_url: Optional[str] = None

    def to_dict(self, clean: bool = True) -> Dict[str, Any]:
        """Chuyển bản ghi thành dict tiêu chuẩn."""
        return {
            "record_id": self.record_id,
            "fields": self.clean_fields if clean else self.fields,
            "created_time": self.created_time,
            "last_modified_time": self.last_modified_time,
            "record_url": self.record_url,
        }


@dataclass
class LarkBaseQueryResult:
    """Kết quả truy vấn tổng thể từ Lark Base."""
    app_token: str
    table_id: str
    total_records: int
    records: List[LarkBaseRecord]
    fields: List[LarkBaseField] = field(default_factory=list)
    has_more: bool = False
    next_page_token: Optional[str] = None

    def to_dict_list(self, clean: bool = True) -> List[Dict[str, Any]]:
        """Trả về danh sách các bản ghi dạng [{field_name: value}, ...]."""
        result = []
        for r in self.records:
            item = {"_record_id": r.record_id}
            item.update(r.clean_fields if clean else r.fields)
            result.append(item)
        return result

    def to_markdown_table(self, max_rows: Optional[int] = None) -> str:
        """Định dạng kết quả thành bảng Markdown để hiển thị hoặc đưa vào LLM."""
        if not self.records:
            return "_Không có bản ghi nào trong bảng._"

        # Lấy danh sách tên cột
        if self.fields:
            headers = [f.field_name for f in self.fields]
        else:
            headers = []
            for r in self.records:
                for k in r.clean_fields.keys():
                    if k not in headers:
                        headers.append(k)

        if not headers:
            headers = ["record_id"]

        rows_to_show = self.records[:max_rows] if max_rows else self.records
        md_lines = []

        # Header row
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Data rows
        for r in rows_to_show:
            row_vals = []
            for h in headers:
                val = r.clean_fields.get(h, "")
                if val is None:
                    str_val = ""
                elif isinstance(val, (dict, list)):
                    str_val = json.dumps(val, ensure_ascii=False)
                else:
                    str_val = str(val).replace("\n", " ").replace("|", "\\|")
                # Giới hạn độ dài ô để bảng không vỡ
                if len(str_val) > 80:
                    str_val = str_val[:77] + "..."
                row_vals.append(str_val)
            md_lines.append("| " + " | ".join(row_vals) + " |")

        if max_rows and len(self.records) > max_rows:
            md_lines.append(f"\n_... và còn {len(self.records) - max_rows} bản ghi khác._")

        return "\n".join(md_lines)
