#!/usr/bin/env python3

import numpy as np

from omnivoice.robust_longform import (
    RobustLongFormConfig,
    RobustLongFormGenerator,
    clean_tts_text,
    score_transcript,
    semantic_chunk_text,
)


def test_clean_tts_text_decodes_html_entities():
    text = "Patterns that reject truth. &#x20;\n\nPatterns that avoid responsibility."
    cleaned = clean_tts_text(text)
    assert "&#x20;" not in cleaned
    assert cleaned == (
        "Patterns that reject truth.\n\nPatterns that avoid responsibility."
    )


def test_semantic_chunker_does_not_split_normal_sentence_at_commas():
    text = (
        "This is not about refusing kindness to someone who is sick, grieving, "
        "poor, overwhelmed, or genuinely trying to rebuild their life."
    )
    chunks = semantic_chunk_text(text, max_words=28, max_chars=220)
    assert [chunk.text for chunk in chunks] == [text]


def test_semantic_chunker_preserves_short_rhetorical_sentences():
    text = (
        "Love is not unlimited access.\n\n"
        "Forgiveness is not instant trust.\n\n"
        "This is about repeated patterns."
    )
    chunks = semantic_chunk_text(text)
    assert [chunk.text for chunk in chunks] == [
        "Love is not unlimited access.",
        "Forgiveness is not instant trust.",
        "This is about repeated patterns.",
    ]
    assert chunks[0].paragraph_end is True
    assert chunks[1].paragraph_end is True
    assert chunks[2].paragraph_end is False


def test_semantic_chunker_keeps_abbreviation_inside_sentence():
    text = "Dr. Smith explained the result. Then everyone left."
    chunks = semantic_chunk_text(text)
    assert [chunk.text for chunk in chunks] == [
        "Dr. Smith explained the result.",
        "Then everyone left.",
    ]


def test_semantic_chunker_splits_overlong_sentence_without_losing_words():
    text = (
        "One two three four five six seven eight, nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen, seventeen eighteen nineteen twenty."
    )
    chunks = semantic_chunk_text(text, max_words=8, max_chars=80)
    rebuilt_words = " ".join(chunk.text for chunk in chunks).replace(",", "").replace(
        ".", ""
    ).split()
    original_words = text.replace(",", "").replace(".", "").split()
    assert rebuilt_words == original_words
    assert len(chunks) > 1


def test_score_transcript_accepts_minor_asr_variation():
    config = RobustLongFormConfig(verify_with_asr=False)
    score = score_transcript(
        "This is not about becoming suspicious of everyone who needs help.",
        "This is not about becoming suspicious of everyone who needs help",
        config,
    )
    assert score.accepted is True
    assert score.critical_missing == []


def test_score_transcript_rejects_missing_negation():
    config = RobustLongFormConfig()
    score = score_transcript(
        "Forgiveness is not instant trust.",
        "Forgiveness is instant trust.",
        config,
    )
    assert score.accepted is False
    assert score.critical_missing == ["not"]


def test_score_transcript_rejects_extra_repetition():
    config = RobustLongFormConfig()
    score = score_transcript(
        "Patterns that reject truth and avoid responsibility.",
        "Patterns that reject truth reject truth and avoid responsibility.",
        config,
    )
    assert score.accepted is False
    assert "reject truth" in score.extra_repetitions


class _FakeModel:
    sampling_rate = 10

    def __init__(self):
        self._asr_pipe = object()
        self.generate_calls = 0
        self.transcripts = [
            "Forgiveness is instant trust.",
            "Forgiveness is not instant trust.",
        ]

    def generate(self, text, generation_config=None, **kwargs):
        del text, generation_config, kwargs
        self.generate_calls += 1
        return [np.ones(10, dtype=np.float32) * self.generate_calls]

    def transcribe(self, audio):
        del audio
        return self.transcripts.pop(0)

    def load_asr_model(self, model_name=None, device=None):
        del model_name, device
        self._asr_pipe = object()


def test_generator_retries_chunk_when_negation_is_missing():
    model = _FakeModel()
    config = RobustLongFormConfig(
        max_retries=2,
        max_split_depth=0,
        normalize_chunk_rms=False,
    )
    generator = RobustLongFormGenerator(model, config)
    result = generator.generate("Forgiveness is not instant trust.")

    assert model.generate_calls == 2
    assert result.all_verified is True
    assert result.reports[0].attempts == 2
    assert result.reports[0].transcript == "Forgiveness is not instant trust."
