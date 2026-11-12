# Warhammer Lore Video Factory

Tự dựng video lore Warhammer 40K dọc từ lời thoại đã duyệt. Mỗi lượt xuất MP4, phụ đề SRT, ảnh bìa, bảng cảnh và danh sách nguồn hình.

## Gửi kịch bản

1. Chủ repo mở Issue theo mẫu **Video lore Warhammer 40K**. Đặt tiêu đề dạng `[40K] Tên video` và dán phần lời đọc đã duyệt.
2. GitHub Actions tạo giọng, chia mốc phụ đề, chọn hình theo lời đọc và xuất video 1080 × 1920. Khi hoàn tất, Issue nhận liên kết tải.
3. Để dựng lại sau khi sửa nội dung Issue, vào **Actions → Dựng video 40K → Run workflow** rồi điền số Issue. Để trống ô này nếu muốn chạy bản kiểm tra.

Issue trong repo Public có thể được người khác đọc. Đường dẫn tải trong Issue dẫn tới tệp của lượt chạy, lưu 14 ngày.

## Giọng và cách dựng

Bản đầu mặc định đọc tiếng Việt. Có thể đổi biến Actions `NARRATION_LANGUAGE` sang `en` cho tiếng Anh. Đặt secret `ELEVENLABS_API_KEY` và biến `ELEVENLABS_VOICE_ID` trong Settings → Secrets and variables → Actions để dùng giọng ElevenLabs Flash v2.5. API tạo một lượt đọc liên tục và trả mốc từng ký tự để đặt phụ đề. Khi chưa có cấu hình ElevenLabs, workflow dùng eSpeak NG và ước lượng mốc phụ đề. Giọng eSpeak phù hợp để kiểm tra luồng dựng.

Hình chuyển theo lời đọc, có chuyển động nhẹ, nền trầm và phụ đề ở vùng an toàn của video dọc. Tiêu đề chỉ xuất hiện ở cảnh mở. Video có âm nền tổng hợp nhỏ dưới lời đọc.

## Nguồn hình

`art/catalog.json` chứa tên nhân vật, phe và sự kiện để tìm hình theo từng cảnh. `credits.md` ghi lại các trang tham khảo, bao gồm trang thẻ của 40K Gallery khi có. Muốn dùng một ảnh trong video, thêm vào `assets` ảnh bạn có quyền sử dụng, kèm tên họa sĩ và nguồn. 40K Gallery có thông tin họa sĩ và [điều khoản sử dụng ảnh](https://40k.gallery/image-usage-terms/).

Mỗi ảnh có `title`, `artist`, `source` (trang ghi công), `rights`, `keywords` và một trong `url` (ảnh HTTPS) hoặc `file` (đường dẫn tương đối trong `art/`). `require_any` là nhóm từ khóa bổ sung cho thời kỳ hoặc bối cảnh. Chẳng hạn, ảnh Guilliman thời Horus Heresy có thể ghép `keywords: ["guilliman"]` với `require_any: ["horus heresy", "đại phản loạn"]`.

Kho ảnh khởi đầu đang trống. Cảnh thiếu ảnh phù hợp sẽ dùng đồ họa quỹ đạo, kiến trúc hoặc khe nứt được tạo trong lúc dựng. Có thể kiểm tra hình đã dùng và liên kết gợi ý theo từng cảnh trong `credits.md` và `scenes.json`.

## Chạy thử cục bộ

Cần Python 3.11+, FFmpeg có libass và libx264, eSpeak NG, phông DejaVu và Pillow.

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m factory.render --title 'Warhammer 40,000' \
  --script examples/smoke.txt --language en --voice espeak --size preview --out out/demo
```

Tệp mẫu chỉ dùng để kiểm tra việc đổi cảnh, giọng và phụ đề. Khi chạy thử trên máy có FFmpeg hỗ trợ libflite, có thể dùng `--voice flite` cho mẫu tiếng Anh.
