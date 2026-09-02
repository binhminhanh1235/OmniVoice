# Hardware Detection + Quality Presets

Project Studio exposes three named generation policies instead of a wall of decoder parameters.

## Hardware detection

The **5. Hardware & Quality** tab reports:

- CUDA availability;
- GPU name;
- total VRAM;
- CUDA compute capability;
- recommended quality preset;
- recommended ASR device.

For a common **single** Google Colab/Kaggle Tesla T4 / ~16 GB runtime, Studio recommends:

```text
quality preset = BALANCED
ASR device     = cpu
```

Keeping Whisper on CPU avoids competing with OmniVoice for the only T4's VRAM.

For a **dual-T4** Kaggle runtime, Studio recommends:

```text
cuda:0         = OmniVoice TTS
cuda:1         = Whisper ASR
quality preset = BALANCED
ASR device     = cuda:1
```

The secondary GPU is preferred for ASR when it has at least 4 GB VRAM. This keeps the TTS decoder isolated on the primary GPU while moving repeated chunk verification and optional word-timestamp work off the CPU.

Hardware recommendations are advisory. They never silently change a project's saved quality policy.

## Presets

| Preset | Diffusion steps | Retries | Split depth | ASR verification | Adaptive retry | Pacing guard |
| --- | ---: | ---: | ---: | --- | --- | --- |
| SAFE | 32 | 3 | 2 | ON | ON | ON |
| BALANCED | 28 | 2 | 2 | ON | ON | ON |
| FAST | 24 | 1 | 1 | ON | OFF | OFF |

### SAFE

Use for final narration, important scripts, and unattended overnight queues where quality matters more than throughput.

SAFE preserves the strongest current Project Studio repair path:

```text
ASR verification
+ adaptive retry
+ pacing anomaly guard
+ up to 3 attempts
+ recursive split depth 2
```

### BALANCED

Use for T4 long-form production when SAFE throughput is unnecessarily expensive.

BALANCED still keeps the same text verification thresholds, adaptive retry, pacing guard and recursive recovery. It reduces diffusion steps and retry budget conservatively.

### FAST

Use for quick review renders or when throughput is explicitly more important than automatic recovery.

FAST intentionally reduces diffusion effort and disables adaptive retry / pacing word-timestamp checks. **It still performs ASR text verification.** A bad result remains `unverified`; FAST does not gain speed by silently accepting incorrect wording.

## Workspace default vs project override

Workspace default is persisted at:

```text
<workspace>/hardware-quality.json
```

A project can inherit that default or store an explicit override in:

```text
<project>/studio.json
```

Example:

```json
{
  "voice_name": "Narrator",
  "voice_variant": "AUTO",
  "language": "en",
  "quality_preset": "SAFE"
}
```

This is useful with Project Queue. Each queued project is loaded through the quality-aware controller, so a project configured as SAFE stays SAFE while another project can use BALANCED or FAST.

## Recommended T4 workflow

Single T4:

```text
Hardware & Quality
    ↓
T4 / ~16 GB detected
    ↓
OmniVoice → cuda:0
Whisper   → cpu
    ↓
workspace default = BALANCED
```

Dual T4 Kaggle:

```text
Hardware & Quality
    ↓
2 × T4 / ~15 GB each detected
    ↓
OmniVoice → cuda:0
Whisper   → cuda:1
    ↓
workspace default = BALANCED
```

Important final projects can still override the workspace default to SAFE; preview/test projects can use FAST.

Example dual-T4 launch:

```bash
omnivoice-project-studio \
  --device cuda:0 \
  --asr-model openai/whisper-small.en \
  --asr-device cuda:1 \
  ...
```

## Architectural rule

A preset is a generation policy object, not a UI-only label. The same policy controls:

- decoder generation config;
- robust retry depth;
- adaptive quality configuration;
- Project Studio generation;
- Project Queue generation through the shared controller.

This keeps CLI/API integration possible without duplicating Gradio-specific logic.
