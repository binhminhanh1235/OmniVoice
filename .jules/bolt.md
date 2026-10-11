# Bolt's Journal

## 2024-10-10 - Regex vs Python Generators for Long Strings
**Learning:** In `omnivoice/utils/text.py`, `add_punctuation` checked for Chinese characters using a generator comprehension inside `any()`: `any("\u4e00" <= char <= "\u9fff" for char in text)`. For very long text inputs without Chinese characters, this iterates the entire string in Python, which is extremely slow (O(N) in Python bytecodes). We replaced it with a pre-compiled Regular Expression `_CJK_RE = re.compile(r"[\u4e00-\u9fff]")` and `bool(_CJK_RE.search(text))`. The C-optimized regex search is over 12x faster.
**Action:** When searching for character classes (like CJK characters) inside long strings, prefer pre-compiled `re` patterns over Python-level string iteration (like list comprehensions or generators) for a massive speedup.
