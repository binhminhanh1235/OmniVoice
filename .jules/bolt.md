## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-05-24 - String Character Detection Performance
**Learning:** In Python, replacing a python-level generator expression like `any(lower <= c <= upper for c in text)` with a compiled regex like `bool(re.compile(r'[lower-upper]').search(text))` yields a massive (~10x+) speedup because it moves string iteration into the C-based regex engine.
**Action:** Use compiled regular expressions for character range detection in strings instead of Python generators.
