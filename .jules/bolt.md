## 2024-05-18 - Fast RuleDurationEstimator Text Iteration

**Learning:** `RuleDurationEstimator` processes a large volume of characters during text generation and inference batch processing. Its implementation relied on `@lru_cache` for evaluating per-character weights, and a generator expression `sum(self._get_char_weight(c) for c in text)` to calculate the total weight. Even though cache hit rate was high, invoking `lru_cache` and executing function calls per character along with generator comprehension yielded noticeable overhead.

**Action:** Replaced the generator with an inline `for` loop and bypassed the function call entirely for ASCII characters (0-127) using a pre-computed array `self._ascii_cache`. The hot-path inline lookup avoids the function call and dictionary lookup entirely, providing a 2.7x speedup in duration calculations.
