# Thư viện hình

Hình dùng lại cho nhiều video (nhân vật, phe, tàu chiến hay xuất hiện). Tải hình lên thư mục này: **Add file → Upload files**. Chỉ đưa vào hình bạn có quyền dùng.

Ghi mỗi hình một dòng trong `index.json` để Claude biết hình vẽ gì và ghi công đúng:

```json
[{"file": "guilliman-throne.jpg", "subject": "Roboute Guilliman, thời Indomitus", "artist": "Tên họa sĩ", "source": "https://40k.gallery/…"}]
```

Trong `picks.json`, hình ở đây có `src` là `art/<tên tệp>`. Hình tối thiểu 320 px mỗi cạnh, tối đa 16 MB.
