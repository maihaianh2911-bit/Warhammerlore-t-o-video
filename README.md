# Warhammer Lore Video Factory

Tự dựng video lore Warhammer 40K dọc từ lời thoại đã duyệt. Mỗi lượt xuất MP4, phụ đề SRT, ảnh bìa, bảng cảnh và danh sách nguồn hình.

## Gửi kịch bản

Kịch bản chủ repo tự gửi để dựng video 40K được xem là đã duyệt và đưa nguyên văn vào Issue. Bản thảo do trợ lý soạn cần chủ repo duyệt trước.

1. Chủ repo mở Issue theo mẫu **Video lore Warhammer 40K**. Đặt tiêu đề dạng `[40K] Tên video` và dán phần lời đọc tiếng Việt đã duyệt.
2. GitHub Actions dịch tiêu đề và lời thoại sang tiếng Đức, rồi tạo giọng, chia mốc phụ đề, chọn hình và xuất video 1080 × 1920. Bản tiếng Đức đi kèm video dưới dạng `title-de.txt` và `script-de.txt`. Khi hoàn tất, Issue nhận liên kết tải.
3. Để dựng lại sau khi sửa nội dung Issue, vào **Actions → Dựng video 40K → Run workflow** rồi điền số Issue. Để trống ô này nếu muốn chạy bản kiểm tra.

Issue trong repo Public có thể được người khác đọc. Đường dẫn tải trong Issue dẫn tới tệp của lượt chạy, lưu 14 ngày.

## Giọng và cách dựng

Repo 40K mặc định dùng tiếng Đức và giọng `ww40k` đã lưu trên VN11 với mã `clone_611`. Mô hình Qwen3 dịch ngay trên máy chạy GitHub Actions, không cần khóa dịch riêng. Nếu lời thoại đã viết bằng tiếng Đức, bước này giữ nguyên lời thoại. Repo nhận khóa VN11 từ secret `VN11_API_KEY` hoặc `VOICE`. Đặt biến `NARRATION_LANGUAGE` thành `en` hoặc `vi` nếu đã có sẵn kịch bản ở ngôn ngữ đó.

VN11 đọc cả kịch bản trong một lượt để giữ nhịp. Whisper nghe lại để căn phụ đề theo lời đọc. Gói xuất có thêm `narration.mp3` và `voice-check.json` ghi những đoạn cần nghe lại, kể cả tên riêng mà Whisper có thể nghe nhầm. Nếu Whisper nghe được quá ít lời trùng với kịch bản, lượt dựng dừng để kiểm tra cấu hình giọng.

Khi chạy bản thử trong Actions, eSpeak NG đọc bản dịch tiếng Đức của mẫu. Nếu đã có khóa VN11, lượt thử cũng kiểm tra xem tài khoản có giọng đã chọn. Lượt kiểm tra giọng chỉ đọc danh sách, chưa tạo audio. Khi chạy cục bộ, cũng có thể chọn ElevenLabs trực tiếp với `--voice elevenlabs` và hai biến môi trường `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.

Phong cách dựng theo video tham chiếu do chủ kênh gửi. Cảnh mở khoảng hai giây, đặt câu hook chữ đỏ đậm nghiêng giữa khung. Khi có nhiều hình phù hợp, cảnh mở dùng tranh ghép rồi lia ngang qua dải tranh. Sau đó dùng tranh phủ kín khung dọc, xen kẽ đẩy máy, kéo ra và lia nhẹ. Cảnh đổi theo lời đọc, chuyển hình trong vài khung hình và giữ chủ thể qua các câu tiếp nối. Phụ đề trắng đậm viền đen chia thành từng cụm, tối đa hai dòng. Video có âm nền tổng hợp nhỏ dưới lời đọc.

## Nguồn hình

`art/catalog.json` chứa tên nhân vật, phe và sự kiện để tìm hình theo từng cảnh. `credits.md` ghi lại các trang tham khảo, bao gồm trang thẻ của 40K Gallery khi có. Muốn dùng một ảnh trong video, thêm vào `assets` ảnh bạn có quyền sử dụng, kèm tên họa sĩ và nguồn. 40K Gallery có thông tin họa sĩ và [điều khoản sử dụng ảnh](https://40k.gallery/image-usage-terms/).

Mỗi ảnh có `title`, `artist`, `source` (trang ghi công), `rights`, `keywords` và một trong `url` (ảnh HTTPS) hoặc `file` (đường dẫn tương đối trong `art/`). Đặt `focal: [0.5, 0.42]` để chỉnh vị trí cắt khi ảnh phủ kín màn hình. Hai giá trị từ 0 đến 1 dịch khung cắt theo chiều ngang và chiều dọc. `require_any` là nhóm từ khóa bổ sung cho thời kỳ hoặc bối cảnh. Chẳng hạn, ảnh Guilliman thời Horus Heresy có thể ghép `keywords: ["guilliman"]` với `require_any: ["horus heresy", "đại phản loạn"]`.

Kho ảnh khởi đầu đang trống. Cảnh thiếu ảnh phù hợp sẽ dùng đồ họa quỹ đạo, kiến trúc hoặc khe nứt được tạo trong lúc dựng. Có thể kiểm tra hình đã dùng và liên kết gợi ý theo từng cảnh trong `credits.md` và `scenes.json`.

## Chạy thử cục bộ

Cần Python 3.11+, FFmpeg có libass và libx264, eSpeak NG, phông DejaVu và Pillow.

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m factory.render --title 'Which portrait belongs in the opening?' \
  --script examples/smoke.txt --language en --voice espeak --size preview --out out/demo
```

Tệp mẫu chỉ dùng để kiểm tra việc đổi cảnh, giọng và phụ đề. Khi chạy thử trên máy có FFmpeg hỗ trợ libflite, có thể dùng `--voice flite` cho mẫu tiếng Anh.

Để chạy VN11 cục bộ, cài thêm `requirements-voice.txt`, đặt `VN11_API_KEY` và chạy lệnh dựng với `--voice vn11`. Có thể đặt `VN11_VOICE_ID` cục bộ để dùng mã giọng khác.
