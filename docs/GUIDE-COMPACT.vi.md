# OmniVoice Studio - Hướng dẫn compact

Bản này dành cho lúc bạn muốn chạy OmniVoice Studio nhanh nhưng vẫn theo đúng production path hiện tại.

Nếu cần kiến trúc, recovery, API/MCP, tunnel, cache acceptance và troubleshooting chi tiết, xem [GUIDE-FULL.vi.md](GUIDE-FULL.vi.md). Quy trình đo cold/warm chính thức nằm ở [production-acceptance.md](production-acceptance.md).

## 1. Chọn cách chạy

| Nhu cầu | Cách nên dùng |
|---|---|
| Local có GPU | `omnivoice-project-studio` |
| Colab production | `notebooks/OmniVoice_Project_Studio_Colab.ipynb` |
| Kaggle production | `notebooks/OmniVoice_Project_Studio_Kaggle.ipynb` |
| Chỉ cần Gradio đơn giản | notebook `*_Gradio.ipynb` |
| Cần UI + REST + SSE + MCP | `omnivoice-studio serve` |

## 2. Trạng thái production quan trọng

Hai optimization hosted-runtime đã ở trạng thái **MERGED / VERIFIED**:

- Persistent Colab/Kaggle Startup Cache.
- Lazy CPU ASR Startup.

`Target-only inference` vẫn **Experimental** và chưa phải production path.

## 3. Cài đặt local

### NVIDIA CUDA 12.8

```bash
python -m venv .venv
source .venv/bin/activate

pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128

pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Windows activate:

```powershell
.venv\Scripts\activate
```

### Apple Silicon

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch==2.8.0 torchaudio==2.8.0
pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

## 4. Chạy Studio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Temporary public URL:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

Unified server:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Endpoints:

```text
/ui
/api/v1
/docs
/mcp
/health
```

## 5. Workflow production

### Voice

1. Dùng reference audio sạch, thường 3-10 giây.
2. Nhập transcript chính xác nếu có.
3. Chọn language.
4. Save Voice.
5. Tái sử dụng prompt ở session sau.

Nếu có transcript chính xác, nhập luôn để tránh phải ASR reference audio ở bước tạo clone prompt.

### Script

```markdown
# Video title

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:30
[EMPHASIZE] Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

Quy tắc:

- `#`, `##`, `###` mặc định là metadata.
- `[WARM]`, `[SOFT]`, `[EMPHASIZE]` là style metadata.
- Bật **Read section titles (###)** nếu muốn đọc tiêu đề.
- Studio có safeguard cho các leading conjunction như `Or`, `And`, `But`.

### Preview

Nghe opening, middle và ending trước full render. Kiểm tra voice identity, pronunciation, pacing, style và reference quality.

### Render

Khuyến nghị:

```text
Voice variant: AUTO
Quality preset: BALANCED
Resume: ON
Language: chọn rõ nếu biết
```

### Review

Nếu một chunk lỗi hoặc nghe chưa tự nhiên:

1. chọn chunk;
2. regenerate đúng chunk đó;
3. không render lại phần đã verified.

### Export

Khi section đạt yêu cầu, merge/export project. Giữ history để sửa lại sau nếu cần.

## 6. Resume sau Colab/Kaggle restart

Không tạo project mới.

1. restore/mount persistent workspace;
2. mở cùng project;
3. Generate/Resume;
4. Studio skip phần đã hoàn thành;
5. tiếp tục pending/failed work.

## 7. Colab production

Notebook:

```text
notebooks/OmniVoice_Project_Studio_Colab.ipynb
```

Kiến trúc:

```text
Google Drive
    persistent workspace + startup cache
          |
          | restore / sync
          v
/content/OmniVoiceStudio
    active local-SSD render workspace
```

Không dùng Drive FUSE làm render hot path.

### Cold/warm acceptance

Notebook tạo `startup-cache-evidence.json` và có acceptance checkpoint.

- Run cold thật: đặt `ACCEPTANCE_SAMPLE = "cold"` rồi lưu evidence.
- Restart runtime với cache đã persist.
- Run warm thật: đặt `ACCEPTANCE_SAMPLE = "warm"`.
- Khi đủ hai file, notebook tự chạy exact-revision acceptance script.

PASS yêu cầu:

```text
same package_ref
warm.resource_fast_path == true
warm.wheel_fast_path == true
warm.bootstrap_seconds < cold.bootstrap_seconds
```

## 8. Kaggle production

Notebook:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

Workspace:

```text
/kaggle/working/OmniVoiceStudio
```

Startup cache export:

```text
/kaggle/working/OmniVoiceStartupCache
```

Sau cold run, save/version thư mục cache thành Kaggle Dataset `omnivoice-startup-cache`. Session sau attach tại:

```text
/kaggle/input/omnivoice-startup-cache
```

Không dùng `/kaggle/input` làm writable workspace.

Nếu dual-T4:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper ASR verification
```

Notebook sẽ copy cold acceptance evidence từ attached Dataset sang writable export tree trước khi ghi warm evidence.

## 9. Lazy CPU ASR Startup

Với:

```text
--asr-device cpu
```

Studio startup không construct Whisper pipeline ngay.

Expected startup log:

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

Khi có first real ASR request:

```text
Initializing ASR on first use: ... device=cpu
```

Sau đó cùng pipeline được reuse.

Nếu first load fail, partial state không được publish; request sau có thể retry.

Nếu explicit accelerator, ví dụ:

```text
--asr-device cuda:1
```

ASR vẫn eager. Đây là behavior cố ý, không phải regression.

## 10. Quality preset

| Preset | Khi dùng |
|---|---|
| `SAFE` | ưu tiên verification/recovery mạnh |
| `BALANCED` | production default |
| `FAST` | ưu tiên throughput hơn |

Chỉ dùng Advanced Settings khi preset chưa đủ.

## 11. MCP tools

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Generation trả `job_id`, không giữ tool call mở cho tới khi render xong.

## 12. Stable public hostname

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Không lưu secret trong git/notebook/project data.

## 13. Benchmark trước optimization

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

Không gọi một optimization là production-ready chỉ dựa trên giả định. Với hosted startup cache, phải có cold/warm evidence thật. Với target-only inference, vẫn cần real GPU benchmark + quality acceptance riêng.

## 14. Production checklist ngắn

```text
[ ] Exact source revision resolved
[ ] Model/ASR revisions resolved
[ ] Active workspace nằm trên local SSD
[ ] Project persistence đã cấu hình
[ ] Voice preview đạt
[ ] BALANCED/SAFE preset phù hợp
[ ] Resume hoạt động
[ ] Failed chunk regenerate đúng scope
[ ] Export đạt
[ ] Nếu đo cache: cold/warm cùng package_ref
[ ] Nếu CPU ASR: startup deferred và first-use init được quan sát
[ ] Không có secret trong artifact
```

## 15. Đọc tiếp

- [Hướng dẫn đầy đủ](GUIDE-FULL.vi.md)
- [Production acceptance](production-acceptance.md)
- [Roadmap](project-studio-roadmap.md)
- [Notebooks](../notebooks/README.md)
- [MCP](ai-native-mcp.md)
- [Stable tunnel](stable-tunnel.md)