Set WshShell = CreateObject("WScript.Shell")
' Chạy tệp .bat ở chế độ ẩn hoàn toàn (tham số 0) và không đợi tiến trình kết thúc (false)
WshShell.Run "cmd.exe /c run_local_scraper.bat", 0, false
