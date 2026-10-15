## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2026-10-15 - Fast Line Counting in Large Files
**Learning:** Using a generator comprehension `sum(buf.count(b"\n") for buf in iter(lambda: f.read(1 << 20), b""))` to count lines in large files introduces significant Python overhead compared to a simple `while` loop `while buf := f.read(1 << 20): count += buf.count(b"\n")`. The `while` loop approach avoids creating and consuming a Python generator, making it noticeably faster for IO-bound chunk processing.
**Action:** Use a `while` loop with assignment expression (`:=`) instead of generator comprehensions when performing simple aggregations over chunks read from files.
