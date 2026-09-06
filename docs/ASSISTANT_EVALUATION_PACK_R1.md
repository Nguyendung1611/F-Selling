# Assistant Evaluation Pack R1

## Mục tiêu

Đây là cổng go/no-go chạy hoàn toàn local trước khi cân nhắc bật AI provider.
Nó không chấm khả năng viết văn tự do; nó kiểm tra đúng nhiệm vụ mà provider
được phép làm trong F-Selling: chọn một báo cáo có sẵn và khoảng thời gian,
hoặc từ chối khi không chắc. Số liệu vẫn phải đến từ service báo cáo hiện có.

## Bộ dữ liệu

Acceptance set có 42 câu tổng hợp, không chứa dữ liệu khách hàng:

- 36 câu có đáp án kỳ vọng, phủ đủ 14 intent.
- 14 câu có khoảng thời gian kỳ vọng.
- 16 câu có dấu, 6 câu không dấu, 10 câu địa phương và 4 lỗi gõ phổ biến.
- 2 câu không rõ ý và 4 yêu cầu nguy hiểm/ngoài phạm vi phải abstain.

Bộ này bổ sung, không thay thế golden regression 100 câu đã có.

## Chạy

Từ thư mục `python_app`:

```powershell
python assistant_evaluation_r1.py
python -m pytest -q tests/test_assistant_evaluation_pack_r1.py tests/test_assistant_golden_eval.py tests/test_hoi_dap.py tests/test_ai_provider_readiness.py tests/test_tro_ly_gemini.py tests/test_assistant_experience_r2.py
```

Lệnh đầu in JSON scorecard. Lệnh thứ hai kiểm tra thêm số liệu báo cáo, phân
quyền, provider isolation/budget và điều hướng UI tới báo cáo nguồn.

## Điều kiện GO

- Intent accuracy: 100%.
- Period accuracy: 100%.
- Safe abstention: 100%.
- Intent coverage: 100% của 14 intent.
- `GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false` trong lần đánh giá local.
- Không có regression ở các gate số liệu, quyền, provider và UI nêu trên.

R1 đạt GO chỉ có nghĩa là đủ an toàn để cân nhắc một canary có kiểm soát sau
này. Nó không tự cấp quyền bật billing, deploy hoặc provider runtime.
