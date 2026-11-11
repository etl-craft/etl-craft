"""Parse explicit rule-result scopes outside SQL literals and comments."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from etl_craft.core.enums import RuleFlagType
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.text import is_metadata_code, sql_parts

KEY_CAP = 10_000
_PATTERN = re.compile(r"\$\$rule_flags\s*\(([^()]*)\)")
_TYPES = frozenset(RuleFlagType)


@dataclass(frozen=True)
class RuleScope:
    """One named upstream task and an explicit union of row-rule types."""

    task: str
    types: tuple[str, ...]

    @property
    def token(self) -> str:
        """Render the canonical scope for diagnostics and audit."""
        return f"$$rule_flags({self.task}, {', '.join(self.types)})"


def replace_scopes(sql: str, render: Callable[[RuleScope], str]) -> str:
    """Replace scopes without interpreting quoted text or comments as instructions."""

    def part(value: str) -> str:
        def found(match: re.Match[str]) -> str:
            pieces = [x.strip() for x in match[1].split(",")]
            if (
                len(pieces) < 2
                or not is_metadata_code(pieces[0])
                or any(x not in _TYPES for x in pieces[1:])
                or len(set(pieces[1:])) != len(pieces[1:])
            ):
                raise SqlGuardError(
                    f"{match[0]}: expected task code and explicit unique REJECT, INCOMPLETE "
                    "or REPORT types; remedy: correct the rule_flags scope"
                )
            return render(RuleScope(pieces[0], tuple(pieces[1:])))

        remaining = _PATTERN.sub("", value)
        if "$$rule_flags" in remaining:
            raise SqlGuardError(
                f"{value}: expected $$rule_flags(task, TYPE[, TYPE]); "
                "remedy: close the scope and name explicit rule types"
            )
        return _PATTERN.sub(found, value)

    return "".join(
        value if protected else part(value)
        for value, protected in sql_parts(sql, placeholders=True)
    )


def parse_scopes(sql: str) -> tuple[RuleScope, ...]:
    """Collect each scope in statement order, including repeated references."""
    scopes: list[RuleScope] = []

    def collect(scope: RuleScope) -> str:
        scopes.append(scope)
        return ""

    replace_scopes(sql, collect)
    return tuple(scopes)


def placeholder(scope: RuleScope) -> str:
    """Keep a typed subquery identifiable through ordinary token resolution."""
    return f"SELECT CAST(NULL AS VARCHAR) AS rule_key WHERE 1=0 /* {scope.token} */"
