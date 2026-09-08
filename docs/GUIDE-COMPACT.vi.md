# OmniVoice Studio - Hướng dẫn compact

Bản này dành cho lúc bạn muốn chạy OmniVoice Studio nhanh, không cần đọc toàn bộ kiến trúc.

Nếu cần mọi chi tiết về production, recovery, API/MCP, tunnel và benchmark, xem [GUIDE-FULL.vi.md](GUIDE-FULL.vi.md).

## 1. Chọn cách chạy

| Nhu cầu | Cách nên dùng |
|---|---|
| Local có GPU | `omnivoice-project-studio` |
| Colab | `notebooks/OmniVoice_Project_Studio_Colab.ipynb` |
| Kaggle | `notebooks/OmniVoice_Project_Studio_Kaggle.ipynb` |
| Chỉ cần Gradio đơn giản | notebook `*_Gradio.ipynb` |
| Cần REST/SSE/MCP | `omnivoice-studio serve` |

## 2. Cài đặt local

Không bắt buộc dùng `uv`.

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

## 3. Chạy Studio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Nếu cần temporary public Gradio URL:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

## 4. Workflow production

### Voice

1. Upload reference audio sạch khoảng 3-10 giây.
2. Nhập transcript chính xác nếu có.
3. Chọn language.
4. Save Voice.
5. Có thể lưu nhiều variant như `DEFAULT`, `WARM`, `SOFT`, `PRAYER`.

### Script

Ví dụ:

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
- Bật **Read section titles (###)** nếu muốn đọc tiêu đề section.
- Studio có safeguard để tránh tách `Or`, `And`, `But` thành chunk thiếu ngữ cảnh khi có thể merge an toàn.

### Preview

Nghe preview trước khi render dài.

Kiểm tra:

- voice có đúng người/đúng chất không;
- tốc độ nói;
- pronunciation;
- style;
- volume/noise của reference.

### Render

Khuyến nghị:

```text
Voice variant: AUTO
Language: English hoặc ngôn ngữ cần dùng
Quality preset: BALANCED
Resume: ON
```

Có thể render toàn bộ hoặc chỉ chọn section.

### Review

Nếu một chunk lỗi:

1. chọn chunk;
2. regenerate đúng chunk đó;
3. không render lại phần đã verified.

### Export

Khi các section đạt yêu cầu, merge/export project.

## 5. Resume sau khi Colab/Kaggle restart

Không tạo project mới.

Làm lại:

1. restore/mount persistent workspace;
2. mở cùng project;
3. Generate/Resume;
4. Studio skip phần đã verified;
5. tiếp tục phần pending.

Active generation nên chạy trên local SSD.

## 6. Kaggle

Workspace chạy:

```text
/kaggle/working/OmniVoiceStudio
```

Không dùng `/kaggle/input` làm writable render workspace.

Nếu có dual-T4:

```text
cuda:0 -> OmniVoice
cuda:1 -> Whisper verification khi phù hợp
```

## 7. Colab

Nên dùng mô hình:

```text
Google Drive / persistent storage
           |
           | restore + sync
           v
/content/OmniVoiceStudio
           |
           v
      active generation
```

Không nên để hàng nghìn file checkpoint/WAV trong render hot path đi trực tiếp qua Drive FUSE.

## 8. Quality preset

| Preset | Khi dùng |
|---|---|
| `SAFE` | cần quality/retry mạnh |
| `BALANCED` | production mặc định |
| `FAST` | ưu tiên tốc độ |

Chỉ vào Advanced Settings khi preset chưa đủ.

## 9. Unified REST/SSE/MCP server

Chạy:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Endpoints:

```text
http://127.0.0.1:8000/ui
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/api/v1
http://127.0.0.1:8000/mcp
http://127.0.0.1:8000/health
```

## 10. MCP tools

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Generation trả về `job_id`, không giữ tool call mở cho tới khi TTS xong.

## 11. Public stable hostname

Thiết lập secrets:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"

export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Chạy:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

Không lưu secret trong git/notebook/project.

## 12. Benchmark trước khi bật optimization

```bash
omnivoice-benchmark \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

Target-only inference vẫn experimental. Không bật production chỉ vì unit projection test pass.

## 13. Khi có lỗi

### Out of memory

- giảm workload;
- dùng `BALANCED` hoặc `FAST`;
- để Whisper trên CPU hoặc GPU thứ hai;
- restart runtime nếu CUDA allocator bị phân mảnh nặng.

### Reference voice không ổn

- dùng audio 3-10 giây;
- giảm noise;
- transcript phải đúng;
- thử Voice Doctor;
- dùng reference cùng ngôn ngữ nếu muốn giảm accent transfer.

### Render bị ngắt

Không xóa project. Dùng Resume.

### Một câu đọc sai

Regenerate đúng chunk. Nếu là pronunciation đặc biệt, dùng pronunciation override hoặc chỉnh script.

### MCP/API không vào được

Kiểm tra:

- `/health`;
- bearer token;
- scopes;
- public URL;
- MCP host/origin allowlist;
- tunnel đang kết nối.

## 14. Đọc thêm

- [README tiếng Việt](../README.vi.md)
- [Hướng dẫn đầy đủ](GUIDE-FULL.vi.md)
- [Roadmap](project-studio-roadmap.md)
- [Project Studio](project-studio.md)
- [MCP](ai-native-mcp.md)
- [SSE](ai-native-sse.md)
- [Stable tunnel](stable-tunnel.md)
- [Notebooks](../notebooks/README.md)
