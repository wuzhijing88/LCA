# 性能基线

OCR 基准由 `tools/benchmark_ocr_runtime.py` 生成。批准后的结果保存为 `benchmarks/ocr/baseline.json`，PR 或发布构建使用以下命令比较：

```powershell
.\venv\Scripts\python.exe tools\compare_benchmark_result.py `
  --baseline benchmarks\ocr\baseline.json `
  --result benchmarks\output\ocr-result.json `
  --tolerance-percent 10
```

更新 baseline 必须说明硬件、Windows 版本、DirectML 驱动、模型哈希和变更原因。`benchmarks/output/` 是本地结果，不入库。
