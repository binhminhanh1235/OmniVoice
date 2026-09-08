# OmniVoice Studio - Hướng dẫn đầy đủ

Tài liệu này mô tả cách cài đặt, vận hành và phục hồi OmniVoice Studio theo workflow production. Nếu chỉ cần chạy nhanh, xem [GUIDE-COMPACT.vi.md](GUIDE-COMPACT.vi.md).

## 1. OmniVoice Studio là gì?

OmniVoice core là mô hình TTS zero-shot đa ngôn ngữ. OmniVoice Studio bổ sung lớp production để xử lý các bài toán mà một lệnh `generate()` đơn lẻ không giải quyết tốt:

- nội dung dài nhiều section;
- runtime Colab/Kaggle có thể bị ngắt;
- cần resume mà không mất phần đã render;
- cần kiểm tra quality theo chunk;
- cần regenerate đúng phần lỗi;
- cần quản lý voice/reference lâu dài;
- cần queue nhiều project;
- cần API/MCP để AI client điều khiển;
- cần stable hostname và auth;
- cần benchmark trước khi merge optimization.

Kiến trúc khái quát:

```text
                   OmniVoice Studio
                         |
          +--------------+--------------+
          |              |              |
        /ui           /api/v1          /mcp
       Gradio           REST            MCP
          |              |              |
          +------ Application Layer ----+
                         |
                 Persistent Job Manager
                         |
       Project / Voice / Queue / History
                         |
                    OmniVoice Core
```

## 2. Khái niệm dữ liệu

Studio tổ chức narration theo:

```text
Project
  Section
    Beat
      Chunk
```

### Project

Một video, podcast, audiobook chapter hoặc một production unit hoàn chỉnh.

Project giữ:

- script gốc;
- project manifest;
- studio settings;
- section/chunk state;
- generated audio;
- history;
- output.

### Section

Một phần logic của script, thường được đánh dấu bằng:

```markdown
## S03 - 1:45-3:10
```

Section có thể render độc lập.

### Beat

Một đoạn có chung delivery/style intent.

Ví dụ:

```markdown
[WARM] This is a warm opening.
```

### Chunk

Đơn vị TTS nhỏ nhất được generate, verify, retry và regenerate độc lập.

Đây là lớp giúp một lỗi nhỏ không buộc phải render lại cả section hoặc project.

## 3. Cài đặt

### 3.1 Python environment

Khuyến nghị Python virtual environment sạch.

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Không bắt buộc dùng `uv`.

### 3.2 NVIDIA GPU

Ví dụ CUDA 12.8:

```bash
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128

pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Nếu CUDA version khác, chọn PyTorch wheel phù hợp với môi trường.

### 3.3 Apple Silicon

```bash
pip install torch==2.8.0 torchaudio==2.8.0
pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Python API có thể dùng:

```python
device_map="mps"
```

Local Apple Silicon phù hợp để test/authoring. Với workload dài, GPU hosted thường thuận lợi hơn về throughput.

### 3.4 Development checkout

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

## 4. Chọn launcher

### 4.1 Project Studio UI

Dùng khi bạn muốn thao tác bằng web UI:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Temporary Gradio share:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

### 4.2 Unified server

Dùng khi cần UI + REST + SSE + MCP:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Surfaces:

```text
/ui
/api/v1
/api/v1/jobs/{id}/stream
/mcp
/health
/docs
```

## 5. Workspace

Workspace là root chứa state của Studio.

Ví dụ:

```text
OmniVoiceStudio/
  voices/
  projects/
  jobs.json
  project-queue.json
  hardware-quality.json
  ...
```

### Quy tắc quan trọng

**Execution storage và persistent storage không nhất thiết phải là cùng một nơi.**

Với hosted runtime, active generation nên chạy trên local SSD để tránh latency của remote filesystem.

## 6. Colab

Mô hình khuyến nghị:

```text
Google Drive
  persistent copy
       |
       | restore / mirror
       v
/content/OmniVoiceStudio
  active local workspace
       |
       v
 generation + checkpoints
```

Lợi ích:

- giảm latency khi tạo nhiều file nhỏ;
- không đẩy render hot path qua Drive FUSE;
- giữ checkpoint/resume logic;
- có thể sync project/voice/output về Drive.

Notebook maintained:

```text
notebooks/OmniVoice_Project_Studio_Colab.ipynb
```

Bản đơn giản:

```text
notebooks/OmniVoice_Project_Studio_Colab_Gradio.ipynb
```

## 7. Kaggle

Workspace local mặc định:

```text
/kaggle/working/OmniVoiceStudio
```

`/kaggle/input` là read-only source, không phải render workspace.

### Dual-T4

Profile hợp lý:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper verification
```

Nếu chỉ có một GPU, để Whisper trên CPU giúp giữ VRAM chính cho TTS.

Notebook:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

Bản đơn giản:

```text
notebooks/OmniVoice_Project_Studio_Kaggle_Gradio.ipynb
```

## 8. Persistent hosted-runtime cache

Persistent startup caching đang được tích hợp theo một PR riêng và chưa được xem là production feature cho tới khi merge vào `master`.

Mục tiêu:

- dependency/wheel cache;
- pip cache;
- Hugging Face model cache;
- Torch cache;
- Whisper cache;
- exact source-revision wheel;
- cache metadata;
- version fingerprint;
- invalidation khi dependency/source thay đổi;
- fast path khi cache hợp lệ;
- cold-start fallback khi cache thiếu/hỏng;
- local SSD vẫn là nơi active generation.

Đây là startup optimization, không phải thay đổi inference algorithm.

## 9. Voice workflow

### 9.1 Reference audio

Nên dùng:

- 3-10 giây;
- ít noise;
- không clipping;
- không có nhạc nền mạnh;
- một speaker;
- transcript chính xác.

### 9.2 Voice Library

Voice Library lưu reusable prompt.

Ví dụ structure:

```text
voices/
  narrator/
    voice.json
    prompts/
      default.pt
      warm.pt
      soft.pt
    references/
      default.wav
      warm.wav
      soft.wav
```

### 9.3 Variant

Một voice có thể có:

- `DEFAULT`
- `WARM`
- `SOFT`
- `PRAYER`
- `EMPHASIZE`

Khi chọn `AUTO`, Style Resolver có thể chọn variant phù hợp với directive.

## 10. Voice Doctor

Dùng Voice Doctor trước khi production render nếu reference chưa được kiểm chứng.

Các loại vấn đề cần chú ý:

- quá ngắn/quá dài;
- clipping;
- silence quá nhiều;
- level quá thấp;
- DC offset;
- noise;
- dynamic bất thường.

Voice Doctor không thay thế nghe bằng tai, nhưng giúp loại các lỗi reference rõ ràng.

## 11. Voice Stability

Voice Stability tạo nhiều probe thực để xem voice clone có ổn định qua các đoạn khác nhau hay không.

Nên dùng trước khi render hàng chục phút nội dung.

## 12. Script format

Ví dụ:

```markdown
# 5 People You Should Stop Enabling

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:45
### The pattern

[SOFT] The question is what happens next.
Do they come back and listen?
Do they reflect?
Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

### Heading

`#`, `##`, `###` là project metadata theo mặc định.

### Optional title narration

Bật:

```text
Read section titles (###)
```

khi muốn `###` trở thành first spoken beat.

### Directive

Các generic style intent:

```text
[WARM]
[SOFT]
[EMPHASIZE]
[NORMAL]
```

Các tag này không bị đọc trực tiếp.

### Native voice-design attribute

Một số directive có thể map sang attribute mà OmniVoice thực sự hỗ trợ, ví dụ whisper/pitch, thay vì gửi generic intent không được model định nghĩa.

## 13. Leading conjunction safeguard

Các từ đầu câu như:

```text
Or
And
But
So
Yet
Nor
```

có thể nghe sai nếu bị tách thành chunk đứng riêng.

Narration parser cố giữ conjunction với chunk trước khi:

- có previous chunk;
- không phá paragraph boundary;
- combined chunk vẫn nằm trong word/character limits.

Mục tiêu là giữ ngữ cảnh phát âm mà không làm chunk quá dài.

## 14. Language selector

Studio dùng dropdown thay vì yêu cầu nhập language ID thủ công ở các luồng chính.

English được đưa lên đầu danh sách.

Backend vẫn dùng language ID như:

```text
en
```

nên UI convenience không thay đổi inference contract.

## 15. Parse project

Khi paste script, dùng Analyze/Parse trước.

Kiểm tra:

- section count;
- beat count;
- chunk count;
- title behavior;
- style;
- section boundaries.

Nếu cấu trúc sai, sửa script trước khi render.

## 16. Quality preset

### SAFE

Dùng khi ưu tiên correctness/recovery hơn tốc độ.

Đặc tính:

- effort cao;
- retry nhiều;
- verification đầy đủ.

### BALANCED

Khuyến nghị production mặc định.

Đây nên là điểm bắt đầu trước khi tinh chỉnh Advanced Settings.

### FAST

Giảm generation/retry effort.

Phù hợp khi:

- cần throughput;
- script/reference đã ổn;
- chấp nhận review thủ công nhiều hơn.

## 17. Advanced Settings

Advanced Settings là override theo project.

Nguyên tắc:

1. bắt đầu bằng preset;
2. chỉ override khi có lý do cụ thể;
3. lưu thay đổi theo project;
4. reset về preset khi thử nghiệm không hiệu quả.

Không nên biến Advanced Settings thành "wall of knobs" phải cấu hình cho mọi project.

## 18. Preview

Preview opening/middle/ending trước full render.

Checklist:

- voice identity;
- accent;
- pronunciation;
- pacing;
- style transition;
- silence;
- loudness.

Nếu preview fail, không nên bắt đầu queue dài.

## 19. Render

Chọn:

- project;
- voice;
- variant;
- language;
- quality preset;
- section selection;
- Resume.

Khuyến nghị:

```text
Variant: AUTO
Quality: BALANCED
Resume: ON
```

## 20. Verification

Chunk được quality gate kiểm tra sau generation.

Verification có thể dùng ASR text comparison và pacing signals.

Nếu output chưa đạt, hệ thống có thể retry/adapt tùy preset/config.

## 21. Review

Review theo section/chunk thay vì chỉ nghe file cuối.

Nếu một chunk có vấn đề:

1. xác định chunk;
2. mark/regenerate chunk;
3. giữ nguyên các chunk verified;
4. review lại section.

## 22. Section Version History

Trước các thao tác có thể làm thay đổi output đã tốt, Studio có thể snapshot version để:

- nghe lại;
- so sánh;
- restore.

Điều này tránh "fix một lỗi nhỏ rồi mất bản tốt cũ".

## 23. Resume

Khi runtime chết:

```text
restart runtime
   |
restore workspace
   |
load project
   |
Generate / Resume
   |
skip verified
   |
continue pending
```

Không xóa manifest, chunk reports hoặc section status nếu mục tiêu là resume.

## 24. Multi-project queue

Queue phù hợp khi có nhiều project.

Trạng thái project có thể gồm:

```text
PENDING
GENERATING
NEEDS_REVIEW
FAILED
DONE
```

Queue có thể:

- chạy section-by-section;
- pause cooperative;
- continue sau project error;
- skip completed work;
- auto-merge tùy cấu hình.

## 25. Export

Sau review, merge section đã verified.

Output production có thể gồm:

- section WAV;
- merged WAV;
- timeline metadata;
- project state để quay lại regenerate.

Các export profile nâng cao như MP3 presets vẫn thuộc roadmap.

## 26. Data backup

Đừng xem runtime ephemeral là nơi lưu duy nhất.

Nên backup:

- `voices/`;
- `projects/`;
- project settings;
- queue state nếu cần;
- output;
- cache metadata sau khi persistent cache được merge.

## 27. Unified server

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

### Health

```text
GET /health
```

### Capabilities

```text
GET /api/v1/capabilities
```

### Hardware

```text
GET /api/v1/hardware
```

### Projects

```text
GET /api/v1/projects
GET /api/v1/projects/{project_id}
```

### Queue

```text
GET /api/v1/queue
```

## 28. Async generation API

Submit:

```http
POST /api/v1/projects/my-project/generate
Idempotency-Key: my-project-render-v1
Content-Type: application/json

{
  "voice_name": "Narrator",
  "voice_variant": "AUTO",
  "language": "en",
  "sections": ["S03", "S04"],
  "resume": true,
  "strict": false,
  "quality_preset": "BALANCED"
}
```

Server trả về job ngay, không block HTTP request cho tới khi render xong.

## 29. Job Manager

State chính:

```text
QUEUED
  |
RUNNING
  +--> COMPLETED
  +--> FAILED
  +--> CANCEL_REQUESTED -> safe checkpoint -> CANCELLED
```

### Single-GPU serialization

GPU-bound jobs chạy qua một worker queue để tránh nhiều task tranh cùng một GPU.

### Idempotency

Nếu client retry sau network timeout với cùng idempotency key, Job Manager có thể trả lại job cũ thay vì tạo duplicate render.

### Recovery

Job state được lưu, cho phép server phục hồi queued/running intent sau restart theo contract hiện tại.

## 30. SSE

Endpoint:

```text
GET /api/v1/jobs/{job_id}/stream
```

Events có thể gồm:

```text
queued
started
project.started
section.started
section.finished
project.finished
completed
failed
cancelled
```

Client reconnect có thể dùng:

```http
Last-Event-ID: 7
```

hoặc query cursor.

## 31. MCP

Endpoint:

```text
/mcp
```

Tools v1:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Resources:

```text
omnivoice://projects/{project_id}
omnivoice://queue
```

### Agent workflow

```text
list_projects
   |
inspect_project
   |
generate_project
   |
job_id
   |
get_job / SSE
```

## 32. Authentication

Machine/API token:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
```

Scopes:

```text
omnivoice:read
omnivoice:generate
omnivoice:queue
omnivoice:mcp
omnivoice:admin
```

Ví dụ:

```bash
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
```

UI protection:

```bash
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"
```

Không đặt token/password vào git.

## 33. Stable Cloudflare Tunnel

Một hostname cố định giúp client không phải đổi URL mỗi khi Colab/Kaggle session đổi.

Ví dụ:

```text
https://omnivoice.example.com/ui
https://omnivoice.example.com/api/v1
https://omnivoice.example.com/mcp
```

Environment:

```bash
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Run:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

Tunnel token được chuyển qua private token file thay vì raw command-line argument.

## 34. MCP transport security

Public MCP cần host/origin protection.

Các biến có thể dùng:

```bash
export OMNIVOICE_MCP_ALLOWED_HOSTS="omnivoice.example.com,omnivoice.example.com:*"
export OMNIVOICE_MCP_ALLOWED_ORIGINS="https://omnivoice.example.com"
```

Chỉ dùng:

```bash
OMNIVOICE_MCP_TRUST_PROXY=1
```

khi một trusted reverse proxy thực sự là security boundary.

## 35. Benchmark

CLI:

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --language en \
  --preset BALANCED \
  --warmup 1 \
  --repeat 2 \
  --output benchmark.json
```

Metrics:

- model load seconds;
- elapsed generation seconds;
- generated audio seconds;
- weighted RTF;
- median RTF;
- peak CUDA memory.

## 36. Optimization policy

Mọi inference optimization phải qua:

1. reproducible baseline;
2. before/after benchmark;
3. projection/output equivalence phù hợp;
4. real TTS generation;
5. ASR/text quality;
6. perceptual listening;
7. memory impact;
8. long-form regression.

## 37. Target-only inference

Target-only inference hiện là **experimental**.

Ý tưởng là chỉ chạy audio projection trên target positions thay vì toàn bộ context positions.

Hiện unit test projection equivalence chưa đủ để kết luận production-safe.

Trước khi bật cần:

- benchmark thật trên GPU;
- cùng prompt/seed/config;
- compare output;
- ASR WER/similarity;
- duration/pacing;
- nghe A/B;
- test clone voice và long-form;
- kiểm tra memory.

## 38. Upstream policy

Fork không merge upstream mù.

Checklist khi upstream thay đổi:

- merge-base;
- commits upstream mới;
- model architecture;
- tokenizer;
- generation config;
- dependency;
- training;
- Python API;
- notebook compatibility;
- Studio regression.

Khi có drift, nên thêm regression test trước khi cherry-pick hoặc merge upstream fix.

## 39. Troubleshooting

### 39.1 CUDA OOM

Thử theo thứ tự:

1. dừng job khác;
2. Whisper -> CPU hoặc GPU thứ hai;
3. giảm workload/batch;
4. dùng `BALANCED` hoặc `FAST`;
5. restart runtime nếu fragmentation nặng.

### 39.2 Whisper làm startup chậm

Lazy CPU ASR đang được đánh giá như safe optimization. Cho tới khi merge, behavior production của master vẫn là contract hiện tại.

### 39.3 Voice nghe khác reference

Kiểm tra:

- reference length;
- transcript;
- language;
- noise;
- clipping;
- cross-language accent transfer.

### 39.4 Một từ/câu phát âm sai

Dùng:

- pronunciation override;
- chỉnh punctuation;
- regenerate chunk;
- tránh chunk bắt đầu bằng conjunction thiếu ngữ cảnh;
- kiểm tra language.

### 39.5 Section title không được đọc

Bật:

```text
Read section titles (###)
```

### 39.6 Title bị đọc ngoài ý muốn

Tắt checkbox. Default là không đọc title.

### 39.7 Runtime restart

Restore workspace và Resume, không tạo project mới.

### 39.8 MCP 401

Kiểm tra bearer token.

### 39.9 MCP 403

Token đúng nhưng thiếu scope.

### 39.10 Tunnel online nhưng MCP lỗi host/origin

Kiểm tra:

- `OMNIVOICE_PUBLIC_URL`;
- allowed hosts;
- allowed origins;
- reverse proxy config.

## 40. Production checklist trước render dài

- [ ] Reference audio sạch.
- [ ] Transcript reference đúng.
- [ ] Voice Doctor không có lỗi nghiêm trọng.
- [ ] Voice Stability chấp nhận được.
- [ ] Language đúng.
- [ ] Script parse đúng section.
- [ ] Title narration đúng ý.
- [ ] Preview opening/middle/ending ổn.
- [ ] Quality preset đã chọn.
- [ ] Workspace có đủ disk.
- [ ] Persistence/backup đã chuẩn bị.
- [ ] Resume bật.
- [ ] Không có duplicate GPU job.
- [ ] Nếu public server, auth đã bật.

## 41. Checklist sau render

- [ ] Không còn failed chunk chưa xử lý.
- [ ] Nghe spot-check đầu/giữa/cuối.
- [ ] Review conjunction/pronunciation nhạy cảm.
- [ ] Merge/export thành công.
- [ ] Backup project state.
- [ ] Backup final output.
- [ ] Giữ project nếu còn khả năng sửa sau.

## 42. Phần đang triển khai và kế hoạch tiếp theo

### In review

- Persistent Colab/Kaggle startup caching.

### Safe optimization cần benchmark/merge riêng

- local-first Colab workspace;
- lazy CPU ASR startup.

### Experimental

- target-only inference.

### Planned

- cache verification/preprocessing metadata;
- cascade verifier;
- same-language reference selection;
- additional write REST handlers cho preview/queue/regenerate/merge;
- Universal OmniVoice Skill;
- ChatGPT/Claude Code/agent examples;
- persistent control plane + worker registry;
- richer directive DSL;
- phrase-level style;
- timeline/silence editor;
- WAV/MP3 export profiles;
- unattended project CLI;
- upstream drift CI guard.

Roadmap canonical: [project-studio-roadmap.md](project-studio-roadmap.md).

## 43. Tài liệu liên quan

- [README tiếng Việt](../README.vi.md)
- [README English](../README.md)
- [Compact guide](GUIDE-COMPACT.vi.md)
- [Roadmap](project-studio-roadmap.md)
- [Project Studio](project-studio.md)
- [Hardware/Quality](hardware-quality-presets.md)
- [Advanced Settings](advanced-settings.md)
- [AI-native foundation](ai-native-foundation.md)
- [SSE](ai-native-sse.md)
- [MCP](ai-native-mcp.md)
- [Stable tunnel](stable-tunnel.md)
- [Kaggle workspace](kaggle-local-workspace.md)
- [Notebooks](../notebooks/README.md)
