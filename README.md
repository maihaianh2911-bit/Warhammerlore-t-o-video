# Warhammer Lore Video Factory

Dây chuyền làm **video lore Warhammer 40K tiếng Đức** khổ dọc (1080 × 1920): hình phủ kín khung với chuyển động máy chậm, câu hook chữ đỏ ở hai giây đầu, phụ đề trắng chạy theo giọng `ww40k`. Chạy hoàn toàn trên GitHub, theo cách làm của repo `japan-video-factory`.

## Làm một video

1. **Issues → New issue → Video lore Warhammer 40K.** Đặt tên video sau `[40K]`, dán kịch bản tiếng Việt đã duyệt, kéo thả các hình muốn dùng → **Create**.
2. Không cần làm gì thêm. Claude dịch sang tiếng Đức và chia câu → máy tạo giọng đọc, nghe lại để căn phụ đề, gom hình → Claude xem và chọn hình cho từng ý, xem trước khung hình → máy dựng video → Claude kiểm tra lại từng cảnh. Mỗi bước báo trong phiếu.
3. Bình luận cuối có link **video**, **phụ đề** (SRT) và **nguồn hình** (dán vào mô tả video).
4. Muốn sửa: viết **một bình luận** gom hết yêu cầu, ví dụ "cảnh 3 đổi hình, câu 5 đọc sai tên". Không bắt đầu bình luận bằng 🤖 (đó là dấu của Claude).

Chỉ phiếu do chủ repo mở mới chạy. Kịch bản chủ repo gửi được xem là đã duyệt: Claude dịch sát, không cắt, không thêm. Phiếu trong repo Public có thể được người khác đọc.

## Hình

Máy **không tự tải được hình từ 40K Gallery** (trang chặn truy cập tự động). Hình đến từ ba nơi:

- **Hình kéo thả vào phiếu**: lưu tranh từ 40K Gallery bằng trình duyệt rồi kéo vào phiếu hoặc một bình luận, ghi tên họa sĩ nếu biết. 40K Gallery có [điều khoản sử dụng ảnh](https://40k.gallery/image-usage-terms/).
- **Thư viện `art/`**: hình dùng lại cho nhiều video, xem [`art/README.md`](art/README.md).
- **Wikimedia Commons**: ảnh miễn phí cho không khí (tinh vân, kiến trúc gothic, tranh chiến trận cổ). Ở đó gần như không có tranh 40K.

Ý nào không có hình phù hợp thì dùng đồ họa nền do máy vẽ; Claude ghi rõ trong bình luận cuối để bạn bổ sung hình nếu muốn.

## Nhãn trên phiếu (máy tự gắn)

| Nhãn | Ý nghĩa |
|---|---|
| `lore-plan` | Chờ Claude dịch và chia câu |
| `lore-voice` | Máy đang tạo giọng đọc và gom hình |
| `lore-pick` | Chờ Claude chọn hình |
| `lore-render` | Máy đang dựng video |
| `lore-check` | Chờ Claude kiểm tra từng cảnh |
| `lore-done` | Video xong (link ở bình luận cuối) |
| `lore-fix` | Bạn yêu cầu sửa, Claude sẽ làm |
| `lore-failed` | Máy gặp lỗi, Claude sẽ xem |

## File kết quả

Nhánh **`renders`**, thư mục `lore/<số phiếu>/`: `video.mp4`, `subtitles.srt`, `credits.md` (nguồn hình), `sheet.jpg` (ảnh các cảnh), `cover.jpg`, `voice/narration.mp3`, `voice/check.md` (đoạn cần nghe lại). Video của phiếu không hoạt động quá 14 ngày được dọn tự động, nên hãy tải về sớm.

## Cấu hình

- **Secrets** (Settings → Secrets and variables → Actions): `VN11_API_KEY` hoặc `VOICE` (giọng đọc VN11), `CLAUDE_TASK_URL` + `CLAUDE_TASK_TOKEN` (để GitHub gọi Claude ngay khi có việc).
- **Tác vụ Claude** cho repo này: một tác vụ Claude Code có API trigger, lời nhắc "Làm theo AGENT.md của repo". Thiếu tác vụ này thì phiếu dừng ở `lore-plan`, vì bước dịch và chọn hình là của Claude.
- Giọng: `ww40k`, mã `clone_611` trên VN11, đọc cả kịch bản trong một lượt. Kịch bản không đổi thì lần dựng lại dùng lại giọng cũ, không tốn thêm.

## Chạy tay (tab **Actions**)

| Workflow | Làm gì |
|---|---|
| **Video 40K** | Chạy lại một bước cho một phiếu: `prepare` (giọng + hình), `search` (tìm thêm hình), `render` (dựng) |
| **Gọi Claude ngay** | Cho Claude bắt đầu ngay; cũng dùng để thử hai secret `CLAUDE_TASK_*` |
| **Thử giọng VN11** | Kiểm tra khóa VN11 và giọng `clone_611` (không tạo audio) |
| **Dọn video cũ (nhánh renders)** | Dọn file của phiếu cũ (tự chạy mỗi tuần) |
| **Tạo nhãn** | Tạo các nhãn ở bảng trên |

Hướng dẫn cho Claude: [`AGENT.md`](AGENT.md).

## Chạy thử cục bộ

Cần Python 3.11+, FFmpeg có libass và libx264, phông DejaVu.

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 tests/smoke.py   # dựng một video giả, không gọi VN11 hay mạng
```
