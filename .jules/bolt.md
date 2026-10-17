## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2025-03-05 - [Python CJK Detection]
**Learning:** Checking character ranges with a generator expression like `any("\u4e00" <= char <= "\u9fff" for char in text)` is exceptionally slow (O(n) time with huge constant overhead). Regex is implemented in C and runs up to 6x faster.
**Action:** Use pre-compiled regex `re.compile(r"[\u4e00-\u9fff]")` instead of `any()` generators for language/character detection.
