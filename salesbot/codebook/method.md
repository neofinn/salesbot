# Method: how to write code that works the first time
Use this every time, whatever the language. Small models succeed by following steps, not by guessing.

## Steps
1. Restate the task in one line. List inputs, outputs and edge cases (empty, zero, huge, missing, wrong type).
2. Pick the simplest approach that fully works. Prefer the standard library over new dependencies.
3. Write the code in small functions (each does one thing, under ~30 lines). Name things for what they mean.
4. Handle errors at the edges: validate input, check results of I/O and network calls, never swallow errors silently.
5. Self-check before answering, line by line:
   - Every variable is defined before use; every import is used and exists.
   - Every opened thing is closed (files, connections); every promise is awaited.
   - Brackets, quotes and indentation balance. No placeholder like TODO or "..." left in code.
   - Off-by-one: loop bounds, slicing ends, 0- vs 1-based indexes.
   - The code does exactly what was asked, nothing more.
6. Give a tiny usage example or test that proves it works.

## Output rules
- Return complete, runnable code: every file in full, with its path. Never "rest unchanged".
- One fenced code block per file, with the language tag. No prose inside code blocks.
- If something is unknown (an API key, a URL, a schema), use a clearly named constant at the top and say so.
- Never invent library functions. If unsure a function exists, use a simpler construct you are sure of.
- Keep secrets out of code: read them from environment variables or config.

## Debugging
Read the error message fully. Find the exact line. Form one hypothesis, change one thing, re-run.
Common causes: wrong type (string vs number), undefined/None, wrong path, async not awaited, wrong indentation.

## Security basics (all languages)
- Never build SQL, shell commands or HTML by string concatenation with user input: use parameters/escaping.
- Validate and limit all input (length, type, range). Use HTTPS. Hash passwords (bcrypt/argon2), never store plain.
- Least privilege: request only the permissions and scopes the feature needs.
