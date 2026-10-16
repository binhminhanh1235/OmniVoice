## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-05-24 - Text Scanning Optimization
**Learning:** In Python, using a pre-compiled regex (e.g., `_CJK_RE.search(text)`) for scanning text (like checking if any character belongs to a certain range) is significantly faster (~13x) than using generator comprehensions like `any("\u4e00" <= char <= "\u9fff" for char in text)`. This happens because the regex engine executes down at the C level.
**Action:** When scanning strings for specific character ranges or patterns, especially on the hot path, prefer compiled `re` objects over Python-level iterations.
