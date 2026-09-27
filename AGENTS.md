# AGENTS.md

Instructions for coding agents working in this repository. README.md is the introduction.

## The person you are working with

Read HUMAN.md at the repository root if it exists. It describes the human you are working with
and how they work, including whether and when you may commit or push. It is personal and is never
committed. If there is no HUMAN.md, ask the human before committing, pushing, or doing anything
else that is hard to undo.

## What this is

`ukumari` defines spreadsheets as text. A model is a short Python script; running it builds a
calculation graph that carries no numbers and does no arithmetic. That graph is checked, then
computed over data by an emitted NumPy program, laid out as a `.yup` file of live formulas, and
saved as JSON (`.uku`). It is one of a family of two: `yupana` owns the `.yup` format, its reader,
the xlsx writer, and an oracle that has the spreadsheet app compute a file. `ukumari` depends on
`yupana` and NumPy, and nothing else.

## Sibling repositories

This repository is one of two, checked out side by side: `../yupana` and `../ukumari`. You may
read the other one, but never change it from here.

## Commands

    uv sync
    uv run ruff format
    uv run ruff check
    uv run ty check
    uv run pytest

## Style

- Python 3.14, typed throughout. ty and ruff, on ruff's defaults, both clean.
- Functional in flavour, Python in form: data is `@dataclass(frozen=True, slots=True)`; a sum type
  is a union of dataclasses, taken apart with `match`; nothing is mutated after construction.
  Never push it past what reads as natural Python.
- Expected failures are values: `Result` from the family's `result` module. A bug raises an
  ordinary built-in exception (`AssertionError` for a broken invariant), and nothing catches it.
  A `try` appears only as a narrow boundary that turns one expected exception into an `Err`.
- `result.py` is shared, byte-identical, by `yupana` and `ukumari`. Do not edit it.
- Text files are written with LF line endings on every platform: open them with `newline=""`
  (or write bytes), since Python's text mode on Windows turns `\n` into `\r\n`.
- Comments and docstrings say why, in the present tense. Doctests are the examples.
- Dates are absolute, such as 2026-09-26.

## Rules

- No third-party material: no downloaded workbooks, no data from anyone else. Examples use
  made-up numbers.
- No workbook is ever committed. Generated files go to `target/`.
- Nothing personal: no names, paths or e-mail addresses.
- Describe techniques generically, never as if from inside an organisation.
- Call the file format "xlsx" and the program "the spreadsheet app". No product names in any
  identifier, module, file or command.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), one concern
  per commit.

### In this repository

- Dependencies are `yupana` and NumPy; pandas never. Nothing Windows-specific, not even for
  development. `ukumari` never imports `yupana`'s oracle: a test marked `app` runs it as an
  external command, and is skipped unless on Windows with `../yupana` present.
- No text from a model ever becomes code. Emitted programs use generated identifiers, and names
  appear in them only as `repr` string literals. Generated code is executed in one place only.
- The emitted NumPy program and the scalar-circuit evaluator agree bit for bit. A disagreement is
  a bug in `ukumari`, and raises `AssertionError`.
- `plan/`, when present, is the working plan. It is never committed. A step in it is one commit.
  Where the plan and the code disagree, the code wins, and the plan is updated.
