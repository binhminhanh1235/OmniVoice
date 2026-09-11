# OmniVoice Studio - Hướng dẫn đầy đủ

Tài liệu này mô tả production workflow hiện tại của fork `binhminhanh1235/OmniVoice`: local Studio, Colab/Kaggle, persistent startup cache, Lazy CPU ASR Startup, project recovery, REST/SSE/MCP, stable tunnel, security và acceptance.

Nếu chỉ cần chạy nhanh, xem [GUIDE-COMPACT.vi.md](GUIDE-COMPACT.vi.md). Quy trình đo cold/warm chính thức nằm ở [production-acceptance.md](production-acceptance.md).

## 1. Mục tiêu của OmniVoice Studio

Upstream OmniVoice cung cấp model TTS multilingual/zero-shot. Fork này bổ sung lớp production để xử lý nội dung dài và runtime dễ bị ngắt như Colab/Kaggle.

Studio tổ chức dữ liệu theo:

```text
Project
  -> Section
      -> Beat
          -> Chunk
```

Mỗi project có script, voice settings, quality settings, trạng thái chunk/section, history, output và checkpoint riêng.

Mục tiêu chính:

- render dài mà có thể resume;
- regenerate đúng phần lỗi;
- reuse voice prompt;
- verify chất lượng bằng ASR khi cần;
- chạy tốt trên hosted GPU;
- tách active local-SSD hot path khỏi persistence remote;
- expose API/MCP để agent/tool có thể điều khiển.

## 2. Trạng thái production hiện tại

Các foundation đã merge gồm:

- robust long-form Project Studio;
- unified project-first workspace;
- Voice Library + Style Bank;
- Text Doctor, Voice Doctor, Voice Stability;
- preview + version history;
- queue + resume/recovery;
- English-first language selector;
- leading conjunction pronunciation protection;
- optional section-title narration;
- REST/OpenAPI;
- async Job Manager;
- SSE progress/replay;
- Streamable HTTP MCP;
- bearer auth/scopes + optional UI Basic Auth;
- Cloudflare named tunnel;
- benchmark framework;
- Persistent Colab/Kaggle Startup Cache;
- Lazy CPU ASR Startup.

Hai hạng mục hosted-runtime cuối hiện ở trạng thái **MERGED / VERIFIED** trên `master`.

`Target-only inference` vẫn **Experimental**. Không xem đó là production path cho tới khi có benchmark và quality acceptance riêng.

## 3. Cài đặt local

### 3.1 NVIDIA CUDA 12.8

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

### 3.2 Apple Silicon

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch==2.8.0 torchaudio==2.8.0
pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Direct Python inference có thể dùng `device_map="mps"`. Với workload dài, throughput tốt nhất vẫn thường đến từ accelerator runtime phù hợp.

### 3.3 Development install

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

## 4. Chạy Studio

### 4.1 Project Studio UI

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Nếu cần temporary Gradio public URL:

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860 \
  --share
```

### 4.2 Unified server

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Một process cung cấp:

```text
/ui                         Gradio
/api/v1                     REST
/api/v1/jobs/{id}/stream    SSE
/mcp                        Streamable HTTP MCP
/health                     health check
/docs                       OpenAPI
```

## 5. Workflow project-first

### 5.1 Chuẩn bị voice

Reference audio nên:

- sạch, ít noise;
- không có background music nếu tránh được;
- thường 3-10 giây là hợp lý;
- có transcript chính xác nếu có thể.

Nếu bạn nhập transcript chính xác, clone prompt không cần ASR chỉ để đoán transcript reference.

Sau khi tạo voice, lưu vào Voice Library để các session sau reuse prompt đã encode.

### 5.2 Script format

Ví dụ:

```markdown
# Video title

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:30
### The pattern

[SOFT] The question is what happens next.
Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

Các heading mặc định là metadata. Bật **Read section titles (###)** nếu muốn đọc `###` thành tiếng.

Style tags như `[WARM]`, `[SOFT]`, `[PRAYER]`, `[EMPHASIZE]` được dùng để chọn style/voice behavior, không phải literal text để đọc.

### 5.3 Leading conjunction protection

Các câu bắt đầu bằng `Or`, `And`, `But` có thể mất ngữ cảnh nếu chunking tách quá gắt. Studio có logic bảo vệ/merge khi an toàn để giảm trường hợp đọc sai hoặc nuốt từ đầu câu.

Không nên tự chèn punctuation giả chỉ để “ép” model nếu chưa cần. Giữ script tự nhiên trước, sau đó dùng Text Doctor/preview để xác nhận.

### 5.4 Preview

Trước full render, nghe ít nhất:

- opening;
- một đoạn giữa;
- ending;
- một đoạn có style mạnh nếu project dùng nhiều style tags.

Kiểm tra:

- voice identity;
- pronunciation;
- pacing;
- loudness;
- style fit;
- reference noise;
- section-title behavior.

### 5.5 Render

Khuyến nghị mặc định:

```text
Voice variant: AUTO
Quality preset: BALANCED
Resume: ON
Language: chọn rõ nếu biết
```

Có thể render toàn bộ hoặc chỉ một số section.

### 5.6 Review và targeted regeneration

Nếu một chunk fail verification hoặc nghe chưa đạt:

1. xác định chunk/section;
2. regenerate đúng phần đó;
3. giữ nguyên phần đã verified;
4. kiểm tra history nếu cần quay lại bản trước.

Đây là lợi ích chính của project-first Studio so với render một file dài monolithic.

### 5.7 Export

Chỉ export final khi các section cần thiết đã đạt. Giữ project state, chunk WAV, section WAV và history để có thể sửa tiếp sau này.

## 6. Quality presets

| Preset | Mục tiêu |
|---|---|
| `SAFE` | verification/retry mạnh hơn |
| `BALANCED` | production default khuyến nghị |
| `FAST` | giảm generation/retry effort để ưu tiên throughput |

Không nên bắt đầu bằng Advanced Settings. Dùng preset trước, chỉ override khi có lý do cụ thể và evidence từ preview/render.

## 7. Resume và recovery

Project state được lưu để runtime restart không buộc render lại từ đầu.

Sau restart:

1. restore/mount đúng workspace;
2. mở cùng project;
3. Generate/Resume;
4. Studio skip phần đã complete;
5. tiếp tục pending/failed work.

Không tạo project mới chỉ vì Colab/Kaggle session mới.

## 8. Local SSD là hot path

Nguyên tắc production:

```text
active generation -> local SSD
persistence       -> Drive / Kaggle Dataset / remote storage
```

Lý do:

- checkpoint nhỏ và thường xuyên;
- nhiều WAV/chunk file;
- metadata updates;
- random I/O;
- remote/FUSE latency có thể làm pipeline chậm và dễ lỗi hơn.

## 9. Colab production architecture

Notebook:

```text
notebooks/OmniVoice_Project_Studio_Colab.ipynb
```

Mô hình:

```text
/content/drive/MyDrive/OmniVoiceStudio
      persistent project mirror
      persistent startup cache
               |
               | restore / sync
               v
/content/OmniVoiceStudio
      active local-SSD workspace
```

Notebook production:

- mount Drive;
- resolve exact OmniVoice master SHA hoặc dùng `OMNIVOICE_PACKAGE_REF` exact SHA;
- resolve exact model/ASR revision;
- restore compatible cache;
- install exact verified wheel;
- restore project data về local SSD;
- chạy Studio local-first;
- sync project state về Drive;
- persist runtime cache khi kết thúc.

## 10. Kaggle production architecture

Notebook:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

Active workspace:

```text
/kaggle/working/OmniVoiceStudio
```

Writable startup cache export:

```text
/kaggle/working/OmniVoiceStartupCache
```

Attached startup cache Dataset ở session sau:

```text
/kaggle/input/omnivoice-startup-cache
```

`/kaggle/input` là read-only. Không dùng nó làm render workspace.

### Dual-T4 mapping

Khi có hai T4:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper ASR verification
CPU     -> preprocessing/API/UI/file I/O
```

OmniVoice không bị sharding qua hai T4 trong production notebook hiện tại. T4 thứ hai được dùng riêng cho ASR verification.

## 11. Persistent hosted startup cache

### 11.1 Những gì được cache

Bootstrap production quản lý:

- pip cache;
- exact OmniVoice wheel cache;
- Hugging Face/model cache;
- Torch cache;
- Whisper/ASR model cache;
- metadata/fingerprint/inventory.

### 11.2 Exact-revision safety

Cache không tự động chọn “last working revision”. Source được resolve thành exact 40-character SHA trước.

Model và ASR revision cũng được resolve/fingerprint. Nếu fingerprint khác, compatible cache fast path không được dùng.

### 11.3 Wheel integrity

Cached exact wheel chỉ được reuse khi manifest khớp:

- package ref;
- filename;
- byte size;
- SHA-256;
- ZIP integrity.

Nếu corrupt/truncated/missing, bootstrap cold-fallback và rebuild thay vì giả vờ warm.

### 11.4 Interrupted cache

Persistent cache chỉ fast-path khi metadata nói state ready và inventory thật trên disk khớp metadata. Partial/interrupted trees bị từ chối.

## 12. Cold/warm production acceptance

Bootstrap ghi:

```text
startup-cache-evidence.json
```

Cần hai mẫu thật:

```text
cold.json
warm.json
```

Cùng exact `package_ref`.

Chạy:

```bash
python scripts/hosted_cache_acceptance.py cold.json warm.json
```

PASS:

```text
cold.package_ref == warm.package_ref
warm.resource_fast_path == true
warm.wheel_fast_path == true
warm.bootstrap_seconds < cold.bootstrap_seconds
```

Không dùng benchmark giả hoặc con số suy diễn từ CI.

### Colab acceptance checkpoint

Production notebook có biến:

```python
ACCEPTANCE_SAMPLE = ""
```

Cold run: đổi thành `"cold"` và chạy cell.

Warm run sau restart: đổi thành `"warm"` và chạy cell.

Evidence được lưu dưới exact package-ref trong Drive. Khi đủ hai mẫu, notebook fetch acceptance script từ cùng exact revision và chạy luôn.

### Kaggle acceptance checkpoint

Cold run:

1. không attach compatible cache Dataset;
2. bootstrap;
3. set `ACCEPTANCE_SAMPLE = "cold"`;
4. save/version `OmniVoiceStartupCache` thành Dataset.

Warm run:

1. attach Dataset;
2. bootstrap từ đầu;
3. set `ACCEPTANCE_SAMPLE = "warm"`;
4. notebook copy cold evidence từ attached Dataset sang writable export tree;
5. đủ cold/warm thì tự compare.

## 13. Lazy CPU ASR Startup

### 13.1 Mục tiêu

CPU Whisper pipeline trước đây có thể làm server startup chậm dù user chưa cần transcription/verification.

Với explicit CPU ASR:

```text
--asr-device cpu
```

Studio hiện chỉ cấu hình ASR metadata lúc startup, chưa construct pipeline.

### 13.2 Expected startup logs

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

Server/UI/API/MCP có thể ready trước khi CPU ASR pipeline được tạo.

### 13.3 First real use

ASR được initialize khi có first real operation cần ASR, ví dụ:

- Voice Doctor transcription;
- clone prompt không có `ref_text`;
- robust verification.

Expected log:

```text
Initializing ASR on first use: model=... device=cpu
```

### 13.4 Thread safety và retry

Model-scoped lock bảo đảm concurrent first-use không tạo nhiều pipeline song song.

Nếu load fail:

- không publish partial pipe;
- `_asr_pipe` vẫn không usable;
- request sau có thể retry.

### 13.5 Explicit accelerator không đổi

Nếu:

```text
--asr-device cuda:1
```

ASR vẫn eager. Đây là contract cố ý để không thay behavior của dedicated accelerator setup.

Do đó Kaggle dual-T4 thường **không áp dụng lazy CPU ASR**, vì ASR được đặt trên `cuda:1`.

## 14. REST jobs

Unified server dùng async jobs cho generation dài.

Typical flow:

```text
POST project generation
  -> trả job_id
GET job status/events
  -> poll hoặc SSE stream
POST cancel
  -> cooperative cancellation
```

Lợi ích:

- request không giữ connection nhiều phút;
- agent/tool dễ theo dõi;
- reconnect vẫn đọc được durable events;
- idempotency giảm duplicate generation.

## 15. MCP

Endpoint:

```text
http://HOST:PORT/mcp
```

Tools chính:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

`generate_project` trả durable `job_id`.

## 16. Stable public hostname

Dùng remotely managed Cloudflare Tunnel nếu muốn một hostname cố định cho agent/API.

Environment example:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="strong-password"
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

Không commit token/password. Tunnel runtime không đặt raw tunnel token trực tiếp trên child-process command line.

## 17. Security checklist

```text
[ ] API token đủ mạnh
[ ] Scope chỉ cấp đúng quyền cần dùng
[ ] UI auth bật nếu public
[ ] Không hard-code secret trong notebook
[ ] Không commit Drive/Kaggle secret
[ ] Không đưa token vào project metadata
[ ] Public URL đúng hostname đã cấu hình
```

## 18. Benchmark framework

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

Framework có thể ghi model load time, generated audio duration, RTF và CUDA peak allocation khi environment hỗ trợ.

### Production rule

Không merge speed optimization chỉ vì microbenchmark “có vẻ nhanh”. Cần:

- real workload;
- same input/settings;
- quality acceptance;
- memory evidence khi liên quan;
- regression test;
- exact-head CI;
- post-merge exact-master verification.

## 19. Target-only inference

Target-only inference vẫn experimental.

Không bật production cho tới khi có tối thiểu:

- real GPU speed benchmark;
- projection/output equivalence;
- real voice-clone acceptance;
- ASR quality;
- pacing;
- perceptual A/B;
- long-form acceptance;
- memory evidence;
- no training regression;
- no API/CLI regression.

Persistent startup cache và Lazy CPU ASR không phải bằng chứng thay thế cho các gate trên.

## 20. Troubleshooting

### Startup cache không warm

Kiểm tra:

- package ref có giống không;
- model revision có đổi không;
- ASR revision có đổi không;
- cache Dataset/Drive path có đúng không;
- `resource_fast_path`;
- `wheel_fast_path`;
- cache metadata/inventory.

Nếu fingerprint khác, cold fallback là behavior đúng.

### Warm time không nhanh hơn cold

Không sửa evidence bằng tay. Kiểm tra network, Drive/Kaggle Dataset attach, pip/model cache path và liệu “cold” có thật sự cold hay không.

### CPU ASR vẫn load lúc startup

Kiểm tra launcher và argument:

```text
--asr-device cpu
```

Expected log phải có `lazy_cpu_asr=True`.

Nếu bạn dùng `cuda:1`, eager ASR là đúng behavior.

### First ASR request fail

Có thể retry request sau khi sửa nguyên nhân. Lazy gate được thiết kế để failed load không poison partial state.

### Project render chậm bất thường trên Colab

Đảm bảo active workspace là `/content/OmniVoiceStudio`, không phải Drive FUSE.

### Kaggle không ghi được cache

Đừng ghi vào `/kaggle/input`. Ghi vào `/kaggle/working/OmniVoiceStartupCache`, sau đó save/version thành Dataset.

## 21. Production acceptance checklist

### Runtime

```text
[ ] Exact package SHA
[ ] Exact model revision
[ ] Exact ASR revision
[ ] Local SSD workspace
[ ] Persistent boundary configured
```

### Cache

```text
[ ] Cold sample genuine
[ ] Warm sample genuine
[ ] Same package_ref
[ ] resource_fast_path=true on warm
[ ] wheel_fast_path=true on warm
[ ] warm bootstrap faster
[ ] acceptance script PASS
```

### ASR

CPU path:

```text
[ ] lazy_cpu_asr=True at startup
[ ] deferred log observed
[ ] first-use initialization observed
[ ] later ASR reuse works
```

Accelerator path:

```text
[ ] explicit accelerator mapping intentional
[ ] eager ASR expected
```

### Functional

```text
[ ] UI starts
[ ] /health works
[ ] REST/OpenAPI works
[ ] MCP works
[ ] Script parsing works
[ ] Voice Library works
[ ] Preview works
[ ] Render works
[ ] Verification works
[ ] Resume works
[ ] Targeted regenerate works
[ ] Export works
```

## 22. Tài liệu liên quan

- [README tiếng Việt](../README.vi.md)
- [Compact guide](GUIDE-COMPACT.vi.md)
- [Production acceptance](production-acceptance.md)
- [Project Studio roadmap](project-studio-roadmap.md)
- [Project Studio](project-studio.md)
- [MCP](ai-native-mcp.md)
- [SSE](ai-native-sse.md)
- [Stable tunnel](stable-tunnel.md)
- [Hardware/quality presets](hardware-quality-presets.md)
- [Kaggle workspace](kaggle-local-workspace.md)
- [Notebooks](../notebooks/README.md)