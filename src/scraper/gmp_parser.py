import io
import re
import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.logging import get_logger
from ..core.models import GmpFactory

logger = get_logger("scraper.gmp_parser")


def _clean_str(val: any) -> str | None:
    """Clean and standardize strings from Excel cells."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    # Thay thế nhiều khoảng trắng hoặc newline liên tiếp bằng 1 khoảng trắng
    return re.sub(r"\s+", " ", val_str)


def parse_gmp_sheet(file_bytes: bytes) -> list[dict]:
    """Parse the WHO-GMP / EU-GMP manufacturing plants Excel sheet (cn92 list 1).
    
    Header row: row 4. Data starts at row 7.
    Indices:
      - Col 0 (TT): Index number (must be numeric to filter out header/meta rows)
      - Col 2 (Tên cơ sở)
      - Col 4 (Địa chỉ cơ sở)
      - Col 5 (Phạm vi chứng nhận)
      - Col 7 (Tiêu chuẩn)
      - Col 8 (Cơ quan cấp chứng nhận)
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    sheet = wb.active
    
    parsed_rows = []
    row_count = 0
    
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if row_idx < 6:  # Bỏ qua các dòng tiêu đề chung ban đầu
            continue
            
        if len(row) < 9:
            continue
            
        tt_val = _clean_str(row[0])
        # Kiểm tra xem dòng này có phải dòng dữ liệu thực tế (bắt đầu bằng số thứ tự)
        if not tt_val or not tt_val.isdigit():
            continue
            
        factory_name = _clean_str(row[2])
        address = _clean_str(row[4])
        
        if not factory_name or not address:
            continue
            
        parsed_rows.append({
            "factory_name": factory_name,
            "address": address,
            "scope": _clean_str(row[5]),
            "standard": _clean_str(row[7]),
            "authority": _clean_str(row[8]),
            "headquarters_address": None,
            "location_name": None,
            "responsible_pharmacist": None,
            "certificate_license": None
        })
        row_count += 1
        
    logger.info(f"Parsed {row_count} GMP manufacturing facilities from Excel sheet.")
    return parsed_rows


def parse_license_sheet(file_bytes: bytes) -> list[dict]:
    """Parse the DKKD Dược (Drug Business Certificate) Excel sheet (cn92 list 2).
    
    Header row: row 4. Data starts at row 7.
    Indices:
      - Col 0 (TT): Index number (must be numeric)
      - Col 1 (Tên cơ sở kinh doanh)
      - Col 2 (Địa chỉ trụ sở chính)
      - Col 3 (Tên địa điểm kinh doanh)
      - Col 4 (Địa điểm kinh doanh)
      - Col 5 (Người chịu trách nhiệm chuyên môn)
      - Col 6 (Phạm vi hoạt động sản xuất thuốc)
      - Col 7 (Giấy CN đủ điều kiện kinh doanh dược)
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    sheet = wb.active
    
    parsed_rows = []
    row_count = 0
    
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if row_idx < 5:  # Bỏ qua dòng tiêu đề ban đầu
            continue
            
        if len(row) < 8:
            continue
            
        tt_val = _clean_str(row[0])
        if not tt_val or not tt_val.isdigit():
            continue
            
        factory_name = _clean_str(row[1])
        address = _clean_str(row[4])  # Sử dụng Địa điểm kinh doanh làm địa chỉ sản xuất chính
        
        if not factory_name or not address:
            continue
            
        parsed_rows.append({
            "factory_name": factory_name,
            "address": address,
            "scope": _clean_str(row[6]),
            "standard": "GMP",  # Giá trị tiêu chuẩn mặc định cho cơ sở sản xuất có giấy phép ĐKKD
            "authority": "Bộ Y tế Việt Nam",
            "headquarters_address": _clean_str(row[2]),
            "location_name": _clean_str(row[3]),
            "responsible_pharmacist": _clean_str(row[5]),
            "certificate_license": _clean_str(row[7])
        })
        row_count += 1
        
    logger.info(f"Parsed {row_count} GMP licensed business facilities from Excel sheet.")
    return parsed_rows


async def sync_gmp_data(session: AsyncSession, category: str, parsed_rows: list[dict]) -> list[dict]:
    """Sync Excel rows with the DB and return newly added factories."""
    newly_added = []
    
    for data in parsed_rows:
        # Tìm kiếm cơ sở xem đã tồn tại trong database chưa (theo category, tên cơ sở và địa chỉ)
        stmt = select(GmpFactory).where(
            GmpFactory.category == category,
            GmpFactory.factory_name == data["factory_name"],
            GmpFactory.address == data["address"]
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing is None:
            # Phát hiện nhà máy hoàn toàn mới!
            factory = GmpFactory(
                category=category,
                factory_name=data["factory_name"],
                address=data["address"],
                scope=data["scope"],
                standard=data["standard"],
                authority=data["authority"],
                headquarters_address=data["headquarters_address"],
                location_name=data["location_name"],
                responsible_pharmacist=data["responsible_pharmacist"],
                certificate_license=data["certificate_license"]
            )
            session.add(factory)
            newly_added.append(data)
        else:
            # Cơ sở đã tồn tại -> Kiểm tra xem có bất kỳ trường thông tin nào thay đổi (vd cập nhật phạm vi, gia hạn)
            changed = False
            for field in [
                "scope", "standard", "authority", "headquarters_address", 
                "location_name", "responsible_pharmacist", "certificate_license"
            ]:
                new_val = data.get(field)
                if new_val is not None and getattr(existing, field) != new_val:
                    setattr(existing, field, new_val)
                    changed = True
            if changed:
                session.add(existing)
                
    await session.flush()
    return newly_added
