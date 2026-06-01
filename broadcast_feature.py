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
        message_text = """
Bot ra mắt một tính năng mới: *PharmaTech Daily*.
Với chương trình như sau:
💡 *Thứ 2, 4, 6*: Sáng tạo Bào chế & Kỹ thuật Tá dược
📈 *Thứ 3, 5*: Xu hướng Kinh tế Dược & Patent Cliff
🔬 *Thứ 7, CN*: Câu chuyện Lâm sàng & Đột phá Sinh học

👉 Gõ lệnh /sources và bấm vào nút để bật nguồn *PharmaTech Daily* khi cần ạ. 

Chúc mọi người ngày mới tốt lành! hehe
"""
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
