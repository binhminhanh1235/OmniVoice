## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-10-18 - CJK Character Checking Performance
**Learning:** Using `re.compile(r"[\u4e00-\u9fff]").search(text)` is ~9x faster than using `any("\u4e00" <= char <= "\u9fff" for char in text)` for checking if a string contains Chinese/CJK characters. Python generator expressions and character-by-character iterations are extremely slow compared to the optimized C implementation of the `re` module.
**Action:** When scanning strings for specific character ranges or subsets, always prefer compiled regular expressions over `any()` with generator expressions.
