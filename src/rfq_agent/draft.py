"""Source-backed bid draft: runtime schema, Decimal arithmetic and dependency closure.

The model proposes the draft; this module only checks it. Nothing here supplies a
value: a number without evidence, a brief rule or a checked calculation is refused.
"""

import ast
import json
import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation

ROUNDING = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN, "DOWN": ROUND_DOWN, "UP": ROUND_UP}
ALL_OMITTED = "all_positions_omitted"
# Structural constants a formula may contain; every other number must be a sourced input.
FORMULA_CONSTANTS = {Decimal(0), Decimal(1), Decimal(100)}
ZERO_WORDS = re.compile(r"\b(zero|null|none|no|kein\w*|ohne)\b", re.IGNORECASE)


def names_position(text: str, position: str) -> bool:
    """position occurs in text as a whole token."""
    return bool(position) and re.search(rf"(?<!\w){re.escape(str(position))}(?!\w)", text or "") is not None


def _states_number(value, quote: str) -> bool:
    number = _decimal(value)
    return number in parse_numbers(quote) or (number == 0 and bool(ZERO_WORDS.search(quote)))


def formula_terms(expression) -> tuple[set, set]:
    """(input names, numeric literals) used by a calculation expression."""
    if not isinstance(expression, str) or len(expression) > 500:
        raise DraftError("calculation must be a short expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise DraftError("calculation could not be parsed") from exc
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - set(_FUNCTIONS)
    literals = {_decimal(node.value) for node in ast.walk(tree) if isinstance(node, ast.Constant) and _is_number(node.value)}
    return names, literals


class DraftError(ValueError):
    pass


def _is_number(value) -> bool:
    return isinstance(value, (int, Decimal, float)) and not isinstance(value, bool)


def _decimal(value) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DraftError(f"not a decimal number: {str(value)[:40]}") from exc


def parse_numbers(text: str) -> set[Decimal]:
    """Every reading of the numeric tokens in text, tolerant of , and . conventions."""
    found: set[Decimal] = set()
    for token in re.findall(r"\d[\d.,']*\d|\d", text or ""):
        token = token.replace("'", "")
        readings = []
        if "." in token and "," in token:
            decimal_mark = "." if token.rfind(".") > token.rfind(",") else ","
            other = "," if decimal_mark == "." else "."
            readings.append(token.replace(other, "").replace(decimal_mark, "."))
        elif "." in token or "," in token:
            mark = "." if "." in token else ","
            if token.count(mark) > 1:
                readings.append(token.replace(mark, ""))
            else:
                readings.append(token.replace(mark, "."))
                if len(token.rsplit(mark, 1)[1]) == 3:
                    readings.append(token.replace(mark, ""))
        else:
            readings.append(token)
        for reading in readings:
            try:
                found.add(Decimal(reading))
            except InvalidOperation:
                pass
    return found


_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_FUNCTIONS = {"min": min, "max": max}


def evaluate(expression: str, inputs: dict) -> Decimal:
    """Decimal arithmetic over named inputs: + - * /, min and max only."""
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and _is_number(node.value):
            return _decimal(node.value)
        if isinstance(node, ast.Name) and node.id in inputs:
            return _decimal(inputs[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
                and node.args and not node.keywords):
            return _FUNCTIONS[node.func.id](walk(arg) for arg in node.args)
        raise DraftError("unsupported term in calculation")
    if not isinstance(expression, str) or len(expression) > 500:
        raise DraftError("calculation must be a short expression")
    try:
        return walk(ast.parse(expression, mode="eval"))
    except (SyntaxError, InvalidOperation, ZeroDivisionError) as exc:
        raise DraftError(f"calculation could not be evaluated ({type(exc).__name__})") from exc


def _json_number(_checker, value) -> bool:
    return _is_number(value)


def _json_integer(_checker, value) -> bool:
    return _is_number(value) and _decimal(value) == _decimal(value).to_integral_value()


def validate_schema(value, schema) -> list[str]:
    """Validate against the run's JSON schema in its declared dialect; refs are never fetched."""
    if schema is None:
        return []
    import jsonschema
    import referencing
    try:
        normalized = json.loads(json.dumps(schema), parse_float=Decimal)
        base = jsonschema.validators.validator_for(normalized, default=jsonschema.Draft202012Validator)
        base.check_schema(normalized)
        checker = base.TYPE_CHECKER.redefine_many({"number": _json_number, "integer": _json_integer})
        validator = jsonschema.validators.extend(base, type_checker=checker)(normalized, registry=referencing.Registry())
        issues = sorted(validator.iter_errors(value), key=lambda issue: [str(part) for part in issue.absolute_path])
        return [f"{'.'.join(str(part) for part in issue.absolute_path) or 'answer'}: {issue.message[:160]}"
                for issue in issues][:20]
    except jsonschema.SchemaError as exc:
        return [f"the run's answer schema is not a valid schema ({exc.message[:120]})"]
    except Exception as exc:
        return [f"the run's answer schema could not be applied ({type(exc).__name__}); unresolved references are not fetched"]


def resolve(document, path: str):
    value = document
    for part in path.split("."):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


def leaves(value, path: str = ""):
    if isinstance(value, dict):
        for name, item in value.items():
            yield from leaves(item, f"{path}.{name}" if path else str(name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, f"{path}.{index}" if path else str(index))
    elif value is not None and value != "":
        yield path, value


@dataclass(frozen=True)
class Draft:
    reference: str
    answer: dict
    identity: dict
    priced: tuple
    omitted: tuple
    no_bid: bool

    def value(self, path: str):
        """One submit-ready scalar: an answer path, or identity.<name>."""
        if path.startswith("identity."):
            return self.identity[path[len("identity."):]]
        value = resolve(self.answer, path)
        if isinstance(value, (dict, list)) or value is None:
            raise KeyError(path)
        return value

    def priced_paths(self) -> dict:
        return dict(self.priced)


def validate_draft(candidate, schema, brief: str, evidence: list, capabilities: dict, checklist=None) -> Draft:
    """Return the checked draft, or raise DraftError listing what is not source-backed.

    `evidence` also carries the separately observed tender inventory (kind "position") and
    catalogue searches; `checklist` is the separately established list of cross-position rules
    (None: not established). The draft can neither shrink the inventory nor the checklist."""
    if not isinstance(candidate, dict):
        raise DraftError("draft must be a JSON object")
    quotes = [item.quote for item in evidence]
    errors: list[str] = []

    def cited(ids) -> list[str] | None:
        ids = ids if isinstance(ids, list) else [ids]
        if not ids or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(quotes) for i in ids):
            return None
        return [quotes[i] for i in ids]

    def in_brief(quote) -> bool:
        return isinstance(quote, str) and bool(quote.strip()) and quote in brief

    def backed(entry) -> bool:
        return isinstance(entry, dict) and (cited(entry.get("evidence", [])) is not None or in_brief(entry.get("quote")))

    reference = candidate.get("reference")
    if not isinstance(reference, str) or not reference.strip() or not (
            reference in brief or any(reference in quote for quote in quotes)):
        errors.append("reference is not found verbatim in the run brief or recorded evidence")
        reference = reference if isinstance(reference, str) else ""
    answer = candidate.get("answer")
    if not isinstance(answer, dict):
        raise DraftError("draft.answer must be an object matching the run's answer schema")
    errors += [f"schema: {issue}" for issue in validate_schema(answer, schema)]
    answer_leaves = dict(leaves(answer))
    if reference and reference not in [value for value in answer_leaves.values() if isinstance(value, str)]:
        errors.append("answer does not carry the exact tender reference")

    sources = candidate.get("sources") if isinstance(candidate.get("sources"), dict) else {}
    priced_declared = candidate.get("priced") if isinstance(candidate.get("priced"), list) else []

    def depends_on(path) -> list[str]:
        source = sources.get(path)
        if not isinstance(source, dict) or source.get("kind") != "calculation" or not isinstance(source.get("inputs"), dict):
            return []
        return [item["path"] for item in source["inputs"].values() if isinstance(item, dict) and isinstance(item.get("path"), str)]

    def circular(path, trail=()) -> bool:
        return path in trail or any(circular(other, trail + (path,)) for other in depends_on(path))
    for path, value in answer_leaves.items():
        source = sources.get(path)
        kind = source.get("kind") if isinstance(source, dict) else None
        numeric = _is_number(value)
        if kind == "evidence":
            texts = cited(source.get("evidence", []))
            if texts is None:
                errors.append(f"{path}: cites no valid evidence id")
            elif numeric and not any(_decimal(value) in parse_numbers(text) for text in texts):
                errors.append(f"{path}: value not found in cited evidence")
            elif isinstance(value, bool):
                errors.append(f"{path}: use an interpretation source for a yes/no value")
            elif isinstance(value, str) and not any(value in text for text in texts):
                errors.append(f"{path}: value not found verbatim in cited evidence; cite it or use interpretation")
        elif kind == "rule":
            if not in_brief(source.get("quote")):
                errors.append(f"{path}: rule quote is not in the run brief")
            elif numeric and not _states_number(value, source["quote"]):
                errors.append(f"{path}: the quoted brief rule does not state this number")
        elif kind == "empty_total":
            if not numeric or _decimal(value) != 0 or priced_declared:
                errors.append(f"{path}: empty_total is only the zero sum of a bid without priced positions")
        elif kind == "interpretation":
            if numeric:
                errors.append(f"{path}: numeric values need evidence, a brief rule or a calculation")
            elif not backed(source):
                errors.append(f"{path}: interpretation cites no evidence or brief quote")
        elif kind == "calculation":
            if not numeric:
                errors.append(f"{path}: only numbers can be calculated")
                continue
            if circular(path):
                errors.append(f"{path}: circular calculation; a derived value must end in evidenced facts")
                continue
            try:
                names, literals = formula_terms(source.get("expression"))
                declared = source.get("inputs") if isinstance(source.get("inputs"), dict) else {}
                if not names or names != set(declared):
                    raise DraftError("a calculation must use at least one sourced input and exactly its declared inputs")
                if literals - FORMULA_CONSTANTS:
                    raise DraftError("numbers inside a calculation must be sourced inputs, not literals")
                inputs = {}
                for name, item in declared.items():
                    if not isinstance(item, dict):
                        raise DraftError(f"input {name} is malformed")
                    if "path" in item:
                        other = answer_leaves.get(item["path"])
                        if not _is_number(other):
                            raise DraftError(f"input {name} is not a numeric answer value")
                        inputs[name] = _decimal(other)
                        continue
                    number = _decimal(item.get("value"))
                    texts = cited(item["evidence"]) if "evidence" in item else (
                        [item["quote"]] if in_brief(item.get("quote")) else None)
                    if texts is None or not any(_states_number(number, text) for text in texts):
                        raise DraftError(f"input {name} is not found in its cited evidence or brief quote")
                    inputs[name] = number
                result = evaluate(source.get("expression"), inputs)
                rounding = source.get("round")
                if isinstance(rounding, dict):
                    result = result.quantize(Decimal(1).scaleb(-int(rounding.get("places", 2))),
                                             ROUNDING.get(str(rounding.get("mode", "HALF_UP")).upper(), ROUND_HALF_UP))
                if result != _decimal(value):
                    errors.append(f"{path}: calculation gives {result}, not {value}")
            except (DraftError, TypeError, ValueError) as exc:
                errors.append(f"{path}: {exc}")
        else:
            errors.append(f"{path}: no source; cite evidence, a brief rule or a calculation, or leave it out")

    identity = {}
    for name, entry in (candidate.get("identity") or {}).items():
        texts = cited(entry.get("evidence", [])) if isinstance(entry, dict) else None
        value = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(value, str) or not value or texts is None or not any(value in text for text in texts):
            errors.append(f"identity.{name}: value not found verbatim in cited evidence")
        else:
            identity[str(name)] = value

    priced_entries = candidate.get("priced") if isinstance(candidate.get("priced"), list) else []
    priced: list[tuple[str, str]] = []
    for entry in priced_entries:
        try:
            position, path = str(entry["id"]), str(entry["path"])
            if not isinstance(resolve(answer, path), dict):
                raise KeyError(path)
            priced.append((position, path))
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append("priced entries need an id and the answer path of that position object")
    omitted_entries = candidate.get("omitted") if isinstance(candidate.get("omitted"), list) else []
    omitted = [str(entry.get("position")) for entry in omitted_entries
               if isinstance(entry, dict) and entry.get("position") not in (None, "")]
    if len(omitted) != len(omitted_entries) or not all(
            isinstance(entry.get("reason"), str) and entry["reason"].strip() for entry in omitted_entries
            if isinstance(entry, dict)):
        errors.append("each omitted entry needs a position and a reason")
    priced_ids = [position for position, _ in priced]
    if len(set(priced_ids + omitted)) != len(priced_ids + omitted) or len({path for _, path in priced}) != len(priced):
        errors.append("a position may appear once: either priced or omitted")
    priced_roots = [path for _, path in priced]
    for path, value in ((p, v) for p, v in _list_objects(answer)):
        if not any(path == root or path.startswith(root + ".") for root in priced_roots):
            errors.append(f"answer element {path} is not declared as a priced position")

    inventory = list(dict.fromkeys(item.subject for item in evidence if item.kind == "position" and item.subject))
    if not inventory:
        errors.append("the tender inventory has not been observed: record each tender position as evidence of kind "
                      "position before drafting")
    unknown = [position for position in priced_ids + omitted if position not in inventory]
    if inventory and unknown:
        errors.append("positions that were never observed in the tender inventory: " + ", ".join(unknown))

    no_bid = candidate.get("no_bid") is True
    if no_bid:
        basis = candidate.get("no_bid_basis") if isinstance(candidate.get("no_bid_basis"), dict) else {}
        searches = basis.get("searches") if isinstance(basis.get("searches"), dict) else {}

        def searched(position) -> bool:
            ids = searches.get(position)
            return (isinstance(ids, list) and bool(ids) and cited(ids) is not None
                    and all(evidence[i].kind == "catalogue_search" and evidence[i].subject == position for i in ids))
        unsearched = [position for position in inventory if not searched(position)]
        if priced or omitted or unsearched or not inventory:
            errors.append("no_bid needs catalogue_search evidence of a completed exact-match search for every tender "
                          "position (missing: " + (", ".join(unsearched) or "none") + ") and cannot stand in for "
                          "unresolved positions; omit unfinished positions instead")
    else:
        missing = [position for position in inventory if position not in priced_ids + omitted]
        if missing:
            errors.append("positions neither priced nor explicitly omitted: " + ", ".join(missing))
        if not priced and not (capabilities.get(ALL_OMITTED) or {}).get("supported") is True:
            errors.append(f"{ALL_OMITTED} capability has not been observed as supported; price a resolved position")

    closure = candidate.get("closure") if isinstance(candidate.get("closure"), dict) else {}
    if priced and checklist is None:
        errors.append("the dependency checklist has not been established from the run brief; a position cannot be priced yet")
    for rule in checklist or []:
        name = rule.get("name") if isinstance(rule, dict) else None
        for position in priced_ids:
            entry = (closure.get(position) or {}).get(name) if isinstance(closure.get(position), dict) else None
            if not (isinstance(entry, dict) and entry.get("status") in {"resolved", "not_applicable"} and backed(entry)):
                errors.append(f"{position}: dependency {name} is unresolved; resolve it with evidence or omit the position")

    if errors:
        raise DraftError("; ".join(errors[:14]))
    return Draft(reference, answer, identity, tuple(priced), tuple(omitted), no_bid)


def _list_objects(value, path: str = ""):
    """Objects that are list elements: the answer's repeated records."""
    if isinstance(value, dict):
        for name, item in value.items():
            yield from _list_objects(item, f"{path}.{name}" if path else str(name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{path}.{index}" if path else str(index)
            if isinstance(item, dict):
                yield child, item
            yield from _list_objects(item, child)
