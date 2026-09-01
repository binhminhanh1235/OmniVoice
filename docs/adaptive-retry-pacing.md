# Adaptive Retry and Pacing Guard

Design notes for the next Project Studio quality layer.

This branch adds two safeguards on top of `RobustLongFormGenerator`:

1. **Adaptive retry** classifies a failed candidate and changes the next action instead of blindly repeating the same generation settings.
2. **Pacing guard** rejects candidates whose speaking rate is implausibly fast or whose local speech-rate spike is much faster than the rest of the same chunk.

The guard is intentionally implemented in the robust wrapper, not in the OmniVoice decoder itself.
