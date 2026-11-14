# Contributing to TrucksIL / Как участвовать

TrucksIL is an early prototype and is **not** for real navigation.

## Safety-first data policy

Wrong restriction data can send a truck under a low bridge. Before adding or changing any data in `data/`, read [docs/DATA_VERIFICATION.md](docs/DATA_VERIFICATION.md):

- Every record needs a source (URL, license) and a verification status.
- Never mark data as verified without checking an official source.
- Unverified data must never be presented as safe.
- Do not invent or guess values; use fictional examples only where clearly labelled.

Данные об ограничениях добавляются только с указанием источника и статуса верификации по правилам `docs/DATA_VERIFICATION.md`.

## Workflow

1. Create a branch and keep changes focused.
2. Run `npm test` to validate schemas and examples.
3. Open a pull request describing what changed and, for data, where it came from.

Formatting follows `.editorconfig` (UTF-8, LF, 2-space indent).
