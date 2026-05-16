from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.workflows.state import WorkflowState


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any


class _ParseError(ValueError):
    pass


class WorkflowConditionEvaluator:
    """Evaluate a deliberately tiny, safe workflow edge condition language."""

    def matches(self, condition: str | None, state: WorkflowState) -> bool:
        if not condition or not condition.strip():
            return True
        try:
            parser = _ConditionParser(_Tokenizer(condition).tokens(), state)
            return bool(parser.parse())
        except _ParseError:
            return False


class _Tokenizer:
    _TWO_CHAR_OPERATORS = {"&&", "||", "==", "!=", "<=", ">="}
    _ONE_CHAR_TOKENS = {"(", ")", "!", "<", ">"}

    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0

    def tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        while self.index < len(self.source):
            char = self.source[self.index]
            if char.isspace():
                self.index += 1
                continue
            two = self.source[self.index : self.index + 2]
            if two in self._TWO_CHAR_OPERATORS:
                tokens.append(_Token(two, two))
                self.index += 2
                continue
            if char in self._ONE_CHAR_TOKENS:
                tokens.append(_Token(char, char))
                self.index += 1
                continue
            if char in {"'", '"'}:
                tokens.append(_Token("literal", self._read_string(char)))
                continue
            if char.isdigit() or (char == "-" and self._next_char_is_digit()):
                tokens.append(_Token("literal", self._read_number()))
                continue
            if char.isalpha() or char == "_":
                tokens.append(self._read_identifier_or_keyword())
                continue
            raise _ParseError(f"Unsupported character in condition: {char}")
        tokens.append(_Token("eof", None))
        return tokens

    def _next_char_is_digit(self) -> bool:
        return self.index + 1 < len(self.source) and self.source[self.index + 1].isdigit()

    def _read_string(self, quote: str) -> str:
        self.index += 1
        chars: list[str] = []
        while self.index < len(self.source):
            char = self.source[self.index]
            if char == "\\":
                if self.index + 1 >= len(self.source):
                    raise _ParseError("Unterminated escape sequence.")
                next_char = self.source[self.index + 1]
                if next_char not in {quote, "\\", "n", "r", "t"}:
                    raise _ParseError("Unsupported string escape.")
                chars.append({"n": "\n", "r": "\r", "t": "\t"}.get(next_char, next_char))
                self.index += 2
                continue
            if char == quote:
                self.index += 1
                return "".join(chars)
            chars.append(char)
            self.index += 1
        raise _ParseError("Unterminated string literal.")

    def _read_number(self) -> int | float:
        start = self.index
        if self.source[self.index] == "-":
            self.index += 1
        while self.index < len(self.source) and self.source[self.index].isdigit():
            self.index += 1
        if self.index < len(self.source) and self.source[self.index] == ".":
            self.index += 1
            if self.index >= len(self.source) or not self.source[self.index].isdigit():
                raise _ParseError("Invalid number literal.")
            while self.index < len(self.source) and self.source[self.index].isdigit():
                self.index += 1
            return float(self.source[start : self.index])
        return int(self.source[start : self.index])

    def _read_identifier_or_keyword(self) -> _Token:
        start = self.index
        while self.index < len(self.source):
            char = self.source[self.index]
            if not (char.isalnum() or char in {"_", "."}):
                break
            self.index += 1
        value = self.source[start : self.index]
        lowered = value.lower()
        if lowered == "true":
            return _Token("literal", True)
        if lowered == "false":
            return _Token("literal", False)
        if lowered == "null":
            return _Token("literal", None)
        if not _is_valid_path(value):
            raise _ParseError(f"Invalid path: {value}")
        return _Token("path", value)


def _is_valid_path(value: str) -> bool:
    if not value or value.startswith(".") or value.endswith(".") or ".." in value:
        return False
    parts = value.split(".")
    for index, part in enumerate(parts):
        if not part:
            return False
        if part.isdigit():
            if index == 0:
                return False
            continue
        if part[0].isdigit() or not part.replace("_", "a").isalnum():
            return False
    return True


class _ConditionParser:
    _COMPARISON_OPERATORS = {"==", "!=", "<", "<=", ">", ">="}

    def __init__(self, tokens: list[_Token], state: WorkflowState) -> None:
        self.tokens = tokens
        self.state = state
        self.index = 0

    def parse(self) -> bool:
        value = self._parse_or()
        self._expect("eof")
        return self._truthy(value)

    def _parse_or(self) -> Any:
        value = self._parse_and()
        while self._match("||"):
            if self._truthy(value):
                self._parse_and()
                value = True
            else:
                value = self._parse_and()
        return value

    def _parse_and(self) -> Any:
        value = self._parse_not()
        while self._match("&&"):
            if not self._truthy(value):
                self._parse_not()
                value = False
            else:
                value = self._parse_not()
        return value

    def _parse_not(self) -> Any:
        if self._match("!"):
            return not self._truthy(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Any:
        left = self._parse_primary()
        token = self._peek()
        if token.kind not in self._COMPARISON_OPERATORS:
            return left
        self.index += 1
        right = self._parse_primary()
        return self._compare(left, token.kind, right)

    def _parse_primary(self) -> Any:
        token = self._peek()
        if token.kind == "literal":
            self.index += 1
            return token.value
        if token.kind == "path":
            self.index += 1
            return self._resolve_path(str(token.value))
        if self._match("("):
            value = self._parse_or()
            self._expect(")")
            return value
        raise _ParseError(f"Expected literal, path, or grouped expression; got {token.kind}.")

    def _compare(self, left: Any, operator: str, right: Any) -> bool:
        if operator in {"==", "!="}:
            result = self._equals(left, right)
            return result if operator == "==" else not result

        numbers = self._numeric_pair(left, right)
        if numbers is None:
            return False
        left_number, right_number = numbers
        if operator == "<":
            return left_number < right_number
        if operator == "<=":
            return left_number <= right_number
        if operator == ">":
            return left_number > right_number
        if operator == ">=":
            return left_number >= right_number
        return False

    def _equals(self, left: Any, right: Any) -> bool:
        if isinstance(left, str) and isinstance(right, str):
            return left.strip().lower() == right.strip().lower()
        return left == right

    def _numeric_pair(self, left: Any, right: Any) -> tuple[float, float] | None:
        if isinstance(left, bool) or isinstance(right, bool):
            return None
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return None
        return float(left), float(right)

    def _truthy(self, value: Any) -> bool:
        return bool(value)

    def _resolve_path(self, path: str) -> Any:
        current: Any = self.state
        for part in path.split("."):
            if part == "length":
                current = self._length(current)
            elif isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if 0 <= index < len(current) else None
            else:
                return None
        return current

    def _length(self, value: Any) -> int | None:
        if isinstance(value, (dict, list, str)):
            return len(value)
        return None

    def _peek(self) -> _Token:
        return self.tokens[self.index]

    def _match(self, kind: str) -> bool:
        if self._peek().kind != kind:
            return False
        self.index += 1
        return True

    def _expect(self, kind: str) -> _Token:
        token = self._peek()
        if token.kind != kind:
            raise _ParseError(f"Expected {kind}; got {token.kind}.")
        self.index += 1
        return token
