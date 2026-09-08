# OmniVoice 🌍 + OmniVoice Studio

> **Bản tiếng Việt của README.** [English README](README.md)

OmniVoice là mô hình text-to-speech zero-shot hỗ trợ hơn 600 ngôn ngữ. Repository này giữ nguyên nền tảng của upstream [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice), đồng thời bổ sung **OmniVoice Studio** để biến mô hình TTS thành một workflow production cho nội dung dài: quản lý project, resume, kiểm tra chất lượng, chạy Colab/Kaggle, REST/SSE/MCP, stable tunnel và các công cụ vận hành.

**Bắt đầu nhanh:** [Hướng dẫn compact](docs/GUIDE-COMPACT.vi.md) | [Hướng dẫn đầy đủ](docs/GUIDE-FULL.vi.md) | [Roadmap](docs/project-studio-roadmap.md) | [Notebooks](notebooks/README.md)

## Repository này có gì thêm?

### 1. OmniVoice Studio theo hướng project-first

Thay vì chỉ nhập một câu rồi sinh một file WAV, Studio tổ chức nội dung theo:

```text
Project
  -> Section
      -> Beat
          -> Chunk
```

Mỗi project có script, metadata, trạng thái section/chunk, cấu hình voice, lịch sử, file audio và output riêng. Nếu runtime Colab/Kaggle bị ngắt, Studio có thể đọc checkpoint và tiếp tục phần chưa hoàn thành.

Các tính năng production đã có:

- Unified Workspace cho Script, Voice, Preview, Render, Review và Export.
- Resume theo section/chunk.
- Regenerate đúng chunk lỗi, không cần render lại toàn bộ.
- Voice Library lưu lại voice-clone prompt để tái sử dụng.
- Voice Style Bank với các variant như `DEFAULT`, `WARM`, `SOFT`, `PRAYER`, `EMPHASIZE`.
- Text Doctor, Voice Doctor, Voice Stability Score.
- Preview trước khi render full project.
- Section Version History.
- Multi-project queue và trạng thái project.
- Quality preset `SAFE`, `BALANCED`, `FAST`.
- Advanced Settings theo từng project.
- Language selector, ưu tiên English ở đầu danh sách.
- Tùy chọn đọc tiêu đề `###`.
- Bảo vệ trường hợp từ đầu câu như `Or`, `And`, `But` bị tách chunk gây phát âm thiếu ngữ cảnh.

### 2. AI-native server

Một process có thể cung cấp đồng thời:

```text
/ui                         Gradio Studio
/api/v1                     REST / OpenAPI
/api/v1/jobs/{id}/stream    SSE progress
/mcp                        Streamable HTTP MCP
/health                     Health check
/docs                       OpenAPI docs
```

Đã có:

- Job Manager chạy tác vụ GPU theo hàng đợi;
- job state được lưu persistent;
- async project generation;
- idempotency key;
- cooperative cancellation;
- SSE progress và replay sau reconnect;
- MCP tools;
- Cloudflare named tunnel cho hostname ổn định;
- bearer token + scope cho API/MCP;
- Basic Auth tùy chọn cho Gradio UI.

### 3. Tối ưu cho Colab/Kaggle

Mục tiêu là **render trên local SSD**, không render trực tiếp qua Google Drive/FUSE hoặc remote storage.

Kaggle mặc định ưu tiên:

```text
/kaggle/working/OmniVoiceStudio
```

Colab và Kaggle có notebook riêng. Với Kaggle dual-T4, OmniVoice có thể dùng GPU chính và Whisper verification có thể dùng GPU thứ hai khi phù hợp.

Persistent dependency/model/Whisper cache đang được tích hợp riêng và chỉ được xem là production sau khi merge vào `master`.

## Trạng thái hiện tại

| Hạng mục | Trạng thái |
|---|---|
| OmniVoice core inference/training | Đã merge |
| Robust long-form Project Studio | Đã merge |
| Unified project-first workspace | Đã merge |
| Language selector, English-first | Đã merge |
| Fix phát âm đầu câu "Or" | Đã merge |
| Optional section-title narration | Đã merge |
| Job Manager + async generation | Đã merge |
| SSE | Đã merge |
| MCP | Đã merge |
| Stable named tunnel | Đã merge |
| API bearer auth/scopes | Đã merge |
| Benchmark framework | Đã merge |
| Persistent Colab/Kaggle cache | Đang review |
| Target-only inference | Experimental |
| Write APIs còn lại, agent adapters, control plane | Planned |

Chi tiết và phần việc tiếp theo nằm trong [docs/project-studio-roadmap.md](docs/project-studio-roadmap.md).

## Cài đặt

### Cách khuyến nghị

Không bắt buộc phải dùng `uv`. Với nhu cầu chạy Studio, có thể dùng Python virtual environment + pip bình thường.

#### NVIDIA CUDA 12.8

```bash
python -m venv .venv
source .venv/bin/activate

pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128

pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Windows:

```powershell
.venv\Scripts\activate
```

#### Apple Silicon

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch==2.8.0 torchaudio==2.8.0
pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Khi gọi Python API trực tiếp trên Apple Silicon, có thể dùng `device_map="mps"`.

#### Clone để phát triển

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

## Chạy Studio nhanh nhất

### Chỉ cần giao diện Gradio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Nếu cần temporary public URL:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

### Chạy unified server

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Sau đó:

- UI: `http://127.0.0.1:8000/ui`
- OpenAPI: `http://127.0.0.1:8000/docs`
- REST: `http://127.0.0.1:8000/api/v1`
- MCP: `http://127.0.0.1:8000/mcp`
- Health: `http://127.0.0.1:8000/health`

## Workflow production khuyến nghị

### Bước 1: Chuẩn bị voice reference

Nên dùng đoạn audio sạch khoảng 3-10 giây, có transcript chính xác nếu có thể.

Trong Studio:

1. mở Voice Library;
2. upload reference audio;
3. nhập transcript;
4. chọn language;
5. lưu voice và variant.

Voice prompt được encode và lưu lại nên không cần làm lại mỗi session.

### Bước 2: Paste script

Ví dụ:

```markdown
# Video title

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:30
[SOFT] The question is what happens next.
Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

Các tag như `[WARM]`, `[SOFT]`, `[EMPHASIZE]` là metadata style, không bị đọc thành tiếng.

Tiêu đề `###` mặc định không đọc. Bật **Read section titles (###)** nếu muốn đọc tiêu đề.

### Bước 3: Preview

Nghe opening, middle, ending trước khi render dài để phát hiện sớm:

- voice reference không phù hợp;
- tốc độ nói chưa đúng;
- style variant không ổn;
- pronunciation có vấn đề.

### Bước 4: Render

Chọn:

- Voice
- Variant, thường dùng `AUTO`
- Language
- Quality preset
- Section cần render hoặc toàn bộ

`BALANCED` là preset hợp lý cho phần lớn production workload.

### Bước 5: Review và regenerate

Nếu một chunk fail verification hoặc nghe không tự nhiên, regenerate đúng chunk đó.

Không cần xóa project hoặc render lại các section đã verified.

### Bước 6: Export

Sau khi các section đạt yêu cầu, merge thành output hoàn chỉnh.

Project vẫn giữ metadata, chunk WAV, section WAV và history để có thể quay lại sửa sau.

## Resume khi runtime bị ngắt

Project Studio được thiết kế để session Colab/Kaggle không trở thành single point of failure.

Khi khởi động lại:

1. mở cùng workspace;
2. load project;
3. chọn Generate/Resume;
4. Studio bỏ qua phần đã verified;
5. tiếp tục phần pending.

Vì vậy nên giữ persistent copy của workspace ngoài runtime ephemeral.

## Colab và Kaggle

Xem [notebooks/README.md](notebooks/README.md).

### Kaggle

Active generation dùng local SSD:

```text
/kaggle/working/OmniVoiceStudio
```

Không nên render trực tiếp vào `/kaggle/input`.

### Colab

Nên tách:

```text
local runtime workspace
        <->
persistent Google Drive copy
```

Mục tiêu là Drive dùng để restore/sync, còn generation chạy trên local VM storage.

## Quality presets

### SAFE

Ưu tiên quality và verification, nhiều retry hơn.

### BALANCED

Preset production mặc định được khuyến nghị.

### FAST

Giảm effort và retry để tăng tốc, nhưng vẫn giữ text verification.

Nếu cần tinh chỉnh sâu hơn, dùng Advanced Settings theo project.

## Python API: voice cloning

```python
import soundfile as sf
import torch
from omnivoice import OmniVoice

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)

audio = model.generate(
    text="Hello from OmniVoice.",
    ref_audio="ref.wav",
    ref_text="Exact transcript of the reference audio.",
    language="en",
)

sf.write("out.wav", audio[0], model.sampling_rate)
```

## Lưu voice prompt để dùng lại

```python
prompt = model.create_voice_clone_prompt(
    ref_audio="ref.wav",
    ref_text="Exact transcript of the reference audio.",
)
prompt.save("my_voice.pt")
```

Session sau:

```python
from omnivoice import VoiceClonePrompt

prompt = VoiceClonePrompt.load("my_voice.pt")

audio = model.generate(
    text="No need to re-encode the reference.",
    voice_clone_prompt=prompt,
    language="en",
)
```

## CLI

| Command | Mục đích |
|---|---|
| `omnivoice-project-studio` | Project Studio UI production |
| `omnivoice-studio serve` | UI + REST + SSE + MCP |
| `omnivoice-benchmark` | benchmark RTF/memory |
| `omnivoice-demo` | robust interactive demo |
| `omnivoice-demo-legacy` | demo kiểu upstream |
| `omnivoice-infer` | inference một item |
| `omnivoice-infer-batch` | batch/multi-GPU |
| `omnivoice-merge-lora` | merge LoRA |

## REST async generation

Ví dụ submit:

```http
POST /api/v1/projects/my-project/generate
Idempotency-Key: my-project-render-v1
Content-Type: application/json

{
  "voice_name": "Narrator",
  "voice_variant": "AUTO",
  "language": "en",
  "sections": ["S01", "S02"],
  "resume": true,
  "strict": false,
  "quality_preset": "BALANCED"
}
```

Theo dõi:

```text
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/events
GET  /api/v1/jobs/{job_id}/stream
POST /api/v1/jobs/{job_id}/cancel
```

## MCP

Endpoint:

```text
http://HOST:PORT/mcp
```

Tools hiện có:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

`generate_project` trả về `job_id`, không giữ tool call mở trong suốt thời gian render.

## Stable hostname và authentication

Đối với public deployment:

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

Không commit token/password vào repository, notebook hoặc project data.

## Benchmark

Trước khi merge optimization inference:

```bash
omnivoice-benchmark \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

Benchmark đo:

- model load time;
- generation wall time;
- audio duration;
- RTF;
- CUDA peak allocation khi có GPU NVIDIA.

Nguyên tắc production là **không bật optimization chỉ vì lý thuyết nhanh hơn**. Phải có benchmark thực và xác minh chất lượng đầu ra.

Target-only inference hiện vẫn experimental.

## Tài liệu

- [Hướng dẫn compact](docs/GUIDE-COMPACT.vi.md)
- [Hướng dẫn đầy đủ](docs/GUIDE-FULL.vi.md)
- [Roadmap](docs/project-studio-roadmap.md)
- [Project Studio](docs/project-studio.md)
- [AI-native foundation](docs/ai-native-foundation.md)
- [SSE](docs/ai-native-sse.md)
- [MCP](docs/ai-native-mcp.md)
- [Stable tunnel](docs/stable-tunnel.md)
- [Hardware / Quality](docs/hardware-quality-presets.md)
- [Advanced Settings](docs/advanced-settings.md)
- [Kaggle local workspace](docs/kaggle-local-workspace.md)
- [Notebooks](notebooks/README.md)

## Chính sách theo upstream

Fork này không merge upstream một cách tự động.

Mỗi thay đổi upstream phải được kiểm tra:

- model/tokenizer compatibility;
- inference behavior;
- quality/output;
- dependency và CUDA;
- training compatibility;
- ảnh hưởng tới Project Studio;
- regression tests.

## Citation

```bibtex
@article{zhu2026omnivoice,
      title={OmniVoice: Towards Omnilingual Zero-Shot Text-to-Speech with Diffusion Language Models},
      author={Zhu, Han and Ye, Lingxuan and Kang, Wei and Yao, Zengwei and Guo, Liyong and Kuang, Fangjun and Han, Zhifeng and Zhuang, Weiji and Lin, Long and Povey, Daniel},
      journal={arXiv preprint arXiv:2604.00688},
      year={2026}
}
```

## Lưu ý sử dụng

Không sử dụng model để clone giọng trái phép, giả mạo danh tính, lừa đảo hoặc thực hiện hành vi bất hợp pháp. Chỉ sử dụng voice data khi bạn có quyền và sự đồng ý phù hợp, đồng thời tuân thủ luật và chính sách nền tảng liên quan.
