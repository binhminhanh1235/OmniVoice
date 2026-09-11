# OmniVoice 🌍 + OmniVoice Studio

> **Bản tiếng Việt của README.** [English README](README.md)

OmniVoice là mô hình text-to-speech zero-shot hỗ trợ hơn 600 ngôn ngữ. Repository này giữ nền tảng của upstream [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice), đồng thời bổ sung **OmniVoice Studio** để biến TTS thành workflow production cho nội dung dài: project/resume, quality verification, Colab/Kaggle runtime, REST/SSE/MCP, stable tunnel, persistent startup cache và tooling vận hành.

**Bắt đầu nhanh:** [Hướng dẫn compact](docs/GUIDE-COMPACT.vi.md) | [Hướng dẫn đầy đủ](docs/GUIDE-FULL.vi.md) | [Production acceptance](docs/production-acceptance.md) | [Roadmap](docs/project-studio-roadmap.md) | [Notebooks](notebooks/README.md)

## Repository này bổ sung gì?

### OmniVoice Studio theo hướng project-first

Studio tổ chức nội dung theo:

```text
Project
  -> Section
      -> Beat
          -> Chunk
```

Mỗi project có script, metadata, trạng thái section/chunk, voice configuration, history, audio và output riêng. Nếu Colab/Kaggle bị ngắt, Studio có thể đọc checkpoint và tiếp tục phần chưa hoàn thành.

Các tính năng production đã có:

- Unified Workspace cho Script, Voice, Preview, Render, Review, Export, History, Quality, Advanced Settings và Storage.
- Resume theo section/chunk.
- Regenerate đúng chunk hoặc section lỗi, không cần render lại toàn bộ.
- Voice Library lưu voice-clone prompt để tái sử dụng.
- Voice Style Bank với `DEFAULT`, `WARM`, `SOFT`, `PRAYER`, `EMPHASIZE`.
- Text Doctor, Voice Doctor, Voice Stability, preview và section version history.
- Multi-project queue, pause/resume và project status.
- Quality preset `SAFE`, `BALANCED`, `FAST`.
- Language selector, ưu tiên English ở đầu danh sách.
- Tùy chọn đọc tiêu đề `###`.
- Bảo vệ các từ đầu câu nhạy như `Or`, `And`, `But` khi chunking.
- Local-first execution trên Colab/Kaggle để active generation chạy trên local SSD.

### AI-native server

Một process có thể cung cấp đồng thời:

```text
/ui                         Gradio Studio
/api/v1                     REST / OpenAPI
/api/v1/jobs/{id}/stream    SSE progress
/mcp                        Streamable HTTP MCP
/health                     Health
/docs                       OpenAPI docs
```

Đã có persistent GPU jobs, async generation, idempotency key, cooperative cancellation, durable events, SSE replay, MCP tools, Cloudflare named tunnel, bearer scopes cho API/MCP và Basic Auth tùy chọn cho UI.

## Hosted-runtime production stack

Colab/Kaggle production path hiện đã có:

- resolve exact OmniVoice commit SHA trước khi bootstrap;
- fingerprint exact model và ASR revision;
- persistent pip/wheel cache;
- kiểm tra wheel bằng filename, byte size, SHA-256 và ZIP integrity;
- persistent Hugging Face/model, Torch và Whisper cache;
- versioned namespace + invalidation khi revision/fingerprint không còn tương thích;
- từ chối cache interrupted, truncated hoặc corrupt;
- local SSD hot path cho active generation;
- `startup-cache-evidence.json` để đo cold/warm thật;
- **Lazy CPU ASR Startup** cho Studio, trong khi explicit accelerator ASR vẫn eager.

Không có con số “nhanh hơn X%” nào được xem là production evidence nếu chưa đo thật trên Colab/Kaggle.

## Trạng thái hiện tại

| Hạng mục | Trạng thái |
|---|---|
| OmniVoice core inference/training | Đã merge |
| Robust long-form Project Studio | Đã merge |
| Unified project-first workspace | Đã merge |
| Language selector, English-first | Đã merge |
| Fix phát âm đầu câu `Or` | Đã merge |
| Optional section-title narration | Đã merge |
| Job Manager + async generation | Đã merge |
| SSE | Đã merge |
| MCP | Đã merge |
| Stable named tunnel | Đã merge |
| API bearer auth/scopes | Đã merge |
| Benchmark framework | Đã merge |
| Persistent Colab/Kaggle startup cache | **MERGED / VERIFIED** |
| Lazy CPU ASR Startup | **MERGED / VERIFIED** |
| Target-only inference | Experimental, chưa bật production |
| Write APIs còn lại, agent adapters, control plane | Planned |

Chi tiết trạng thái nằm trong [docs/project-studio-roadmap.md](docs/project-studio-roadmap.md). Quy trình chốt hosted runtime nằm trong [docs/production-acceptance.md](docs/production-acceptance.md).

## Cài đặt

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

Khi gọi Python API trực tiếp có thể dùng `device_map="mps"`.

### Clone để phát triển

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

## Chạy Studio nhanh

### Gradio Project Studio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Temporary share URL:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

### Unified UI + REST + SSE + MCP

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Endpoints:

```text
http://127.0.0.1:8000/ui
http://127.0.0.1:8000/api/v1
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/mcp
http://127.0.0.1:8000/health
```

## Lazy CPU ASR Startup

Với `--asr-device cpu`, Studio không còn construct Whisper pipeline ngay lúc server/model startup.

```text
server startup
    -> ASR chưa construct
first transcription / verification
    -> init ASR đúng một lần dưới model-scoped lock
request sau
    -> reuse cùng pipeline
```

Nếu first load fail thì partial state không được publish; request sau có thể retry. Nếu bạn chủ động đặt `--asr-device cuda:1` hoặc accelerator khác thì eager behavior được giữ nguyên.

Startup log CPU bình thường:

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

First-use log:

```text
Initializing ASR on first use: ...
```

Kaggle dual-T4 thường dùng:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper verification
```

Đây là explicit accelerator ASR nên không lazy, đúng với acceptance contract.

## Hosted notebooks

| Môi trường | Notebook khuyến nghị | Mô hình chạy |
|---|---|---|
| Colab | `notebooks/OmniVoice_Project_Studio_Colab.ipynb` | local SSD + Drive persistence/cache boundary |
| Kaggle | `notebooks/OmniVoice_Project_Studio_Kaggle.ipynb` | `/kaggle/working` + startup-cache Dataset |
| Colab đơn giản | `notebooks/OmniVoice_Project_Studio_Colab_Gradio.ipynb` | temporary Gradio |
| Kaggle đơn giản | `notebooks/OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | local SSD + temporary Gradio |

Nguyên tắc: **render local, persist remote**. Không dùng Drive/FUSE hoặc `/kaggle/input` làm writable render hot path.

## Cold/warm startup cache acceptance

Notebook production ghi:

```text
startup-cache-evidence.json
```

Cần một mẫu cold thật và một mẫu warm thật trên **cùng exact `package_ref`**.

Sau đó chạy:

```bash
python scripts/hosted_cache_acceptance.py cold.json warm.json
```

PASS yêu cầu:

```text
cold.package_ref == warm.package_ref
warm.resource_fast_path == true
warm.wheel_fast_path == true
warm.bootstrap_seconds < cold.bootstrap_seconds
```

Notebook production có acceptance checkpoint để lưu `cold.json` / `warm.json` và tự gọi acceptance script exact-revision khi đủ hai mẫu.

Không gọi một session đã warm là “cold” chỉ để có số đẹp.

## Workflow production khuyến nghị

### 1. Voice

Dùng reference audio sạch, thường khoảng 3-10 giây. Nếu có transcript chính xác, nên nhập transcript để tránh cần ASR ở bước clone prompt.

Lưu voice vào Voice Library để session sau tái sử dụng prompt thay vì encode lại.

### 2. Script

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

- `#`, `##`, `###` mặc định là metadata;
- `[WARM]`, `[SOFT]`, `[EMPHASIZE]` là style metadata;
- bật **Read section titles (###)** khi muốn đọc tiêu đề;
- Studio bảo vệ leading conjunction khi merge/chunk an toàn.

### 3. Preview

Nghe opening, middle, ending trước full render. Kiểm tra voice identity, pronunciation, pacing, style và chất lượng reference.

### 4. Render

Khuyến nghị production mặc định:

```text
Voice variant: AUTO
Quality preset: BALANCED
Resume: ON
Language: chọn rõ nếu biết
```

### 5. Review và regenerate

Nếu một chunk fail verification hoặc nghe chưa tự nhiên, regenerate đúng chunk đó. Không render lại section/project đã đạt.

### 6. Export

Sau khi section đạt yêu cầu, merge/export output. Giữ project metadata và history để có thể quay lại chỉnh sau.

## Resume sau runtime restart

1. restore/mount persistent workspace;
2. mở lại cùng project;
3. chọn Generate/Resume;
4. Studio skip phần đã hoàn thành;
5. tiếp tục phần pending/failed.

Colab active workspace:

```text
/content/OmniVoiceStudio
```

Kaggle active workspace:

```text
/kaggle/working/OmniVoiceStudio
```

## Quality preset

| Preset | Khi dùng |
|---|---|
| `SAFE` | ưu tiên verification/recovery mạnh |
| `BALANCED` | production default khuyến nghị |
| `FAST` | ưu tiên throughput hơn |

Chỉ dùng Advanced Settings khi preset chưa đủ cho mục tiêu cụ thể.

## MCP và jobs

Các MCP tool chính:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Generation trả `job_id`, không giữ agent tool call mở xuyên suốt quá trình TTS.

## Stable hostname + private access

Ví dụ secrets:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Không commit secrets vào git, notebook hoặc project data.

## Benchmark và nguyên tắc optimization

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

Optimization chỉ được gọi production-ready khi có evidence thật. **Target-only inference** vẫn experimental và chưa được bật production cho tới khi có real GPU benchmark, equivalence, real voice-clone quality, ASR/pacing quality, perceptual A/B, long-form acceptance, memory evidence và no-regression cho training/API.

## Tài liệu

- [Hướng dẫn compact](docs/GUIDE-COMPACT.vi.md)
- [Hướng dẫn đầy đủ](docs/GUIDE-FULL.vi.md)
- [Production acceptance](docs/production-acceptance.md)
- [Roadmap](docs/project-studio-roadmap.md)
- [Project Studio](docs/project-studio.md)
- [MCP](docs/ai-native-mcp.md)
- [SSE](docs/ai-native-sse.md)
- [Stable tunnel](docs/stable-tunnel.md)
- [Hardware/quality presets](docs/hardware-quality-presets.md)
- [Kaggle workspace](docs/kaggle-local-workspace.md)
- [Notebooks](notebooks/README.md)

## Citation

```bibtex
@article{zhu2026omnivoice,
  title={OmniVoice: Towards Omnilingual Zero-Shot Text-to-Speech with Diffusion Language Models},
  author={Zhu, Han and Ye, Lingxuan and Kang, Wei and Yao, Zengwei and Guo, Liyong and Kuang, Fangjun and Han, Zhifeng and Zhuang, Weiji and Lin, Long and Povey, Daniel},
  journal={arXiv preprint arXiv:2604.00688},
  year={2026}
}
```

## License

Xem [LICENSE](LICENSE).