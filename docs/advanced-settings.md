# Advanced Settings

Project Studio exposes **7. Advanced Settings** for optional per-project tuning.

The existing **SAFE / BALANCED / FAST** quality preset remains the primary configuration. Advanced Settings are disabled by default. When disabled, generation behaves exactly as before: the quality preset chooses decoder/retry effort and Voice Style Bank profiles can choose their normal per-style speed.

## Controls

| Setting | Default custom value | Allowed range | Effect |
| --- | ---: | ---: | --- |
| Speed | 1.00x | 0.50–1.50x | Global speaking-speed override for the project |
| Diffusion steps | 32 | 16–64 | More steps generally cost more GPU time |
| Guidance scale | 2.0 | 0.5–5.0 | Generation guidance strength |
| Position temperature | 1.0 | 0.20–2.00 | Lower values are generally more deterministic |
| Max retries | 3 | 1–6 | Retry budget for failed chunk verification |
| Maximum WER | 0.18 | 0.01–0.50 | Lower values make ASR verification stricter |
| Chunk pause | 320 ms | 0–2000 ms | Base pause inserted between robust chunks |
| Paragraph pause | 460 ms | 0–3000 ms | Base paragraph pause |

## Speed and style tags

When **Enable custom advanced overrides** is OFF, `[WARM]`, `[SOFT]`, and other style profiles retain their normal speed behavior.

When custom overrides are ON, the **Speed** value is supplied explicitly to generation and becomes the same base speed for all beats. Voice Style Bank variant selection still works, so `[WARM]` can still select a WARM reference, but the style profile no longer changes speed independently.

## Persistence

Advanced settings are stored under `advanced_settings` in each project's `studio.json`. They are preserved by later Generate/Resume operations.

The same project settings are used by:

- Generate / Resume;
- targeted chunk regeneration;
- Project Queue.

This means a queued project keeps using its saved advanced tuning without requiring the Advanced Settings tab to stay open.

## Reset

Use **Reset to preset defaults** to remove the project's `advanced_settings` block. The project immediately returns to its effective Hardware & Quality preset and normal style-profile speed behavior.
