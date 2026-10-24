## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-05-24 - String Check Performance
**Learning:** In Python, using a compiled regex `bool(regex.search(string))` is significantly faster (~10x) than using a generator expression like `any("a" <= char <= "z" for char in string)` to check if a string contains characters in a certain range.
**Action:** Use compiled regular expressions for character existence checks instead of generator expressions.
