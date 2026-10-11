import os
import sys
import time
import json
import asyncio
import functools
import inspect
from typing import Any, Callable, Dict, List, Optional, Union

# Đảm bảo đường dẫn import server/ luôn hợp lệ
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from utils.llm_extractor.claim_extraction import (
    Claim,
    ClaimExtractor,
    claim_extractor,
    extract_claims,
    extract_claim,
    fix_json,
)

# ==============================================================================
# 1. CẤU HÌNH ĐƠN GIÁ API (GEMINI 2.5 FLASH)
# ==============================================================================
# Đơn vị: USD trên 1 triệu token
# Input (Văn bản, hình ảnh, video): $0.30 / 1M tokens
# Output (Phản hồi, suy luận): $2.50 / 1M tokens
INPUT_PRICE_PER_M = 0.30
OUTPUT_PRICE_PER_M = 2.50
USD_TO_VND = 25400.0


# ==============================================================================
# 2. DECORATOR ĐO LATENCY VÀ CHI PHÍ (COST)
# ==============================================================================
def measure_latency_and_cost(
    extractor_instance: Optional[ClaimExtractor] = None,
    print_report: bool = True
):
    """
    Decorator đo thời gian thực thi (Latency) và Chi phí (Cost) của mô hình Gemini 2.5 Flash.
    
    Hỗ trợ cả hàm Async và Sync.
    Đơn giá tính toán:
      - Input:  $0.30 / 1.000.000 token
      - Output: $2.50 / 1.000.000 token
    """
    def decorator(func: Callable):
        is_async = inspect.iscoroutinefunction(func)

        def _compute_and_display_metrics(
            latency: float,
            extractor: ClaimExtractor,
            func_name: str
        ) -> Dict[str, Any]:
            # Lấy thông số token từ claim_extractor
            metrics = getattr(extractor, "last_metrics", {})
            prompt_tokens = metrics.get("prompt_tokens", 0)
            candidates_tokens = metrics.get("candidates_tokens", 0)
            total_tokens = metrics.get("total_tokens", prompt_tokens + candidates_tokens)
            fix_attempts = metrics.get("fix_attempts", 0)

            # Tính toán chi phí USD
            cost_input_usd = (prompt_tokens / 1_000_000.0) * INPUT_PRICE_PER_M
            cost_output_usd = (candidates_tokens / 1_000_000.0) * OUTPUT_PRICE_PER_M
            total_cost_usd = cost_input_usd + cost_output_usd
            total_cost_vnd = total_cost_usd * USD_TO_VND

            perf_summary = {
                "function": func_name,
                "latency_sec": latency,
                "latency_ms": latency * 1000.0,
                "prompt_tokens": prompt_tokens,
                "candidates_tokens": candidates_tokens,
                "total_tokens": total_tokens,
                "cost_input_usd": cost_input_usd,
                "cost_output_usd": cost_output_usd,
                "total_cost_usd": total_cost_usd,
                "total_cost_vnd": total_cost_vnd,
                "fix_attempts": fix_attempts,
            }

            if print_report:
                print("\n" + "=" * 70)
                print(" ⏱️  HIỆU NĂNG & CHI PHÍ API (GEMINI 2.5 FLASH)".center(68))
                print("=" * 70)
                print(f" • Hàm gọi:           {func_name}()")
                print(f" • Độ trễ (Latency):  {latency:.3f}s ({latency * 1000.0:.1f} ms)")
                print(f" • Số lần sửa lỗi:    {fix_attempts} lần (Self-Correction feedback)")
                print("-" * 70)
                print(f" • Tokens đầu vào:    {prompt_tokens:,} tokens".ljust(40) + f"-->  ${cost_input_usd:.8f} (~{cost_input_usd * USD_TO_VND:.3f} VNĐ)")
                print(f" • Tokens đầu ra:     {candidates_tokens:,} tokens".ljust(40) + f"-->  ${cost_output_usd:.8f} (~{cost_output_usd * USD_TO_VND:.3f} VNĐ)")
                print(f" • Tổng Tokens:       {total_tokens:,} tokens")
                print("-" * 70)
                print(f" • TỔNG CHI PHÍ:      ${total_cost_usd:.8f} USD  (~{total_cost_vnd:.2f} VNĐ)")
                print("=" * 70 + "\n")

            return perf_summary

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            extractor = extractor_instance or claim_extractor
            start_time = time.perf_counter()
            result = await func(*args, **kwargs)
            latency = time.perf_counter() - start_time

            _compute_and_display_metrics(latency, extractor, func.__name__)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            extractor = extractor_instance or claim_extractor
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            latency = time.perf_counter() - start_time

            _compute_and_display_metrics(latency, extractor, func.__name__)
            return result

        return async_wrapper if is_async else sync_wrapper

    return decorator


# ==============================================================================
# 3. HÀM IN BẢNG CLAIM RA TERMINAL
# ==============================================================================
def print_claims_table(claims: List[Claim], raw_input: str = ""):
    """
    In kết quả Claims ra terminal theo định dạng thẻ rõ ràng, trực quan.
    """
    print("-" * 70)
    if raw_input:
        print(f"💬 Tin nhắn đầu vào: \"{raw_input}\"")
        print("-" * 70)

    if not claims:
        print("ℹ️  KẾT QUẢ: Không tìm thấy Claim nào (Tin nhắn không chứa thông tin sự thật/khẳng định cần lưu trữ).")
        print("-" * 70)
        return

    print(f"🎯 KẾT QUẢ: Trích xuất thành công {len(claims)} Claim(s):")
    print("-" * 70)

    for i, c in enumerate(claims, start=1):
        # Format giá trị JSONB
        val_str = json.dumps(c.value, ensure_ascii=False) if isinstance(c.value, (dict, list)) else str(c.value)

        print(f"📌 [Claim #{i}]")
        print(f"   • id:                {c.id}")
        print(f"   • entity:            \033[94m{c.entity}\033[0m")
        print(f"   • predicate:         \033[92m{c.predicate}\033[0m")
        print(f"   • value:             \033[93m{val_str}\033[0m (type: {type(c.value).__name__})")
        print(f"   • source_message_id: {c.source_message_id or 'None'}")
        print(f"   • status:            {c.status}")
        print(f"   • superseded_by:     {c.superseded_by or 'None'}")
        print(f"   • created_at:        {c.created_at.isoformat()}")
        print("-" * 70)

    print("💾 \033[92mTất cả Claims trên đã được lưu trực tiếp vào CSDL server/database/claim.db\033[0m")
    print("-" * 70)


# ==============================================================================
# 4. CÁC HÀM THỰC THI TRÍCH XUẤT ĐÃ ĐƯỢC GẮN DECORATOR
# ==============================================================================
@measure_latency_and_cost()
async def extract_claims_with_metrics(
    text_or_req: Union[str, dict, Any],
    source_message_id: Optional[str] = None
) -> List[Claim]:
    return await extract_claims(text_or_req, source_message_id=source_message_id)


@measure_latency_and_cost()
def extract_claims_sync_with_metrics(
    text_or_req: Union[str, dict, Any],
    source_message_id: Optional[str] = None
) -> List[Claim]:
    return claim_extractor.extract_sync(text_or_req, source_message_id=source_message_id)


# ==============================================================================
# 5. BỘ TEST CASES MẪU
# ==============================================================================
SAMPLE_TEST_CASES = [
    {
        "name": "Case 1: Dự án có deadline và ngân sách cụ thể",
        "message": "Dự án Atlas deadline chốt vào ngày 20/10/2026, ngân sách duyệt là 500 triệu đồng. Anh Nam phụ trách chính.",
        "msg_id": "om_msg_001",
    },
    {
        "name": "Case 2: Cập nhật điều khoản thanh toán hợp đồng (Thay đổi dữ kiện)",
        "message": "Hợp đồng đối tác ABC đã thống nhất chia làm 3 đợt thanh toán thay vì 2 đợt. File scan hợp đồng đã tải lên Google Drive.",
        "msg_id": "om_msg_002",
    },
    {
        "name": "Case 3: Tin nhắn xã giao / chào hỏi (Mong đợi: 0 claim)",
        "message": "Chào buổi sáng cả nhà, chúc mọi người một ngày làm việc tràn đầy năng lượng nhé!",
        "msg_id": "om_msg_003",
    },
    {
        "name": "Case 4: Hạ tầng kỹ thuật & trạng thái máy chủ (Dữ liệu có cấu trúc)",
        "message": "Cụm server Kubernetes staging cluster_hanoi vừa nâng cấp lên bản 1.30, IP gateway là 10.0.0.1, trạng thái healthy 100%.",
        "msg_id": "om_msg_004",
    },
]


async def run_predefined_tests():
    """
    Chạy tự động các test case mẫu và hiển thị chi tiết Claim + Latency + Cost.
    """
    print("\n" + "=" * 70)
    print("🚀 BẮT ĐẦU CHẠY BỘ TEST MẪU CLAIM EXTRACTION".center(68))
    print("=" * 70)

    for idx, tc in enumerate(SAMPLE_TEST_CASES, start=1):
        print(f"\n▶ [{idx}/{len(SAMPLE_TEST_CASES)}] {tc['name']}")
        try:
            claims = await extract_claims_with_metrics(
                tc["message"],
                source_message_id=tc["msg_id"]
            )
            print_claims_table(claims, raw_input=tc["message"])
        except Exception as e:
            print(f"❌ LỖI KHI CHẠY TEST CASE: {e}")

    print("\n✅ HOÀN THÀNH TẤT CẢ TEST CASES MẪU!\n")


# ==============================================================================
# 6. CHẾ ĐỘ TEST TƯƠNG TÁC TRÊN TERMINAL (INTERACTIVE CLI)
# ==============================================================================
async def run_interactive_mode():
    """
    Chế độ dòng lệnh tương tác trực tiếp: Nhập văn bản bất kỳ để xem trích xuất Claim và chi phí.
    """
    print("\n" + "=" * 70)
    print("💬 CHẾ ĐỘ TEST TƯƠNG TÁC (INTERACTIVE TEST CLI)".center(68))
    print("   Nhập tin nhắn Lark để kiểm tra trích xuất Claim trực tiếp.")
    print("   Gõ 'exit' hoặc 'quit' để quay lại menu chính.")
    print("=" * 70 + "\n")

    msg_counter = 1
    while True:
        try:
            user_input = input("\n👉 Nhập tin nhắn cần test: ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 Thoát chế độ tương tác.")
                break

            msg_id = f"om_cli_{msg_counter:03d}"
            msg_counter += 1

            print("\n⏳ Đang gửi request tới Gemini 2.5 Flash qua ClaimExtractor...")
            claims = await extract_claims_with_metrics(user_input, source_message_id=msg_id)
            print_claims_table(claims, raw_input=user_input)

        except KeyboardInterrupt:
            print("\n\n👋 Thoát chế độ tương tác.")
            break
        except Exception as e:
            print(f"\n❌ LỖI: {e}\n")


# ==============================================================================
# 7. MAIN RUNNER VỚI MENU CHỌN
# ==============================================================================
async def main():
    # Kiểm tra nếu truyền tham số từ CLI (ví dụ: uv run python tests/test_claim_extraction.py 1)
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg in ("1", "--test", "-t", "test"):
            await run_predefined_tests()
            return
        elif arg in ("2", "--interactive", "-i"):
            await run_interactive_mode()
            return
        else:
            # Truyền trực tiếp tin nhắn cần test
            custom_msg = " ".join(sys.argv[1:])
            print(f"\n▶ Chạy test nhanh với tin nhắn từ CLI: \"{custom_msg}\"")
            claims = await extract_claims_with_metrics(custom_msg, source_message_id="cli_quick_test")
            print_claims_table(claims, raw_input=custom_msg)
            return

    while True:
        print("\n" + "=" * 70)
        print("🤖 HiLark Claim Extraction - Test & Benchmark Runner".center(68))
        print("=" * 70)
        print(" [1] Chạy bộ test cases mẫu (Predefined Test Cases)")
        print(" [2] Chế độ test tương tác (Interactive Test CLI)")
        print(" [3] Chạy 1 câu test nhanh")
        print(" [4] Xem danh sách Claims đã lưu trong claim.db")
        print(" [0] Thoát")
        print("=" * 70)

        try:
            choice = input("Lựa chọn của bạn (0-4): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThoát chương trình.")
            break

        if choice == "1":
            await run_predefined_tests()
        elif choice == "2":
            await run_interactive_mode()
        elif choice == "3":
            try:
                quick_input = input("Nhập câu cần test nhanh: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if quick_input:
                claims = await extract_claims_with_metrics(quick_input, source_message_id="quick_test_01")
                print_claims_table(claims, raw_input=quick_input)
        elif choice == "4":
            try:
                from database.db import get_claims, CLAIM_DB_PATH
                db_claims = get_claims(limit=20)
                print(f"\n📂 CSDL: {CLAIM_DB_PATH}")
                print(f"Tổng số claim tìm thấy: {len(db_claims)}")
                print("-" * 70)
                for i, r in enumerate(db_claims, start=1):
                    val_str = json.dumps(r['value'], ensure_ascii=False) if isinstance(r['value'], (dict, list)) else str(r['value'])
                    print(f"#{i} [{r['entity']}] -> {r['predicate']} = {val_str} (status: {r['status']}, id: {r['id'][:8]}...)")
                print("-" * 70)
            except Exception as e:
                print(f"❌ Lỗi khi đọc claim.db: {e}")
        elif choice == "0":
            print("Tạm biệt!")
            break
        else:
            print("Lựa chọn không hợp lệ. Vui lòng chọn từ 0 đến 4.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã hủy lệnh chạy.")
