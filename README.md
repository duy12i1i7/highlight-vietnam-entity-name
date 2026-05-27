# PDF Entity Highlighter

Ứng dụng desktop và CLI để tự động bôi màu tên người, địa danh và các thực thể khác trong file PDF có text layer.

Pipeline:

```text
PDF -> trích text từng trang -> NER engine -> strict/confirmed validation -> tìm lại vị trí trong PDF -> thêm highlight annotation -> PDF mới
```

## Cài đặt

Khuyến nghị dùng Python 3.12 vì một số thư viện NLP tiếng Việt có thể chưa hỗ trợ tốt Python 3.14.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[vi,vncorenlp,gui]"
```

Trên Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[vi,vncorenlp,gui]"
```

## Chạy ứng dụng desktop

```bash
pdf-entity-highlighter-gui
```

Ứng dụng cho phép:

- Chọn một hoặc nhiều file PDF.
- Kéo thả PDF vào danh sách.
- Chọn thư mục lưu kết quả khi xử lý nhiều file.
- Chọn đường dẫn file PDF đầu ra khi xử lý một file.
- Chọn loại entity cần bôi màu: `PER`, `LOC`, `ORG`, `MISC`.
- Chọn engine NER: VnCoreNLP hoặc Underthesea.
- Bật strict validation hoặc dùng confirmed-only list khi không chấp nhận false positive.

## Chạy bằng CLI

Mặc định chương trình highlight `PER` và `LOC`.

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf
```

Engine mặc định là `underthesea`. Dùng VnCoreNLP để có NER tiếng Việt tốt hơn:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf \
  --engine vncorenlp \
  --download-vncorenlp \
  --strict
```

VnCoreNLP cần Java 1.8+. Trên macOS có thể cài bằng:

```bash
brew install openjdk@17
```

Chế độ ít false positive hơn:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf --strict
```

Khi không chấp nhận false positive, dùng danh sách đã duyệt và bỏ qua NER:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf \
  --confirmed-only confirmed-entities.txt \
  --labels PER LOC ORG MISC
```

Định dạng `confirmed-entities.txt`:

```text
PER,Nguyễn Văn A
LOC,Hà Nội
ORG,Công ty ABC
```

Highlight thêm tổ chức:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf --labels PER LOC ORG
```

Ghi báo cáo JSON:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf --report report.json
```

Đổi màu:

```bash
pdf-entity-highlight input.pdf output-highlighted.pdf \
  --color PER=#ffd54f \
  --color LOC=#81c784
```

## Nhãn hỗ trợ

Các engine NER thường trả về các nhãn:

- `PER`: tên người
- `LOC`: địa danh
- `ORG`: tổ chức
- `MISC`: thực thể khác

## Lưu ý

- Công cụ này xử lý tốt PDF có thể copy được chữ.
- PDF scan dạng ảnh cần OCR trước, ví dụ bằng OCRmyPDF, rồi mới chạy highlighter.
- File gốc không bị sửa; chương trình lưu ra file PDF mới.
- Không có NER tự động nào đảm bảo tuyệt đối không false positive. Nếu yêu cầu là không bôi sai, hãy dùng `--confirmed-only` với danh sách thực thể đã được kiểm tra.

## Đóng gói thành ứng dụng

Cài dependency build:

```bash
python -m pip install -e ".[vi,vncorenlp,gui,build]"
```

Build app cho hệ điều hành hiện tại:

```bash
python scripts/build_app.py
```

Kết quả nằm trong thư mục `dist/`.

Lưu ý: PyInstaller cần build trên đúng hệ điều hành đích. Muốn có đủ bản Windows, macOS và Ubuntu, dùng workflow GitHub Actions tại `.github/workflows/build-app.yml`; workflow này build artifact riêng cho từng OS.

## Kiểm thử

```bash
python -m pip install -e ".[vi,vncorenlp,gui,dev]"
pytest
```
