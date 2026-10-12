## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.
## 2024-10-12 - Joining string characters directly
**Learning:** Using `" ".join(string)` is about ~40% faster than `" ".join([x for x in string])` because it avoids building an intermediate list in Python and instead directly iterates over the characters at the C level.
**Action:** Always use `" ".join(string)` when you just need to intersperse characters with spaces.
