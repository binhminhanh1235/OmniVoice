## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-10-21 - CJK Character Checking Performance
**Learning:** In Python, checking if a string contains characters from a specific unicode block (like CJK `\u4e00-\u9fff`) using a generator expression like `any("\u4e00" <= char <= "\u9fff" for char in text)` is significantly slower (~10x) than using a compiled regular expression `re.compile(r"[\u4e00-\u9fff]").search(text)`. The python generator creates significant overhead on long strings or many small strings compared to the C-level execution of the regex engine.
**Action:** Always prefer compiled regex searches `_CJK_RE.search(text)` over generator expressions for checking character ranges/classes in strings, especially in hot paths like text normalizers or punctuation handling.
