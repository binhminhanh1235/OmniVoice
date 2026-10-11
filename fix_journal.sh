rm -f .jules/bolt.md
mkdir -p .jules
echo "## 2024-05-24 - String Iteration Performance" >> .jules/bolt.md
echo "**Learning:** In Python, \`sum(map(fn, string))\` is significantly faster (~30%+) than \`sum(fn(c) for c in string)\` because it pushes the iteration loop down to C level instead of creating a Python generator. This is a critical learning for NLP/Text-to-Speech codebases where iterating over long text strings is a hot path." >> .jules/bolt.md
echo "**Action:** Use \`map\` instead of generator expressions for \`sum\` operations on strings when mapping a single function." >> .jules/bolt.md
