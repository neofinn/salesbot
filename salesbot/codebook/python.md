# Python (3.10+)
## Rules
- 4-space indent, snake_case for functions/variables, PascalCase for classes, UPPER_CASE constants.
- Use f-strings, `pathlib.Path`, `with open(...)` (auto-close), type hints on functions.
- Prefer list/dict comprehensions for simple transforms; plain loops when there is logic.
- `if __name__ == "__main__":` guard for scripts. `None` checks with `is None`.
- Mutable default args are a bug: `def f(x=None): x = x or []`.
## Templates
```python
import json, logging, sys
from pathlib import Path

log = logging.getLogger(__name__)

def load_json(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("missing %s", path); return {}

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: app.py FILE", file=sys.stderr); return 2
    data = load_json(argv[1])
    print(len(data)); return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```
HTTP with httpx (or requests): `r = httpx.get(url, timeout=20); r.raise_for_status(); data = r.json()`.
Async: `async def f(): async with httpx.AsyncClient() as c: r = await c.get(url)`; run with `asyncio.run(f())`.
Dataclass: `@dataclass class User: name: str; age: int = 0`.
CLI: `argparse.ArgumentParser(); p.add_argument("--n", type=int, default=10)`.
SQLite: `con = sqlite3.connect("db.sqlite"); con.execute("SELECT * FROM t WHERE id = ?", (id,))`.
FastAPI: `app = FastAPI(); @app.get("/items/{id}") async def get(id: int): return {"id": id}`.
Tests (pytest): `def test_add(): assert add(2, 3) == 5`; run `pytest -q`.
## Pitfalls
- `==` vs `is`; integer division `//`; `range(n)` stops at n-1; dict iteration order is insertion order.
- Don't catch bare `except:`; catch specific exceptions. Don't modify a list while iterating it.
- Timezones: use `datetime.now(timezone.utc)`. Floats for money are wrong: use `Decimal` or integer cents.
