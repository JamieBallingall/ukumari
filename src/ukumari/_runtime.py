"""The runtime every emitted program carries: its data gate, placement, arithmetic and driver.

This module's source is copied verbatim into each program, which therefore depends on
nothing but NumPy. So it imports nothing from ukumari, and every name in it starts with an
underscore, leaving the program's own names free. ukumari's data gate calls ``_extents``
too, so a program and the library accept exactly the same data.

A declaration is a tuple ``(name, kind, region, front, back)``, with ``region`` None for a
single value; an axis is ``(name, regions)``. A problem is a tuple whose first item names
its kind.
"""

import math as _math

import numpy as _np

# --- The data gate -----------------------------------------------------------------------


def _extents(declarations, axes, lengths, explicit):
    """Every region's extent, from input lengths and extents given explicitly.

    An input on ``region[f:-b]`` with ``n`` values gives the region ``n + f + b``. A region
    carrying no input takes an extent given explicitly. Returns the extents found and every
    problem, as tuples.
    """
    problems = []
    inputs = [d for d in declarations if d[1] == "input"]
    names = {d[0] for d in inputs}
    for name in lengths:
        if name not in names:
            problems.append(("unknown_input", name))
    for name, _, region, _, _ in inputs:
        if name not in lengths:
            problems.append(("missing_input", name))
        elif region is None and lengths[name] != 1:
            problems.append(("wrong_length", name, 1, lengths[name]))
    regions = [region for _, members in axes for region in members]
    for region in explicit:
        if region not in regions:
            problems.append(("unknown_extent", region))
    extents = {}
    for region in regions:
        sources = []
        if region in explicit:
            sources.append(("", explicit[region]))
        for name, _, on, front, back in inputs:
            if on == region and name in lengths:
                sources.append((name, lengths[name] + front + back))
        found = {extent for _, extent in sources}
        if not sources:
            problems.append(("missing_extent", region))
        elif len(found) > 1:
            problems.append(("conflicting_extent", region, tuple(sources)))
        else:
            extents[region] = found.pop()
    for region, extent in extents.items():
        if extent < 1:
            problems.append(("empty_region", region, region))
    for name, _, region, front, back in declarations:
        full = extents.get(region, 0)
        if full >= 1 and full - front - back < 1:
            problems.append(("empty_region", name, region))
    return extents, problems


def _describe(problem):
    """A problem in words, naming what is wrong in the model's own terms."""
    kind = problem[0]
    if kind == "unknown_input":
        return f"{problem[1]!r} is not an input of this model"
    if kind == "missing_input":
        return f"input {problem[1]!r} is missing"
    if kind == "wrong_length":
        return f"input {problem[1]!r} needs {problem[2]} value(s), not {problem[3]}"
    if kind == "unknown_extent":
        return f"an extent is given for {problem[1]!r}, which is not a region"
    if kind == "missing_extent":
        return f"nothing gives region {problem[1]!r} a length: give its extent"
    if kind == "conflicting_extent":
        told = ", ".join(
            f"{extent} from {repr(source) if source else 'the extents given'}"
            for source, extent in problem[2]
        )
        return f"region {problem[1]!r} is given different lengths: {told}"
    if kind == "empty_region":
        if problem[1] == problem[2]:
            return f"region {problem[1]!r} has no positions"
        return f"{problem[1]!r} is trimmed to nothing on region {problem[2]!r}"
    if kind == "not_numbers":
        return f"input {problem[1]!r} is not an array of numbers"
    if kind == "dimensions":
        return f"input {problem[1]!r} must be (scenarios, values), not {problem[2]}-D"
    if kind == "scenarios":
        told = ", ".join(f"{name!r} has {count}" for name, count in problem[1])
        return f"inputs disagree on the number of scenarios: {told}"
    if kind == "unknown_output":
        return f"{problem[1]!r} is not an output of this model"
    return repr(problem)


# --- Placement -----------------------------------------------------------------------------


def _placement(declarations, axes, extents):
    """Each declaration's absolute interval ``(start, stop)``, or None for a single value."""
    start_of = {}
    for _, regions in axes:
        at = 0
        for region in regions:
            start_of[region] = at
            at += extents[region]
    return [
        None
        if region is None
        else (start_of[region] + front, start_of[region] + extents[region] - back)
        for _, _, region, front, back in declarations
    ]


# --- Arithmetic ----------------------------------------------------------------------------
# One error value, carried as NaN. An infinite result is an error too, explicitly, since the
# spreadsheet app reports overflow as an error and NumPy gives infinity.


def _finite(r):
    return _np.where(_np.isinf(r), _np.nan, r)


def _add(a, b):
    return _finite(_np.add(a, b))


def _sub(a, b):
    return _finite(_np.subtract(a, b))


def _mul(a, b):
    return _finite(_np.multiply(a, b))


def _div(a, b):
    # Division by zero, including 0/0 and x/-0, is an error.
    r = _np.divide(a, b)
    return _np.where(_np.equal(b, 0) | _np.isinf(r), _np.nan, r)


def _neg(a):
    return _np.negative(a)


def _min(a, b):
    # Comparison alone would lose a NaN depending on argument order; on a tie, the second.
    return _np.where(_np.isnan(a) | _np.isnan(b), _np.nan, _np.where(a < b, a, b))


def _max(a, b):
    return _np.where(_np.isnan(a) | _np.isnan(b), _np.nan, _np.where(a > b, a, b))


def _power(a, b):
    # C's pow gives 1 for 1 ** NaN and NaN ** 0, so errors are checked first. The app
    # refuses 0 ** 0, zero to a negative power, and a negative number to a fractional
    # power or to one of 4,294,967,295 or more in size.
    if _math.isnan(a) or _math.isnan(b) or (a == 0.0 and b <= 0.0):
        return _math.nan
    if a < 0.0 and abs(b) >= 4294967295.0:
        return _math.nan
    try:
        r = _math.pow(a, b)
    except ValueError, OverflowError:
        return _math.nan
    return _math.nan if _math.isinf(r) else r


_power_each = _np.frompyfunc(_power, 2, 1)


def _pow(a, b):
    # math.pow on each pair, exactly as the scalar evaluator computes it: NumPy's own power
    # may round differently on some machines, and the two must agree bit for bit.
    return _np.asarray(_power_each(a, b), dtype=_np.float64)


def _fit(x, rows, columns):
    """``x`` broadcast to ``(rows, columns)``, as a new array."""
    return _np.array(_np.broadcast_to(x, (rows, columns)), dtype=_np.float64)


def _lag(seed, body, rows, columns):
    """A seeded lag: the seed at the first position, then the body.

    Under ``k`` seeded lags, a target of ``k`` or fewer positions asks the innermost body
    for fewer than none, so ``columns`` may be negative: that is no columns.
    """
    out = _np.empty((rows, max(columns, 0)))
    out[:, :1] = seed
    out[:, 1:] = body
    return out


def _columns(x, start, stop):
    """Columns ``[start, stop)`` of ``x``; none when the range is empty.

    A range asked for under seeded lags can end before it starts, and a plain slice would
    then count a negative end from the right.
    """
    return x[:, start:stop] if start < stop else x[:, :0]


# --- The driver ----------------------------------------------------------------------------


def _run(declarations, axes, steps, inputs, extents, outputs):
    """Check the data, place the regions, and evaluate what the outputs need."""
    names = [d[0] for d in declarations]
    index = {name: i for i, name in enumerate(names)}
    computed = [d[0] for d in declarations if d[1] == "vector"]
    requested = list(computed if outputs is None else outputs)

    problems = []
    for name in requested:
        if name not in computed:
            problems.append(("unknown_output", name))
    arrays = {}
    for name, value in inputs.items():
        try:
            array = _np.asarray(value, dtype=_np.float64)
        except TypeError, ValueError:
            problems.append(("not_numbers", name))
            continue
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2:
            problems.append(("dimensions", name, array.ndim))
            continue
        arrays[name] = array
    counts = sorted({(a.shape[0], n) for n, a in arrays.items() if a.shape[0] != 1})
    if len({count for count, _ in counts}) > 1 or any(c == 0 for c, _ in counts):
        problems.append(("scenarios", tuple((n, c) for c, n in counts)))
    lengths = {name: array.shape[1] for name, array in arrays.items()}
    found, gate = _extents(declarations, axes, lengths, dict(extents or {}))
    problems += gate
    if problems:
        raise ValueError(
            "the data does not fit the model:\n"
            + "\n".join(_describe(p) for p in problems)
        )
    rows = counts[0][0] if counts else 1
    places = _placement(declarations, axes, found)

    values = [None] * len(declarations)
    for name, array in arrays.items():
        values[index[name]] = _np.where(_np.isinf(array), _np.nan, array)

    wanted = {index[name] for name in requested}
    needed = []
    for number in range(len(steps) - 1, -1, -1):
        _, reads, writes = steps[number]
        if wanted.intersection(writes):
            needed.append(number)
            wanted.update(reads)
    needed.reverse()
    last_reader = {}
    for number in needed:
        for i in steps[number][1]:
            last_reader[i] = number
    keep = {index[name] for name in requested}

    with _np.errstate(all="ignore"):
        for number in needed:
            step, _, _ = steps[number]
            step(values, places, rows)
            for i, reader in last_reader.items():
                if reader == number and i not in keep:
                    values[i] = None

    result = {}
    for name in requested:
        i = index[name]
        start_stop = places[i]
        width = 1 if start_stop is None else start_stop[1] - start_stop[0]
        result[name] = _fit(values[i], rows, width)
    return result
