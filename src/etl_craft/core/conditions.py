"""Run conditions: a closed grammar over upstream facts, parsed once and evaluated many times.

A condition is written on the row it governs: ``CFG_TASKS.RUN_CONDITION`` names tasks (``task``,
``pipeline.task`` or ``project.pipeline.task``), ``CFG_PIPELINES.START_CONDITION`` names
pipelines (``pipeline`` or ``project.pipeline``). Every reference ends in a fact::

    load.SUCCESS AND load.REJECTED = 0
    AT_LEAST(1, a.FAILED, b.FAILED)

Evaluation is three-valued: ``True``, ``False`` or ``None`` (not known yet), combined as SQL
combines them, so ``a.SUCCESS OR b.SUCCESS`` is true on the first success and ``a.SUCCESS AND
b.SUCCESS`` is false on the first failure. There are no other functions, no arithmetic and no
templating.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from etl_craft.core.enums import DependencyType, RunStatus
from etl_craft.core.errors import ConditionError
from etl_craft.core.text import suggest

Truth = bool | None
"""A condition's value: ``None`` while it cannot be decided yet."""


class Scope(StrEnum):
    """Where a condition is written, which decides what its names mean."""

    TASK = "TASK"
    PIPELINE = "PIPELINE"


class Kind(StrEnum):
    """A fact's type."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    STATUS = "status"
    ERROR_CLASS = "error class"


STATUSES = (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.CANCELLED)
ERROR_CLASSES = ("TRANSIENT", "PERMANENT", "UNKNOWN", "NONE")
COUNTS = (
    "SOURCE_ROWS",
    "TARGET_ROWS",
    "ROWS_WRITTEN",
    "INSERTED",
    "UPDATED",
    "DELETED",
    "REJECTED",
    "DUPLICATES",
)
FACTS: dict[str, tuple[Kind, frozenset[Scope]]] = {
    **{
        f: (Kind.BOOLEAN, frozenset(Scope))
        for f in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.SKIPPED, "FINISHED")
    },
    DependencyType.HAS_DATA: (Kind.BOOLEAN, frozenset(Scope)),
    "STATUS": (Kind.STATUS, frozenset(Scope)),
    **{f: (Kind.INTEGER, frozenset(Scope)) for f in COUNTS},
    "DURATION_SECONDS": (Kind.INTEGER, frozenset(Scope)),
    "ATTEMPTS": (Kind.INTEGER, frozenset({Scope.TASK})),
    "ERROR_CLASS": (Kind.ERROR_CLASS, frozenset({Scope.TASK})),
}
KEYWORDS = frozenset({"AND", "OR", "NOT", "AT_LEAST"})
OPERATORS = ("<=", ">=", "<>", "=", "<", ">")
TERMINAL = frozenset({RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.CANCELLED})


@dataclass(frozen=True)
class Facts:
    """What a condition can read about one finished upstream: a task run or a pipeline run.

    ``counts`` maps a count fact to its value, or to ``None`` where the upstream did not produce
    it (a comparison with it is then not known). A ``SKIPPED`` or ``CANCELLED`` upstream counts
    zero rows.
    """

    status: str
    counts: dict[str, int | None] = field(default_factory=dict)
    attempts: int | None = None
    duration_seconds: int | None = None
    error_class: str | None = None
    assumed: bool = False

    @classmethod
    def delivered(cls) -> Facts:
        """Return what a backfill assumes of another pipeline's upstream: it succeeded with data.

        Every other fact is not known, so a condition that needs one is not met.
        """
        return cls(RunStatus.SUCCESS, assumed=True)

    def value(self, fact: str) -> bool | int | str | None:
        """Return ``fact``'s value, ``None`` when it is not known."""
        if self.assumed and fact not in (
            RunStatus.SUCCESS,
            RunStatus.FAILED,
            RunStatus.SKIPPED,
            "FINISHED",
            "STATUS",
        ):
            return True if fact == DependencyType.HAS_DATA else None
        terminal = self.status in TERMINAL
        if fact == RunStatus.SUCCESS:
            return self.status == RunStatus.SUCCESS
        if fact in (RunStatus.FAILED, RunStatus.SKIPPED):
            return self.status == fact
        if fact == "FINISHED":
            return terminal
        if fact == "STATUS":
            return self.status
        if fact == DependencyType.HAS_DATA:
            written = self.counts.get("ROWS_WRITTEN")
            if written is None:
                written = self.counts.get("TARGET_ROWS")
            return self.status == RunStatus.SUCCESS and bool(written and written > 0)
        if fact in COUNTS:
            if self.status in (RunStatus.SKIPPED, RunStatus.CANCELLED):
                return 0
            return self.counts.get(fact)
        if fact == "ATTEMPTS":
            return self.attempts
        if fact == "DURATION_SECONDS":
            return self.duration_seconds
        if fact == "ERROR_CLASS":
            return (self.error_class or "UNKNOWN") if self.status == RunStatus.FAILED else "NONE"
        raise ConditionError(f"unknown fact {fact}")


# The tree


@dataclass(frozen=True)
class Ref:
    """``parts`` (the name, outermost first) and the fact read from it."""

    parts: tuple[str, ...]
    fact: str
    position: int

    @property
    def name(self) -> str:
        """The dotted name without the fact: ``load`` or ``SALES.load``."""
        return ".".join(self.parts)

    def __str__(self) -> str:
        """Write the reference as the condition spells it: ``load.SUCCESS``."""
        return f"{self.name}.{self.fact}"


@dataclass(frozen=True)
class Flag:
    """A boolean fact on its own: ``load.SUCCESS``."""

    ref: Ref


@dataclass(frozen=True)
class Compare:
    """``ref op value``: ``load.REJECTED = 0``, ``load.STATUS <> FAILED``."""

    ref: Ref
    op: str
    value: int | str


@dataclass(frozen=True)
class Not:
    """``NOT term``."""

    term: Node


@dataclass(frozen=True)
class AllOf:
    """``a AND b AND ...``."""

    terms: tuple[Node, ...]


@dataclass(frozen=True)
class AnyOf:
    """``a OR b OR ...``."""

    terms: tuple[Node, ...]


@dataclass(frozen=True)
class AtLeast:
    """``AT_LEAST(n, a, b, ...)``: at least ``n`` of the terms are true."""

    count: int
    terms: tuple[Node, ...]


Node = Flag | Compare | Not | AllOf | AnyOf | AtLeast


@dataclass(frozen=True)
class Condition:
    """A parsed condition: its text and tree, and every reference it reads."""

    text: str
    root: Node
    refs: tuple[Ref, ...]

    def names(self) -> tuple[tuple[str, ...], ...]:
        """Return the distinct names the condition reads, in the order they first appear."""
        return tuple(dict.fromkeys(ref.parts for ref in self.refs))


# Parsing

_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+)|(?P<word>[A-Za-z][A-Za-z0-9_]*)|(?P<op><=|>=|<>|=|<|>)"
    r"|(?P<punct>[().,]))"
)


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    position: int


def _tokens(text: str) -> list[_Token]:
    tokens, index = [], 0
    while index < len(text):
        if text[index:].strip() == "":
            break
        match = _TOKEN.match(text, index)
        if match is None or match.end() == index:
            start = index + len(text[index:]) - len(text[index:].lstrip())
            raise ConditionError(
                f"position {start + 1}: unexpected {text[start]!r}; expected a name, AND, OR, "
                "NOT, AT_LEAST, parentheses, a comparison or a number"
            )
        kind = match.lastgroup or ""
        tokens.append(_Token(kind, match.group(kind), match.start(kind) + 1))
        index = match.end()
    return tokens


class _Parser:
    def __init__(self, text: str, scope: Scope) -> None:
        self.text, self.scope = text, scope
        self.tokens = _tokens(text)
        self.index = 0
        self.refs: list[Ref] = []

    def peek(self, offset: int = 0) -> _Token | None:
        at = self.index + offset
        return self.tokens[at] if at < len(self.tokens) else None

    def fail(self, token: _Token | None, expected: str) -> ConditionError:
        if token is None:
            return ConditionError(
                f"position {len(self.text) + 1}: the condition ends; expected {expected}"
            )
        return ConditionError(
            f"position {token.position}: value {token.text!r}; expected {expected}"
        )

    def at(self, text: str) -> bool:
        token = self.peek()
        return token is not None and token.text == text

    def take(self, text: str) -> _Token:
        token = self.peek()
        if token is None or token.text.upper() != text:
            raise self.fail(token, repr(text))
        self.index += 1
        return token

    def keyword(self, word: str) -> bool:
        token, after = self.peek(), self.peek(1)
        is_name = after is not None and after.text == "."
        if token is not None and token.text.upper() == word and not is_name:
            self.index += 1
            return True
        return False

    def parse(self) -> Condition:
        if not self.tokens:
            raise ConditionError("the condition is empty; expected a name such as load.SUCCESS")
        root = self.disjunction()
        if self.peek() is not None:
            raise self.fail(self.peek(), "AND, OR or the end of the condition")
        return Condition(self.text, root, tuple(self.refs))

    def disjunction(self) -> Node:
        terms = [self.conjunction()]
        while self.keyword("OR"):
            terms.append(self.conjunction())
        return terms[0] if len(terms) == 1 else AnyOf(tuple(terms))

    def conjunction(self) -> Node:
        terms = [self.negation()]
        while self.keyword("AND"):
            terms.append(self.negation())
        return terms[0] if len(terms) == 1 else AllOf(tuple(terms))

    def negation(self) -> Node:
        if self.keyword("NOT"):
            return Not(self.negation())
        return self.primary()

    def primary(self) -> Node:
        token = self.peek()
        if token is not None and token.text == "(":
            self.index += 1
            node = self.disjunction()
            self.take(")")
            return node
        if self.keyword("AT_LEAST"):
            return self.at_least()
        ref = self.reference()
        kind = FACTS[ref.fact][0]
        op = self.peek()
        if op is not None and op.kind == "op":
            self.index += 1
            return Compare(ref, op.text, self.value(ref, kind, op))
        if kind != Kind.BOOLEAN:
            raise ConditionError(
                f"position {ref.position}: {ref} is {kind}, not true or false; compare it, "
                f"for example {ref} {'> 0' if kind == Kind.INTEGER else '= FAILED'}"
            )
        return Flag(ref)

    def at_least(self) -> Node:
        opening = self.take("(")
        count_token = self.peek()
        if count_token is None or count_token.kind != "number":
            raise self.fail(count_token, "how many must be true, a whole number")
        self.index += 1
        terms: list[Node] = []
        while self.at(","):
            self.index += 1
            terms.append(self.disjunction())
        self.take(")")
        count = int(count_token.text)
        if len(terms) < 2 or not 1 <= count <= len(terms):
            raise ConditionError(
                f"position {opening.position - len('AT_LEAST')}: AT_LEAST({count}, ...) has "
                f"{len(terms)} condition(s); expected at least two, and a count from 1 to "
                f"{max(len(terms), 1)}"
            )
        return AtLeast(count, tuple(terms))

    def reference(self) -> Ref:
        first = self.peek()
        if first is None or first.kind != "word" or first.text.upper() in KEYWORDS:
            raise self.fail(first, "a name such as load.SUCCESS")
        parts = [first.text]
        self.index += 1
        while self.at("."):
            self.index += 1
            token = self.peek()
            if token is None or token.kind != "word":
                raise self.fail(token, "a name or a fact after '.'")
            parts.append(token.text)
            self.index += 1
        if len(parts) < 2:
            raise ConditionError(
                f"position {first.position}: {first.text!r} has no fact; expected "
                f"{first.text}.SUCCESS or another fact: {', '.join(FACTS)}"
            )
        fact, name = parts[-1].upper(), tuple(parts[:-1])
        limit = 3 if self.scope == Scope.TASK else 2
        if len(name) > limit:
            where = "task" if self.scope == Scope.TASK else "pipeline"
            shape = "project.pipeline.task" if self.scope == Scope.TASK else "project.pipeline"
            raise ConditionError(
                f"position {first.position}: {'.'.join(name)!r} has {len(name)} parts; a "
                f"{where} condition names at most {shape}"
            )
        if fact not in FACTS:
            hint = suggest(fact, FACTS)
            did = f"; did you mean {hint[0]}?" if hint else ""
            raise ConditionError(
                f"position {first.position}: unknown fact {parts[-1]!r}; expected one of "
                f"{', '.join(FACTS)}{did}"
            )
        if self.scope not in FACTS[fact][1]:
            raise ConditionError(
                f"position {first.position}: {fact} is not available for a pipeline; expected "
                f"one of {', '.join(f for f, (_, s) in FACTS.items() if Scope.PIPELINE in s)}"
            )
        ref = Ref(name, fact, first.position)
        self.refs.append(ref)
        return ref

    def value(self, ref: Ref, kind: Kind, op: _Token) -> int | str:
        token = self.peek()
        if token is None:
            raise self.fail(token, "a value to compare with")
        self.index += 1
        if kind == Kind.INTEGER:
            if token.kind != "number":
                raise ConditionError(
                    f"position {token.position}: {ref} is a count; expected a whole number, "
                    f"not {token.text!r}"
                )
            return int(token.text)
        allowed = STATUSES if kind == Kind.STATUS else ERROR_CLASSES
        if kind == Kind.BOOLEAN or op.text not in ("=", "<>"):
            raise ConditionError(
                f"position {op.position}: {ref} cannot use {op.text!r}; "
                + ("use it on its own or with NOT" if kind == Kind.BOOLEAN else "use = or <>")
            )
        if token.text.upper() not in allowed:
            raise ConditionError(
                f"position {token.position}: value {token.text!r} for {ref}; expected one of "
                f"{', '.join(allowed)}"
            )
        return token.text.upper()


def parse(text: str, scope: Scope) -> Condition:
    """Parse ``text``; ``ConditionError`` names the position, the value and what was expected."""
    return _Parser(text, scope).parse()


# Evaluation

Lookup = Callable[[Ref], Facts | None]
"""The facts a reference reads, or ``None`` while they are not known."""


@dataclass
class Reading:
    """What one evaluation read: each reference as text, with its value (``None``: unknown)."""

    values: dict[str, bool | int | str | None] = field(default_factory=dict)


def evaluate(condition: Condition, lookup: Lookup, reading: Reading | None = None) -> Truth:
    """Return the condition's value; ``reading`` collects what it read, for the record."""
    return _node(condition.root, lookup, reading if reading is not None else Reading())


def _node(node: Node, lookup: Lookup, reading: Reading) -> Truth:
    if isinstance(node, Flag):
        value = _read(node.ref, lookup, reading)
        return None if value is None else bool(value)
    if isinstance(node, Compare):
        return _compare(_read(node.ref, lookup, reading), node.op, node.value)
    if isinstance(node, Not):
        inner = _node(node.term, lookup, reading)
        return None if inner is None else not inner
    if isinstance(node, AllOf):
        values = [_node(term, lookup, reading) for term in node.terms]
        return False if False in values else (None if None in values else True)
    if isinstance(node, AnyOf):
        values = [_node(term, lookup, reading) for term in node.terms]
        return True if True in values else (None if None in values else False)
    values = [_node(term, lookup, reading) for term in node.terms]
    true, unknown = values.count(True), values.count(None)
    if true >= node.count:
        return True
    return False if true + unknown < node.count else None


def _read(ref: Ref, lookup: Lookup, reading: Reading) -> bool | int | str | None:
    facts = lookup(ref)
    value = None if facts is None else facts.value(ref.fact)
    reading.values[str(ref)] = value
    return value


def _compare(left: bool | int | str | None, op: str, right: int | str) -> Truth:
    if left is None:
        return None
    if op == "=":
        return left == right
    if op == "<>":
        return left != right
    assert isinstance(left, int) and isinstance(right, int)
    return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]


def describe(reading: Reading) -> str:
    """``a.SUCCESS=true, b.REJECTED=0, c.SUCCESS=unknown`` for a log line or a decision."""
    shown = {True: "true", False: "false", None: "unknown"}
    return ", ".join(
        f"{ref}={shown[value] if value is None or isinstance(value, bool) else value}"
        for ref, value in reading.values.items()
    )


def _atoms(node: Node) -> list[Flag | Compare]:
    if isinstance(node, (Flag, Compare)):
        return [node]
    if isinstance(node, Not):
        return _atoms(node.term)
    return [atom for term in node.terms for atom in _atoms(term)]


LEGACY_KINDS = {
    RunStatus.SUCCESS: DependencyType.SUCCESS,
    RunStatus.FAILED: DependencyType.FAILURE,
    "FINISHED": DependencyType.ALWAYS,
    DependencyType.HAS_DATA: DependencyType.HAS_DATA,
}


def is_plain(condition: Condition) -> bool:
    """Whether the condition only requires flags to hold together: ``a.SUCCESS AND b.HAS_DATA``."""
    root = condition.root
    return isinstance(root, Flag) or (
        isinstance(root, AllOf) and all(isinstance(term, Flag) for term in root.terms)
    )


def edge_kind(condition: Condition, name: tuple[str, ...]) -> str:
    """Name what a condition reads from one upstream: a single flag's kind, else ``CONDITION``.

    Graphs style an edge by it: ``SUCCESS``, ``FAILURE``, ``ALWAYS`` or ``HAS_DATA`` when the
    condition only tests that flag of the upstream, plainly; anything richer is ``CONDITION``.
    """
    atoms = [atom for atom in _atoms(condition.root) if atom.ref.parts == name]
    facts = {atom.ref.fact for atom in atoms}
    if (
        is_plain(condition)
        and len(atoms) == 1
        and isinstance(atoms[0], Flag)
        and facts <= LEGACY_KINDS.keys()
    ):
        return LEGACY_KINDS[facts.pop()]
    return "CONDITION"


def holds_for(condition: Condition, name: tuple[str, ...], lookup: Lookup) -> Truth:
    """Whether every test the condition makes of one upstream holds on its own."""
    values = [
        _node(atom, lookup, Reading()) for atom in _atoms(condition.root) if atom.ref.parts == name
    ]
    if not values:
        return True
    return False if False in values else (None if None in values else True)
