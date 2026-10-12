import asyncio
from datetime import datetime
from database.db import get_staging_collection, get_daily_digests_collection
from models.digest import (
    StagingMessage,
    DailyDigestRecord,
    DecisionItem,
    CommitmentItem,
    StatusChangeItem,
    StatusCategory,
    SourceReference,
)

async def seed_data():
    stg_coll = get_staging_collection()
    dig_coll = get_daily_digests_collection()

    chat_id = "oc_802c12b86f7ab42ae736a45fc8f0c151"
    chat_name = "Dự Án HiLark Core"
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Bơm dữ liệu mẫu vào conversation_staging
    sample_messages = [
        StagingMessage(
            id="stg_001",
            message_id="om_msg_001_dec",
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name="Tống Phước Hoài Nam",
            speaker_id="ou_5a83a5e22269cfed0aaabeada2d3e603",
            text="@all Dự án HiLark sẽ chốt phương án Pure WebSocket để bảo toàn hạn ngạch API quota của Lark, ngắt hoàn toàn polling.",
            timestamp=f"{today}T09:15:00+07:00",
            message_link="https://applink.larksuite.com/client/message/open?open_message_id=om_msg_001_dec",
            project_tag="HILARK",
            processed=True,
        ),
        StagingMessage(
            id="stg_002",
            message_id="om_msg_002_cmt",
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name="Nguyễn Văn Tuấn",
            speaker_id="ou_tuan_backend_02",
            text="Em nhận task refactor module Lark Bot và gắn lifespan vào FastAPI, cam kết hoàn thành trước 17:00 chiều mai.",
            timestamp=f"{today}T10:30:00+07:00",
            message_link="https://applink.larksuite.com/client/message/open?open_message_id=om_msg_002_cmt",
            project_tag="HILARK",
            processed=True,
        ),
        StagingMessage(
            id="stg_003",
            message_id="om_msg_003_prog",
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name="Lê Thu Hương",
            speaker_id="ou_huong_frontend_03",
            text="Phần giao diện thẻ duyệt Interactive Card trên Lark đã hoàn thiện 90%, đang kiểm thử hiển thị trên app mobile.",
            timestamp=f"{today}T14:20:00+07:00",
            message_link="https://applink.larksuite.com/client/message/open?open_message_id=om_msg_003_prog",
            project_tag="HILARK",
            processed=True,
        ),
        StagingMessage(
            id="stg_004",
            message_id="om_msg_004_block",
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name="Trần Minh QA",
            speaker_id="ou_minh_qa_04",
            text="Team test đang bị blocker ở khâu cấp quyền Lark App mới trên Developer Console, cần Admin tenant duyệt quyền.",
            timestamp=f"{today}T15:45:00+07:00",
            message_link="https://applink.larksuite.com/client/message/open?open_message_id=om_msg_004_block",
            project_tag="HILARK",
            processed=True,
        ),
        StagingMessage(
            id="stg_005",
            message_id="om_msg_005_nam",
            chat_id=chat_id,
            chat_name=chat_name,
            speaker_name="Tống Phước Hoài Nam",
            speaker_id="ou_5a83a5e22269cfed0aaabeada2d3e603",
            text="Ok Minh, Nam sẽ liên hệ Admin duyệt quyền ngay trong chiều nay để gỡ blocker nhé.",
            timestamp=f"{today}T16:00:00+07:00",
            message_link="https://applink.larksuite.com/client/message/open?open_message_id=om_msg_005_nam",
            project_tag="HILARK",
            processed=True,
        ),
    ]

    for m in sample_messages:
        await stg_coll.update_one({"message_id": m.message_id}, {"$set": m.to_dict()}, upsert=True)

    print(f"✔ Đã bơm {len(sample_messages)} tin nhắn mẫu vào conversation_staging!")

    # 2. Bơm dữ liệu mẫu vào daily_digests
    digest_id = f"digest_{today.replace('-', '')}_{chat_id}"
    sample_digest = DailyDigestRecord(
        id=digest_id,
        date=today,
        chat_id=chat_id,
        chat_name=chat_name,
        project_tag="HILARK",
        overview_summary="Ngày làm việc tập trung chốt hạ tầng Pure WebSocket, phân công refactor kiến trúc FastAPI lifespan và tháo gỡ điểm nghẽn cấp quyền Lark App.",
        decisions=[
            DecisionItem(
                id="dec_01",
                title="Chốt hạ tầng Pure WebSocket",
                content="Thống nhất chuyển toàn bộ kết nối Lark sang Pure WebSocket, ngắt triệt để vòng lặp polling để bảo toàn hạn ngạch API quota.",
                scope="Toàn bộ hệ thống HiLark",
                source=SourceReference.create(
                    message_id="om_msg_001_dec",
                    speaker_name="Tống Phước Hoài Nam",
                    speaker_id="ou_5a83a5e22269cfed0aaabeada2d3e603",
                    timestamp=f"{today} 09:15",
                    quote="Dự án HiLark sẽ chốt phương án Pure WebSocket để bảo toàn hạn ngạch API quota của Lark",
                ),
            )
        ],
        commitments=[
            CommitmentItem(
                id="cmt_01",
                promiser_name="Nguyễn Văn Tuấn",
                promiser_id="ou_tuan_backend_02",
                task="Refactor module Lark Bot và tích hợp vào FastAPI lifespan",
                deadline=f"17:00 ngày mai",
                recipient_name="Tống Phước Hoài Nam",
                is_completed=False,
                source=SourceReference.create(
                    message_id="om_msg_002_cmt",
                    speaker_name="Nguyễn Văn Tuấn",
                    speaker_id="ou_tuan_backend_02",
                    timestamp=f"{today} 10:30",
                    quote="Em nhận task refactor module Lark Bot và gắn lifespan vào FastAPI, cam kết hoàn thành trước 17:00 chiều mai.",
                ),
            ),
            CommitmentItem(
                id="cmt_02",
                promiser_name="Tống Phước Hoài Nam",
                promiser_id="ou_5a83a5e22269cfed0aaabeada2d3e603",
                task="Liên hệ Admin duyệt cấp quyền Lark App mới để gỡ blocker cho QA",
                deadline=f"18:00 {today}",
                recipient_name="Trần Minh QA",
                is_completed=False,
                source=SourceReference.create(
                    message_id="om_msg_005_nam",
                    speaker_name="Tống Phước Hoài Nam",
                    speaker_id="ou_5a83a5e22269cfed0aaabeada2d3e603",
                    timestamp=f"{today} 16:00",
                    quote="Nam sẽ liên hệ Admin duyệt quyền ngay trong chiều nay để gỡ blocker nhé.",
                ),
            ),
        ],
        status_changes=[
            StatusChangeItem(
                id="stc_01",
                category=StatusCategory.PROGRESS,
                target_object="Giao diện Interactive Card Lark",
                summary="Đạt 90% khối lượng công việc, đang kiểm thử hiển thị trên mobile client",
                previous_state="Đang phát triển (70%)",
                new_state="Hoàn thiện 90%",
                source=SourceReference.create(
                    message_id="om_msg_003_prog",
                    speaker_name="Lê Thu Hương",
                    speaker_id="ou_huong_frontend_03",
                    timestamp=f"{today} 14:20",
                    quote="Phần giao diện thẻ duyệt Interactive Card trên Lark đã hoàn thiện 90%",
                ),
            ),
            StatusChangeItem(
                id="stc_02",
                category=StatusCategory.BLOCKER,
                target_object="Môi trường kiểm thử QA",
                summary="Bị nghẽn do chưa được Admin cấp quyền Lark App mới trên Developer Console",
                previous_state="Bình thường",
                new_state="Bị nghẽn (Blocker)",
                blocker_reason="Chờ Admin tenant duyệt cấp quyền im:message và im:chat",
                source=SourceReference.create(
                    message_id="om_msg_004_block",
                    speaker_name="Trần Minh QA",
                    speaker_id="ou_minh_qa_04",
                    timestamp=f"{today} 15:45",
                    quote="Team test đang bị blocker ở khâu cấp quyền Lark App mới trên Developer Console",
                ),
            ),
        ],
        message_count=len(sample_messages),
        sync_status="pending",
    )

    await dig_coll.update_one({"id": sample_digest.id}, {"$set": sample_digest.to_dict()}, upsert=True)
    print(f"✔ Đã bơm bản ghi tổng hợp mẫu vào daily_digests: {sample_digest.id}")

if __name__ == "__main__":
    asyncio.run(seed_data())
