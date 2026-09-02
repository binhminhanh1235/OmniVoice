# Kaggle dual-T4 stale-kernel note

If a Kaggle notebook upgrades OmniVoice in a Python kernel that already imported `omnivoice.hardware_quality`, Python may keep the old module object in memory even though the package on disk has been updated.

For dual-T4 notebooks, the runtime mapping is therefore derived directly from CUDA device count:

```text
cuda:0 = OmniVoice TTS
cuda:1 = Whisper ASR when a second GPU exists
```

The Hardware & Quality detector is still used for preset recommendations, but the notebook reloads the detector module after installation and does not allow a stale `recommended_asr_device=cpu` value to leave the second T4 idle.

A fresh Kaggle session is still recommended after substantial package upgrades.
