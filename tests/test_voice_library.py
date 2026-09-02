from pathlib import Path

import torch

from omnivoice import VoiceClonePrompt
from omnivoice.voice_library import VoiceLibrary


def _prompt(text: str = "hello world") -> VoiceClonePrompt:
    return VoiceClonePrompt(
        ref_audio_tokens=torch.arange(24, dtype=torch.long).reshape(3, 8),
        ref_text=text,
        ref_rms=0.125,
    )


def test_save_and_load_prompt(tmp_path: Path):
    library = VoiceLibrary(tmp_path / "voices")
    entry = library.save_prompt("Warm Narrator", _prompt())

    assert entry.name == "Warm Narrator"
    assert library.voice_names() == ["Warm Narrator"]
    assert library.variants("Warm Narrator") == ["DEFAULT"]

    loaded = library.load_prompt("Warm Narrator")
    assert loaded.ref_text == "hello world"
    assert loaded.ref_rms == 0.125
    assert torch.equal(loaded.ref_audio_tokens, _prompt().ref_audio_tokens)


def test_voice_variants_and_reference_copy(tmp_path: Path):
    reference = tmp_path / "soft.wav"
    reference.write_bytes(b"fake-reference")
    library = VoiceLibrary(tmp_path / "voices")

    library.save_prompt("David", _prompt("neutral"), variant="DEFAULT")
    entry = library.save_prompt(
        "David",
        _prompt("soft"),
        variant="SOFT",
        language="en",
        reference_audio=reference,
    )

    assert sorted(entry.variants) == ["DEFAULT", "SOFT"]
    assert entry.variants["SOFT"].language == "en"
    assert entry.variants["SOFT"].reference_file is not None
    copied = tmp_path / "voices" / "david" / entry.variants["SOFT"].reference_file
    assert copied.read_bytes() == b"fake-reference"
    assert library.load_prompt("David", "SOFT").ref_text == "soft"


def test_create_from_reference_uses_model_once(tmp_path: Path):
    reference = tmp_path / "ref.wav"
    reference.write_bytes(b"audio")

    class FakeModel:
        def __init__(self):
            self.calls = 0

        def create_voice_clone_prompt(self, **kwargs):
            self.calls += 1
            assert kwargs["ref_audio"] == str(reference)
            assert kwargs["ref_text"] == "exact words"
            return _prompt("exact words")

    model = FakeModel()
    library = VoiceLibrary(tmp_path / "voices")
    library.create_from_reference(
        model,
        name="Narrator",
        reference_audio=reference,
        ref_text="exact words",
    )

    assert model.calls == 1
    assert library.load_prompt("Narrator").ref_text == "exact words"


def test_auto_style_variant_selects_exact_match(tmp_path: Path):
    library = VoiceLibrary(tmp_path / "voices")
    library.save_prompt("David", _prompt("default"), variant="DEFAULT")
    library.save_prompt("David", _prompt("warm"), variant="WARM")
    library.save_prompt("David", _prompt("soft"), variant="SOFT")

    warm = library.resolve_prompt("David", style="WARM", preferred_variant="AUTO")
    soft = library.resolve_prompt("David", style="SOFT", preferred_variant="AUTO")

    assert warm.variant == "WARM"
    assert warm.prompt.ref_text == "warm"
    assert not warm.used_fallback
    assert soft.variant == "SOFT"
    assert soft.prompt.ref_text == "soft"
    assert not soft.used_fallback


def test_style_variant_has_deterministic_fallback_chain(tmp_path: Path):
    library = VoiceLibrary(tmp_path / "voices")
    library.save_prompt("David", _prompt("default"), variant="DEFAULT")
    library.save_prompt("David", _prompt("warm"), variant="WARM")

    emphasize = library.resolve_prompt(
        "David",
        style="EMPHASIZE",
        preferred_variant="AUTO",
    )
    soft = library.resolve_prompt(
        "David",
        style="SOFT",
        preferred_variant="AUTO",
    )

    assert emphasize.variant == "WARM"
    assert emphasize.prompt.ref_text == "warm"
    assert emphasize.used_fallback
    assert soft.variant == "DEFAULT"
    assert soft.prompt.ref_text == "default"
    assert soft.used_fallback


def test_explicit_variant_locks_style_bank(tmp_path: Path):
    library = VoiceLibrary(tmp_path / "voices")
    library.save_prompt("David", _prompt("default"), variant="DEFAULT")
    library.save_prompt("David", _prompt("warm"), variant="WARM")

    resolution = library.resolve_prompt(
        "David",
        style="WARM",
        preferred_variant="DEFAULT",
    )

    assert resolution.variant == "DEFAULT"
    assert resolution.prompt.ref_text == "default"
    assert not resolution.used_fallback
    assert library.variant_choices("David") == ["AUTO", "DEFAULT", "WARM"]
