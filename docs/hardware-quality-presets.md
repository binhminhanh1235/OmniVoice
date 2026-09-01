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

For a common Google Colab Tesla T4 / 16 GB runtime, Studio recommends:

```text
quality preset = BALANCED
ASR device     = cpu
```

Keeping Whisper on CPU avoids competing with OmniVoice for T4 VRAM.

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

```text
Hardware & Quality
    ↓
T4 / ~16 GB detected
    ↓
workspace default = BALANCED
    ↓
important final project → override SAFE
preview/test project     → override FAST
    ↓
Project Queue
```

ASR should normally remain on CPU on T4:

```bash
omnivoice-project-studio \
  --asr-device cpu \
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
