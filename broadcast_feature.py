import asyncio
import sys
import httpx
from sqlalchemy import select

# Thiết lập output terminal thành UTF-8 trên Windows để không bị lỗi ký tự tiếng Việt
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from src.core.config import get_settings
from src.core.database import get_session
from src.core.models import Subscription
from src.core import init_db, close_db

async def main():
    settings = get_settings()
    init_db(settings.resolved_database_url)
    
    try:
        token = settings.telegram_bot_token
        
        # =========================================================================
        # BẠN CÓ THỂ SỬA NỘI DUNG TIN NHẮN THÔNG BÁO Ở DƯỚI ĐÂY
        # =========================================================================
        message_text = """📢 *THÔNG BÁO: CẬP NHẬT TRA CỨU & THÔNG BÁO VỀ GMP*

Bot vừa được tích hợp thêm các tính năng theo dõi và tra cứu tiêu chuẩn GMP (WHO, EU, PIC/S...) từ Cục Quản lý Dược (DAV):

🔎 *1. Tra cứu cơ sở đạt chuẩn GMP (/gmp)*
▸ *Cú pháp:* `/gmp <tên hoặc địa chỉ cơ sở>` _(Ví dụ: /gmp Stellapharm)_
▸ *Kết quả:* Hiển thị tức thì thông tin cơ sở đạt chuẩn GMP trong nước, ĐKKD Dược và các cơ sở nước ngoài đạt chuẩn, kèm theo *chi tiết phạm vi hoạt động/sản xuất*.

📊 *2. Xem thống kê dữ liệu GMP (/gmpstats)*
▸ *Cú pháp:* `/gmpstats`
▸ *Kết quả:* Hiển thị tổng hợp số lượng cơ sở sản xuất trong nước, nước ngoài và ĐKKD Dược hiện có trong CSDL của hệ thống.

🔔 *3. Tự động nhận thông báo GMP mới*
▸ Mỗi khi có đợt công bố GMP mới từ DAV, hệ thống sẽ tự động quét, so sánh và gửi ngay danh sách các cơ sở mới đạt chuẩn tới bạn.
▸ Bật/tắt nguồn nhận tin này tại /sources -> chọn *🎖️ DAV Việt Nam — Đạt chuẩn GMP*.

Cảm ơn bạn đã theo dõi - T."""
        # =========================================================================

        print("Đang quét danh sách người dùng...")
        async with get_session() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.is_active == True)
            )
            subscribers = list(result.scalars().all())
    
        if not subscribers:
            print("Không có người dùng nào đang active.")
            return

        print(f"Tìm thấy {len(subscribers)} người dùng. Bắt đầu gửi...")
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        sent_count = 0
        fail_count = 0
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for sub in subscribers:
                try:
                    resp = await client.post(url, json={
                        "chat_id": sub.chat_id,
                        "text": message_text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    })
                    resp.raise_for_status()
                    sent_count += 1
                    print(f"✅ Đã gửi tới {sub.chat_id}")
                    await asyncio.sleep(0.5)  # Tránh rate limit Telegram
                except Exception as e:
                    fail_count += 1
                    print(f"❌ Lỗi khi gửi tới {sub.chat_id}: {e}")
                    
        print(f"\nHOÀN TẤT! Đã gửi thành công: {sent_count} | Thất bại: {fail_count}")
    finally:
        await close_db()

if __name__ == "__main__":
    asyncio.run(main())
