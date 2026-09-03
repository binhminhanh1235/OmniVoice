#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Experimental inference-only optimizations for the ``optimize`` branch.

The base decoder computes ``audio_heads`` for every hidden-state position and
then keeps only target-audio logits.  This engine keeps the LLM forward pass
identical but gathers only conditional/unconditional target hidden states before
running ``audio_heads``.  It also delays fp32 conversion until after target
logits are sliced.

The class intentionally lives beside, rather than inside, the stable model so
A/B benchmarking can prove speed/memory gains before the optimization is folded
into the default decoder.
"""

from __future__ import annotations

import logging
import math
from typing import List, Sequence

import torch

from omnivoice.models.omnivoice import (
    GenerationTask,
    OmniVoice,
    OmniVoiceGenerationConfig,
    _get_time_steps,
    _gumbel_sample,
)

logger = logging.getLogger(__name__)


def gather_target_hidden_states(
    hidden_states: torch.Tensor,
    c_lens: Sequence[int],
    target_lens: Sequence[int],
) -> torch.Tensor:
    """Gather only target positions from conditional/unconditional hidden states.

    ``hidden_states`` has batch layout ``[cond_0..cond_B-1, uncond_0..uncond_B-1]``.
    Conditional targets occupy the final ``target_len`` positions of each real
    conditional sequence.  Unconditional targets start at position zero.
    """

    batch_size = len(c_lens)
    if batch_size == 0 or len(target_lens) != batch_size:
        raise ValueError("c_lens and target_lens must be non-empty and aligned")
    if hidden_states.ndim != 3:
        raise ValueError("hidden_states must have shape [2B, sequence, hidden]")
    if hidden_states.size(0) != 2 * batch_size:
        raise ValueError("hidden_states batch must contain conditional + unconditional rows")

    max_target_len = max(int(value) for value in target_lens)
    if max_target_len < 1:
        raise ValueError("target lengths must be >= 1")

    gathered = hidden_states.new_zeros(
        (2 * batch_size, max_target_len, hidden_states.size(-1))
    )
    for index, (c_len_raw, t_len_raw) in enumerate(zip(c_lens, target_lens)):
        c_len = int(c_len_raw)
        t_len = int(t_len_raw)
        if t_len < 1 or c_len < t_len or c_len > hidden_states.size(1):
            raise ValueError(
                f"invalid lengths for item {index}: c_len={c_len}, target_len={t_len}"
            )
        gathered[index, :t_len] = hidden_states[
            index, c_len - t_len : c_len
        ]
        gathered[batch_size + index, :t_len] = hidden_states[
            batch_size + index, :t_len
        ]
    return gathered


class OptimizedOmniVoice(OmniVoice):
    """OmniVoice inference engine with target-only audio projection."""

    def _forward_target_logits(
        self,
        *,
        input_ids: torch.Tensor,
        audio_mask: torch.Tensor,
        attention_mask: torch.Tensor,
        c_lens: Sequence[int],
        target_lens: Sequence[int],
    ) -> torch.Tensor:
        """Run the normal LLM context forward, then project target positions only."""

        inputs_embeds = self._prepare_embed_inputs(input_ids, audio_mask)
        llm_outputs = self.llm(
            inputs_embeds=inputs_embeds,
            attention_mask=attention_mask,
            return_dict=True,
        )
        target_hidden = gather_target_hidden_states(
            llm_outputs[0], c_lens, target_lens
        )

        batch_size, target_seq_len, _ = target_hidden.shape
        logits_flat = self.audio_heads(target_hidden)
        return logits_flat.view(
            batch_size,
            target_seq_len,
            self.config.num_audio_codebook,
            self.config.audio_vocab_size,
        ).permute(0, 2, 1, 3)

    def _generate_iterative(
        self, task: GenerationTask, gen_config: OmniVoiceGenerationConfig
    ) -> List[torch.Tensor]:
        """N-step decoding with target-only projection and target-only fp32 cast."""

        B = task.batch_size

        for i in range(B):
            logger.debug(
                "Item %d — text: %s | ref_text: %s | instruct: %s | lang: %s | target_tokens: %d",
                i,
                task.texts[i],
                task.ref_texts[i],
                task.instructs[i],
                task.langs[i],
                task.target_lens[i],
            )

        inputs_list = [
            self._prepare_inference_inputs(
                task.texts[i],
                task.target_lens[i],
                task.ref_texts[i],
                task.ref_audio_tokens[i],
                task.langs[i],
                task.instructs[i],
                gen_config.denoise,
            )
            for i in range(B)
        ]

        c_lens = [inp["input_ids"].size(2) for inp in inputs_list]
        max_c_len = max(c_lens)
        pad_id = self.config.audio_mask_id

        batch_input_ids = torch.full(
            (2 * B, self.config.num_audio_codebook, max_c_len),
            pad_id,
            dtype=torch.long,
            device=self.device,
        )
        batch_audio_mask = torch.zeros(
            (2 * B, max_c_len), dtype=torch.bool, device=self.device
        )
        batch_attention_mask = torch.zeros(
            (2 * B, 1, max_c_len, max_c_len), dtype=torch.bool, device=self.device
        )

        for i, inp in enumerate(inputs_list):
            c_len, u_len = c_lens[i], task.target_lens[i]

            batch_input_ids[i, :, :c_len] = inp["input_ids"]
            batch_audio_mask[i, :c_len] = inp["audio_mask"]
            batch_attention_mask[i, :, :c_len, :c_len] = True

            batch_input_ids[B + i, :, :u_len] = inp["input_ids"][..., -u_len:]
            batch_audio_mask[B + i, :u_len] = inp["audio_mask"][..., -u_len:]
            batch_attention_mask[B + i, :, :u_len, :u_len] = True
            if max_c_len > u_len:
                pad_diag = torch.arange(u_len, max_c_len, device=self.device)
                batch_attention_mask[B + i, :, pad_diag, pad_diag] = True

        tokens = torch.full(
            (B, self.config.num_audio_codebook, max(task.target_lens)),
            self.config.audio_mask_id,
            dtype=torch.long,
            device=self.device,
        )

        timesteps = _get_time_steps(
            t_start=0.0,
            t_end=1.0,
            num_step=gen_config.num_step,
            t_shift=gen_config.t_shift,
        ).tolist()
        schedules = []
        for t_len in task.target_lens:
            total_mask = t_len * self.config.num_audio_codebook
            rem = total_mask
            sched = []
            for step in range(gen_config.num_step):
                num = (
                    rem
                    if step == gen_config.num_step - 1
                    else min(
                        math.ceil(
                            total_mask * (timesteps[step + 1] - timesteps[step])
                        ),
                        rem,
                    )
                )
                sched.append(int(num))
                rem -= int(num)
            schedules.append(sched)

        layer_ids = torch.arange(
            self.config.num_audio_codebook, device=self.device
        ).view(1, -1, 1)

        for step in range(gen_config.num_step):
            # Shape: [2B, C, max_target_len, vocab]. Unlike the base decoder,
            # conditioning/reference positions never pass through audio_heads.
            batch_logits = self._forward_target_logits(
                input_ids=batch_input_ids,
                audio_mask=batch_audio_mask,
                attention_mask=batch_attention_mask,
                c_lens=c_lens,
                target_lens=task.target_lens,
            )

            for i in range(B):
                k = schedules[i][step]
                if k <= 0:
                    continue

                t_len = task.target_lens[i]
                # Convert only the target slices used for guidance/scoring.
                c_logits = batch_logits[i : i + 1, :, :t_len, :].to(torch.float32)
                u_logits = batch_logits[B + i : B + i + 1, :, :t_len, :].to(
                    torch.float32
                )

                pred_tokens, scores = self._predict_tokens_with_scoring(
                    c_logits, u_logits, gen_config
                )
                scores = scores - (layer_ids * gen_config.layer_penalty_factor)

                if gen_config.position_temperature > 0.0:
                    scores = _gumbel_sample(scores, gen_config.position_temperature)

                sample_tokens = tokens[i : i + 1, :, :t_len]
                scores.masked_fill_(
                    sample_tokens != self.config.audio_mask_id, -float("inf")
                )

                _, topk_idx = torch.topk(scores.flatten(), k)
                flat_tokens = sample_tokens.flatten()
                flat_tokens[topk_idx] = pred_tokens.flatten()[topk_idx]
                sample_tokens.copy_(flat_tokens.view_as(sample_tokens))

                tokens[i : i + 1, :, :t_len] = sample_tokens
                c_len = c_lens[i]
                batch_input_ids[i : i + 1, :, c_len - t_len : c_len] = sample_tokens
                batch_input_ids[B + i : B + i + 1, :, :t_len] = sample_tokens

        return [tokens[i, :, : task.target_lens[i]] for i in range(B)]
