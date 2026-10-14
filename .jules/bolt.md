## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2025-02-12 - Regex vs Generator Expression Performance for Character Presence
**Learning:** Checking for the presence of specific characters (like Chinese/CJK ranges) using `bool(re.compile(r"[\u4e00-\u9fff]").search(text))` is significantly faster (~10x for English, ~3x for Chinese text in my benchmarks) than using a Python generator expression like `any("\u4e00" <= char <= "\u9fff" for char in text)`. This is because the regex engine runs entirely in C, avoiding the overhead of byte-code evaluation and object creation for each character in the string. For lists of strings, `re.search("".join(list))` was also ~7x faster than a nested generator expression `any(any(...) for n in list)`.
**Action:** When performing character range checks or simple substring searches to determine language or properties of text, prefer pre-compiled regular expressions over Python generator expressions.
