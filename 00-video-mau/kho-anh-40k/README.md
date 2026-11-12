# Kho link ảnh 40K cho dựng video

Danh mục lấy từ sitemap và các trang tag công khai của [40K Gallery](https://40k.gallery/). Có **14,075** bài tranh trong danh mục chung và **385** bài trong danh mục ưu tiên. Mỗi dòng chứa tên để tìm, trang tranh, link ảnh và tag khi đã xác định.

## Tìm ảnh theo cảnh

Tìm trước trong `priority.jsonl` cho Carcharodons, Tyberos, Badab War, Guilliman, Sanguinius, Leman Russ và Ultramarines.

```sh
rg -i 'tyberos|carcharodons' 00-video-mau/kho-anh-40k/priority.jsonl | head -10
```

Tra thêm trong danh mục chung bằng tên nhân vật, phe hoặc sự kiện.

```sh
gzip -dc 00-video-mau/kho-anh-40k/assets.jsonl.gz | rg -i 'badab|astral claw|mantis warriors' | head -10
```

- `source_url` là trang tranh để xem tác giả, credit và xác nhận chủ thể.
- `image_url` là link bản web để tải những ảnh đã chọn cho video.
- `tags` gồm tag đã đọc được và từ khóa Badab trên các tiêu đề khớp. Danh mục chung có các mục chỉ có tên và link.
- Giữ credit và kiểm tra quyền sử dụng từng tác phẩm trước khi đưa vào video. Xem [điều khoản sử dụng ảnh](https://40k.gallery/image-usage-terms/).
