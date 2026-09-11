# OmniVoice Studio Production Acceptance

This runbook defines the evidence required before calling a hosted-runtime optimization production-ready. It covers the verified persistent Colab/Kaggle startup cache and Lazy CPU ASR Startup behavior.

## 1. Acceptance principles

1. Compare the same exact OmniVoice source revision.
2. Resolve exact model and ASR revisions, not floating cache state.
3. Keep active generation on local SSD.
4. Treat Drive/Kaggle Dataset/cloud storage as persistence boundaries.
5. Do not fabricate or extrapolate hosted timing.
6. Keep target-only inference outside this acceptance. It remains experimental.

## 2. Required startup evidence

The production bootstrap writes:

```text
startup-cache-evidence.json
```

The file records the exact package revision, cache fast-path state, and measured bootstrap duration. A useful acceptance pair contains:

```text
cold.json
warm.json
```

Both files must come from the same exact `package_ref`.

## 3. Cold run

A cold run means the compatible persistent startup cache is genuinely unavailable for the selected package/model/ASR fingerprint.

Before recording a cold sample, confirm that you are not reusing an already-populated compatible cache namespace.

After the bootstrap completes, preserve the generated evidence as `cold.json`.

Do not delete unrelated project data just to create a cold cache measurement.

## 4. Warm run

Restart the hosted runtime and attach or mount the cache produced by the cold run.

The warm sample must report:

```text
resource_fast_path = true
wheel_fast_path = true
```

Preserve that session's startup evidence as `warm.json`.

## 5. Cache acceptance command

Run the repository acceptance script:

```bash
python scripts/hosted_cache_acceptance.py cold.json warm.json
```

PASS requires:

```text
cold.package_ref == warm.package_ref
warm.resource_fast_path == true
warm.wheel_fast_path == true
warm.bootstrap_seconds < cold.bootstrap_seconds
```

The command prints the measured cold/warm seconds and the measured improvement for those two real samples. It does not create a synthetic benchmark.

## 6. Colab procedure

Recommended notebook:

```text
notebooks/OmniVoice_Project_Studio_Colab.ipynb
```

Runtime layout:

```text
/content/OmniVoiceStudio
    active project/render workspace

/content/drive/MyDrive/OmniVoiceStudio
    persistent project mirror
    persistent startup cache
    acceptance evidence archive
```

Production rules:

- mount Drive before bootstrap;
- restore project data to local SSD;
- render locally;
- mirror project state back to Drive;
- keep startup evidence outside the normal project mirror overwrite path.

The notebook acceptance cell supports `ACCEPTANCE_SAMPLE = "cold"` or `"warm"`. It stores evidence under an exact-revision acceptance directory. When both samples exist, the notebook downloads `scripts/hosted_cache_acceptance.py` from the same exact OmniVoice revision and executes it.

## 7. Kaggle procedure

Recommended notebook:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

Runtime layout:

```text
/kaggle/working/OmniVoiceStudio
    active project/render workspace

/kaggle/working/OmniVoiceStartupCache
    cache export to save/version as a Kaggle Dataset

/kaggle/input/omnivoice-startup-cache
    attached read-only cache Dataset on the next session
```

Cold run:

1. start without a compatible attached startup-cache Dataset;
2. bootstrap and record `cold` evidence;
3. save/version `/kaggle/working/OmniVoiceStartupCache` as the `omnivoice-startup-cache` Dataset.

Warm run:

1. attach the saved Dataset at `/kaggle/input/omnivoice-startup-cache`;
2. restart the notebook from the top;
3. record `warm` evidence;
4. run the automatic acceptance comparison when both samples are available.

The notebook copies prior acceptance evidence from the attached cache Dataset into the new writable export directory before writing the warm sample.

## 8. Lazy CPU ASR acceptance

### CPU ASR

When Studio is launched with:

```text
--asr-device cpu
```

startup must defer Whisper pipeline construction.

Expected startup evidence:

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

At this point the server/UI/API/MCP should be ready without a constructed CPU ASR pipeline.

Trigger one real operation that requires ASR, for example:

- a Voice Doctor transcription;
- a clone prompt without supplied reference transcript;
- robust long-form verification.

Expected first-use log:

```text
Initializing ASR on first use: model=... device=cpu
```

Subsequent ASR requests should reuse the same model-scoped pipeline rather than initialize a new one.

The exact-head CI safety gate separately verifies single initialization, concurrent first-use, reuse, and fail-first retry using a fake loader so CI never downloads a real ASR model.

### Explicit accelerator ASR

When ASR is explicitly placed on an accelerator, for example:

```text
--asr-device cuda:1
```

ASR remains eager by design. This is the normal dual-T4 Kaggle mapping:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper ASR verification
```

Do not mark this as a Lazy CPU ASR failure. The optimization intentionally changes CPU startup only.

## 9. Functional regression checklist

Before production acceptance, verify:

- Studio UI starts;
- `/health` responds;
- REST/OpenAPI remains available;
- MCP endpoint remains available;
- project parsing works;
- Voice Library remains readable;
- preview works;
- project generation works;
- robust ASR verification works when enabled;
- resume skips completed work;
- failed chunk regeneration remains targeted;
- export works;
- no secrets are written to repository/project artifacts.

CI must also keep the robust long-form/project regression and notebook JSON validation green on the exact head and exact post-merge master SHA.

## 10. Result record template

Record evidence without rounding away the raw values:

```text
Environment: Colab | Kaggle
Runtime/GPU: ...
Package ref: <40-char SHA>
Model revision: <40-char SHA>
ASR revision: <40-char SHA>
Cold bootstrap_seconds: ...
Warm bootstrap_seconds: ...
Warm resource_fast_path: true|false
Warm wheel_fast_path: true|false
Acceptance script: PASS|FAIL
ASR placement: cpu|cuda:1|...
Lazy CPU ASR startup observed: yes|no|not-applicable
First-use ASR observed: yes|no|not-applicable
Notes: ...
```

## 11. What this acceptance does not prove

Persistent startup cache acceptance proves safe reuse and real startup improvement for the measured hosted environment. Lazy CPU ASR acceptance proves deferred CPU pipeline construction and first-use behavior.

Neither proves that experimental target-only inference is safe. Target-only inference still requires separate real-GPU speed, projection/output equivalence, voice-clone quality, ASR quality, pacing, perceptual A/B, long-form, memory, training, and API acceptance before production use.