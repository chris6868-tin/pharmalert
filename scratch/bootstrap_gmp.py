import asyncio
import os
import sys
from pathlib import Path

# Thiết lập output terminal thành UTF-8 trên Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Thêm thư mục hiện tại vào sys.path để import các module src
sys.path.append(os.getcwd())

from src.core.config import get_settings
from src.core.database import get_session, init_db, close_db, create_tables
from src.scraper.gmp_parser import parse_gmp_sheet, parse_license_sheet, sync_gmp_data

async def bootstrap():
    settings = get_settings()
    
    print("================== KHỞI TẠO DỮ LIỆU NỀN GMP (BOOTSTRAP) ==================")
    print(f"Database URL: {settings.resolved_database_url}")
    
    # Khởi tạo kết nối CSDL và tạo bảng nếu chưa có
    init_db(settings.resolved_database_url)
    await create_tables()
    
    # Xác định đường dẫn file Excel
    gmp_file = Path("data/temp/gmp_temp.xlsx")
    dkkd_file = Path("data/temp/dkkd_temp.xlsx")
    
    if not gmp_file.exists():
        print(f"❌ Không tìm thấy file GMP nền tại: {gmp_file}")
        return
    if not dkkd_file.exists():
        print(f"❌ Không tìm thấy file ĐKKD nền tại: {dkkd_file}")
        return
        
    async with get_session() as session:
        # 1. Đồng bộ dữ liệu GMP sản xuất (WHO/EU/PIC/S)
        print(f"\n1. Đang đọc và đồng bộ file GMP sản xuất: {gmp_file}...")
        gmp_bytes = gmp_file.read_bytes()
        gmp_rows = parse_gmp_sheet(gmp_bytes)
        print(f"   ├─ Tìm thấy {len(gmp_rows)} dòng dữ liệu chuẩn.")
        new_gmp = await sync_gmp_data(session, "gmp_manufacturing", gmp_rows)
        print(f"   └─ Đã thêm mới {len(new_gmp)} cơ sở sản xuất đạt chuẩn GMP.")
        
        # 2. Đồng bộ dữ liệu Giấy chứng nhận ĐKKD Dược
        print(f"\n2. Đang đọc và đồng bộ file ĐKKD Dược: {dkkd_file}...")
        dkkd_bytes = dkkd_file.read_bytes()
        dkkd_rows = parse_license_sheet(dkkd_bytes)
        print(f"   ├─ Tìm thấy {len(dkkd_rows)} dòng dữ liệu chuẩn.")
        new_dkkd = await sync_gmp_data(session, "gmp_license", dkkd_rows)
        print(f"   └─ Đã thêm mới {len(new_dkkd)} cơ sở đủ điều kiện kinh doanh dược đạt chuẩn GMP.")
        
        print("\nSaving changes to database...")
        # SQLAlchemy commits on context manager exit.

    print("\n✅ HOÀN THÀNH ĐỒNG BỘ DỮ LIỆU NỀN CÔNG TY GMP THÀNH CÔNG!")

if __name__ == "__main__":
    asyncio.run(bootstrap())
