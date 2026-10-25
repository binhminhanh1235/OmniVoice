## 2024-05-24 - String Iteration Performance
**Learning:** In Python, `sum(map(fn, string))` is significantly faster (~30%+) than `sum(fn(c) for c in string)` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path.
**Action:** Use `map` instead of generator expressions for `sum` operations on strings when mapping a single function.

## 2024-10-25 - Regex String Iteration Performance
**Learning:** In Python, replacing nested generator expressions checking character ranges like `any(any("\u4e00" <= c <= "\u9fff" for c in n) for n in text_list)` with a compiled regex check `any(_ZH_PATTERN.search(n) for n in text_list)` yields a roughly 10x performance improvement. Pushing the iteration to the C level provides immense speedups for string scanning. Avoid mapping regex matches to boolean, e.g., `bool(_ZH_PATTERN.search(n))` since `any()` implicitly evaluates the truthiness of match objects vs `None` anyway.
**Action:** When searching strings for character matches or properties, compile a regex rather than using generator loops.
