# Design

ukumari defines a spreadsheet as text. A model is a short Python script; running it builds a **calculation graph** that carries no numbers and does no arithmetic. Everything else is an interpretation of that one graph.

## The graphs

| | Name | What it is | Cyclic |
|---|---|---|---|
| **A** | Authored | What running the model's Python builds. It may be wrong | yes |
| **L** | List circuit | A that has passed every check. Vector equations with no lengths; cycles only through `lag`. Holding an L means every later step succeeds for any data that binds | yes |
| **V** | Vector circuit | L bound to the data: every length known, every recurrence written out position by position | no |
| **S** | Scalar circuit | One node per operation, in topological order. The source of the workbook's formulas. It carries no addresses: placement is the separate layout | no |
| **P** | Python program | NumPy, emitted from L. Runs at any length. Executing it gives the values | — |
| **`.uku`** | L as JSON | Read back through the checks, never directly into L | — |

## The flow

```text
                                        model errors             data errors
                                             ▲                        ▲
 model.py ──run──▶ A ──────── check ─────────┴──▶ L ──── bind(data) ──┴──▶ V ──unroll──▶ S
                   ▲                              │                                       │
                   └────── read ◀── .uku ◀───────┤                                       │
                                                  └── emit ──▶ P ──run(data)──▶ values   │
                                                                     │                    │
                                                            equal, bit for bit ◀── evaluate
                                                                                          │
                                                                                          ▼
                                   S + layout ──▶ .yup ──read back, yupana──▶ xlsx (live formulas)
                                                    └──yupana's oracle (tests)──▶ the app's values
```

## The transformations

| | From → to | Module |
|---|---|---|
| α | `.py` → L, and L ↔ `.uku` | `model`, `check` (with `guard` and `align`), `uku` |
| β₁ | L + data → `.yup` and a values CSV | `bind`, `unroll`, `layout`, `yup` |
| β₂ | L + data → values | `emit` (running P) |
| β₃ | L → P, a standalone NumPy program | `emit`, with `_runtime` copied in |
| γ₁ | `.yup` → xlsx | `yupana` |

`pipeline.export` runs the lot in one call: build, bind, unroll, lay out, run P, check P against the S evaluator, write the `.yup` and values CSV, and read the `.yup` back.

## Key decisions

- **No numbers in the graph.** `build()` holds no data: every number that could change between runs arrives as an input. Constants that are part of a formula's meaning, like the `1` in `1 + growth`, are exact rationals, and become doubles only when computed.
- **Two gates.** The model gate (`check`) finds every model error at once and returns L or all of them: construction, guardedness (every cycle crosses a `lag`) and alignment (every leaf supplies every position its equation reads). The data gate (`bind`) rejects only data. So nothing after L can fail on a model error.
- **Alignment is decided without extents.** Every position is a linear form in the region extents; the admissible extents form a box, on which "non-negative everywhere" is exact. A brute-force checker agrees with it on 1,000 random models.
- **Subtraction and division are primitives**, as is negation: `a × (1/b)` rounds twice, and `−a` differs from `0 − a` on signed zero.
- **One error value, carried as NaN.** Division by zero and any infinite result are errors, explicitly, as in the spreadsheet app. `minimum` and `maximum` check for errors explicitly, and return the second argument on a tie.
- **P is emitted from L, and agrees with S bit for bit.** Two independent computations of one model: a NumPy program that runs at any length over many scenarios, and a scalar evaluator that walks S one double at a time. Every export checks one against the other, cell by cell.
- **No model text becomes code.** In P, identifiers are generated, names appear only as `repr` string literals, and numbers only as a float's `repr`.
- **The `.yup` file is the contract** with `yupana`: ukumari writes it and reads it back through `yupana`'s reader, so a workbook built in memory passes the same checks as a file. The app's own values come from `yupana`'s oracle, run as a separate tool: ukumari never depends on anything Windows-specific.

## Finer points

Where the plan was silent or ambiguous, the code decides:

- **The library and P share one data gate.** `_runtime.py` is copied verbatim into every emitted program, and `bind` calls the same code, so both accept exactly the same data.
- **A seed is not guarded by its lag.** It is read at the first position, not an earlier one, so a reference inside a seed is a same-position dependency.
- **Scalars are unrolled first within each layer**, not before every layer, since a scalar may depend on a reduction of an earlier layer (`share = last(x) / 2`).
- **Every region has at least one position**, so alignment's box has every minimum at least 1. The seeded-lag refinement never changes a verdict in the milestone-1 language (the target region's extent cancels, or appears with coefficient −1), but it is exact and cheap, and it will matter if extents ever get a maximum.
- **Conflicting extents name every source.** The inputs on a region, and any extent given explicitly, must agree; one `ConflictingExtent` lists them all.
- **A subexpression holding a literal is never shared** in S, since literals are never shared: `c = a * 2 + 2` does not reuse `b = a * 2`.
- **A formula literal is the shorter of plain digits and `repr`**, so `1.5e300` is written `1.5E+300`, not 301 digits.
- **A formula is its equation.** It references exactly the cells its equation names and writes every operation inline, even one another cell happens to compute: S shares nodes to compute each value once, which is not how a modeller writes. So a seed reads the cell the model names, not the input its value came from. Where several named cells hold one value, it takes the formula's own column on its own sheet, then its own sheet, then the same position on another sheet, then the rest, and within each prefers the origin.
- **Sheets line up by region.** On every sheet of a `Workbook`, column C shows the first position of the sheet's `start` region, so two sheets that start at the same region show the same quarter in the same column, and a copied row is a same-column link.
- **A copy links to the cell it copies.** A cell whose equation is a bare reference (a copy, a lag's previous position, a seed, a reduction) holds the same node as the cell it reads, and is written as a link to that cell, so a copy of a copy links to the copy. Any other cell writes out its own equation, even when another cell computes the same value: a row that adds the same two assumptions in every quarter reads the same in every column.
