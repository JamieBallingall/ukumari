"""Guardedness, and the schedule it produces.

Every cycle of references must cross a ``lag``, and no reduction may sit on a cycle. The same
traversal that proves it gives the evaluation order:

- layers, split at reductions, because a reduction needs its whole source first;
- within a layer, strongly connected components in topological order; a component with a
  lag on a cycle through it is a recurrence and stays together;
- ties broken by the order in which vectors were defined, so everything downstream is
  deterministic.

>>> from ukumari.expr import Ref, Lag, Literal
>>> from ukumari.circuit import Equation
>>> errors, layers = schedule((
...     Equation("closing", Ref("opening") - Ref("payment")),
...     Equation("opening", Lag(Ref("closing"), Literal(100))),
...     Equation("payment", Ref("opening") * 2),
... ))
>>> errors
()
>>> layers
(Layer(components=(Component(members=('opening', 'payment', 'closing'), recurrent=True),)),)
"""

import heapq
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

from ukumari.circuit import Component, Equation, Layer
from ukumari.errors import CircularReduction, GuardError, UnguardedCycle
from ukumari.expr import At, Binary, Expr, Lag, Last, Literal, Neg, Ref


class Edge(StrEnum):
    """How an equation reads a name."""

    DIRECT = "direct"  # at the same position
    LAGGED = "lagged"  # at an earlier position, through a lag
    REDUCTION = "reduction"  # all of it, through a reduction


def dependencies(expr: Expr) -> list[tuple[str, Edge]]:
    """Every name an expression reads, and how, in order of appearance.

    A seed is not guarded by its lag: it is read at the first position, not an earlier one.

    >>> dependencies(Lag(Ref("x"), Last("y")) + Ref("z"))
    [('x', <Edge.LAGGED: 'lagged'>), ('y', <Edge.REDUCTION: 'reduction'>), ('z', <Edge.DIRECT: 'direct'>)]
    """
    found: list[tuple[str, Edge]] = []

    def go(e: Expr, lagged: bool) -> None:
        match e:
            case Ref(name):
                found.append((name, Edge.LAGGED if lagged else Edge.DIRECT))
            case Last(name):
                found.append((name, Edge.REDUCTION))
            case Literal() | At():
                pass
            case Neg(operand):
                go(operand, lagged)
            case Binary(_, left, right):
                go(left, lagged)
                go(right, lagged)
            case Lag(body, seed):
                go(body, True)
                if seed is not None:
                    go(seed, False)

    go(expr, False)
    return found


def strongly_connected(
    nodes: Sequence[str], successors: Mapping[str, Sequence[str]]
) -> list[tuple[str, ...]]:
    """Tarjan's strongly connected components, iteratively.

    Components come out dependencies first: every component a component reaches is listed
    before it. Members are listed in the order of ``nodes``.

    >>> strongly_connected("abc", {"a": ["b"], "b": ["a", "c"], "c": []})
    [('c',), ('a', 'b')]
    """
    order = {node: i for i, node in enumerate(nodes)}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[tuple[str, ...]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            children = successors.get(node, ())
            if child < len(children):
                work.append((node, child + 1))
                successor = children[child]
                if successor not in index:
                    work.append((successor, 0))
                elif successor in on_stack:
                    low[node] = min(low[node], index[successor])
                continue
            if low[node] == index[node]:
                members: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node:
                        break
                components.append(tuple(sorted(members, key=order.__getitem__)))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return components


def _ordered(
    items: Iterable[str],
    predecessors: Mapping[str, Iterable[str]],
    rank: Mapping[str, int],
) -> list[str]:
    """A topological order (predecessors first), ties broken by rank; cycles by rank too."""
    items = list(items)
    remaining = {item: 0 for item in items}
    followers: dict[str, list[str]] = {item: [] for item in items}
    for item in items:
        for before in set(predecessors.get(item, ())):
            if before in remaining and before != item:
                remaining[item] += 1
                followers[before].append(item)
    ready = [(rank[item], item) for item in items if remaining[item] == 0]
    heapq.heapify(ready)
    result: list[str] = []
    while ready:
        _, item = heapq.heappop(ready)
        result.append(item)
        for follower in followers[item]:
            remaining[follower] -= 1
            if remaining[follower] == 0:
                heapq.heappush(ready, (rank[follower], follower))
    if len(result) < len(items):
        # Only a model with an unguarded cycle gets here, and it is refused anyway.
        placed = set(result)
        result += sorted((i for i in items if i not in placed), key=rank.__getitem__)
    return result


def _cycle(
    members: Sequence[str], direct: Mapping[str, Sequence[str]]
) -> tuple[str, ...]:
    """One concrete cycle through the first member, following direct edges within members."""
    inside = set(members)
    start = members[0]
    path = [start]
    seen = {start: 0}
    node = start
    while True:
        node = next(s for s in direct[node] if s in inside)
        if node in seen:
            return tuple(path[seen[node] :])
        seen[node] = len(path)
        path.append(node)


def schedule(
    equations: Sequence[Equation],
) -> tuple[tuple[GuardError, ...], tuple[Layer, ...]]:
    """Every guardedness error, and the schedule.

    Only the first definition of each name counts (a second is reported elsewhere), and
    only defined names are scheduled: inputs are there from the start. The schedule is
    meaningful only when there are no errors.
    """
    definitions: dict[str, Expr] = {}
    for equation in equations:
        definitions.setdefault(equation.name, equation.expression)
    nodes = list(definitions)
    rank = {name: i for i, name in enumerate(nodes)}

    edges: dict[str, list[tuple[str, Edge]]] = {
        name: [(d, how) for d, how in dependencies(expr) if d in definitions]
        for name, expr in definitions.items()
    }
    successors = {name: [d for d, _ in found] for name, found in edges.items()}
    direct = {
        name: [d for d, how in found if how is Edge.DIRECT]
        for name, found in edges.items()
    }

    errors: list[GuardError] = []
    component_of: dict[str, int] = {}
    components = strongly_connected(nodes, successors)
    built: list[Component] = []
    for number, members in enumerate(components):
        for member in members:
            component_of[member] = number
        inside = set(members)
        for member in members:
            for source, how in edges[member]:
                if how is Edge.REDUCTION and source in inside:
                    error = CircularReduction(member, source)
                    if error not in errors:
                        errors.append(error)
        direct_inside = {m: [d for d in direct[m] if d in inside] for m in members}
        for group in strongly_connected(members, direct_inside):
            if len(group) > 1 or group[0] in direct_inside[group[0]]:
                errors.append(UnguardedCycle(_cycle(group, direct_inside)))
        recurrent = len(members) > 1 or any(
            d == members[0] for d, _ in edges[members[0]]
        )
        order = _ordered(members, direct_inside, rank)
        built.append(Component(tuple(order), recurrent))

    # Components come dependencies first, so each one's layer is known before it is needed.
    layer_of: list[int] = []
    for number, members in enumerate(components):
        layer = 0
        for member in members:
            for source, how in edges[member]:
                other = component_of[source]
                if other != number:
                    layer = max(layer, layer_of[other] + (how is Edge.REDUCTION))
        layer_of.append(layer)

    layers: list[Layer] = []
    for layer in range(max(layer_of, default=-1) + 1):
        here = [n for n in range(len(components)) if layer_of[n] == layer]
        key = {str(n): min(rank[m] for m in components[n]) for n in here}
        before = {
            str(n): [
                str(component_of[s])
                for m in components[n]
                for s in successors[m]
                if component_of[s] != n
            ]
            for n in here
        }
        order = _ordered([str(n) for n in here], before, key)
        layers.append(Layer(tuple(built[int(n)] for n in order)))
    return tuple(errors), tuple(layers)
