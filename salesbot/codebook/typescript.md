# TypeScript
## Rules
- `strict: true`. Type function parameters and return values; let locals be inferred.
- `interface` for object shapes, `type` for unions. Avoid `any`; use `unknown` and narrow with checks.
- Discriminated unions for states: `type S = { kind: "ok"; data: T } | { kind: "err"; error: string }`.
## Templates
```ts
interface User { id: number; name: string; email?: string }

async function fetchUser(id: number): Promise<User> {
  const res = await fetch(`/api/users/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as User;
}

function isUser(x: unknown): x is User {
  return typeof x === "object" && x !== null && typeof (x as User).id === "number";
}
```
Generics: `function first<T>(xs: T[]): T | undefined { return xs[0]; }`. Utility types: `Partial<T>`, `Pick<T,"a">`, `Record<string, T>`.
React (TSX): `function Card({ title }: { title: string }) { const [n, setN] = useState(0); return <button onClick={() => setN(n + 1)}>{title} {n}</button>; }`
## Pitfalls
- `as` casts don't check anything at runtime; validate external data. Non-null `!` hides bugs.
- Enums compile to objects; prefer string-literal unions. Keep `tsconfig` `moduleResolution` consistent with the bundler.
