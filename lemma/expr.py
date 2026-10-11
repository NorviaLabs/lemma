"""A small, safe expression language shared by the server and the browser.

Models describe their numbers with expressions such as ``normcdf(d / 2) * 100``.
The same grammar is implemented in ``static/expr.js``; keep the two in step.

Grammar (lowest to highest precedence)::

    ternary  := or ('?' ternary ':' ternary)?
    or       := and (('||' | 'or') and)*
    and      := cmp (('&&' | 'and') cmp)*
    cmp      := add (('<' | '<=' | '>' | '>=' | '==' | '!=') add)?
    add      := mul (('+' | '-') mul)*
    mul      := unary (('*' | '/' | '%') unary)*
    unary    := ('-' | '+' | '!' | 'not') unary | power
    power    := atom ('^' unary)?
    atom     := number | name | name '(' args ')' | '(' ternary ')'

Booleans are numbers: comparisons and logic return 1 or 0.
"""

from __future__ import annotations

import math
import re

__all__ = ["ExprError", "parse", "evaluate", "names", "FUNCTIONS", "CONSTANTS"]


class ExprError(ValueError):
    pass


_TOKEN = re.compile(
    r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|([A-Za-z_][A-Za-z0-9_]*)"
    r"|(<=|>=|==|!=|&&|\|\||[-+*/%^()<>!?:,]))"
)


def _tokenize(src: str) -> list[tuple[str, str]]:
    if not isinstance(src, str):
        raise ExprError("expression must be a string")
    tokens, pos = [], 0
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExprError(f"unexpected character {src[pos]!r} in {src!r}")
        num, name, op = m.groups()
        if num is not None:
            tokens.append(("num", num))
        elif name is not None:
            tokens.append(("name", name))
        else:
            tokens.append(("op", op))
        pos = m.end()
    tokens.append(("end", ""))
    return tokens


def _nan() -> float:
    return float("nan")


def _div(a, b):
    if b == 0:
        return _nan() if a == 0 or a != a else math.copysign(math.inf, a) * (math.copysign(1, b))
    return a / b


def _mod(a, b):
    if b == 0:
        return _nan()
    return math.fmod(a, b)  # JS % keeps the sign of the dividend


def _pow(a, b):
    try:
        r = math.pow(a, b)
    except OverflowError:
        return math.inf
    except ValueError:
        return _nan()
    return r


def _safe(fn):
    def wrapped(*args):
        try:
            return float(fn(*args))
        except OverflowError:
            return math.inf
        except (ValueError, ZeroDivisionError):
            return _nan()

    return wrapped


def _log(x):
    if x == 0:
        return -math.inf
    return math.log(x)


def _erf(x):
    # Abramowitz & Stegun 7.1.26, written identically in expr.js so both sides agree.
    s = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + 0.3275911 * x)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return s * y


def _normcdf(x, mu=0.0, sd=1.0):
    if sd <= 0:
        return _nan()
    return 0.5 * (1 + _erf((x - mu) / (sd * math.sqrt(2))))


def _normpdf(x, mu=0.0, sd=1.0):
    if sd <= 0:
        return _nan()
    z = (x - mu) / sd
    return math.exp(-0.5 * z * z) / (sd * math.sqrt(2 * math.pi))


def _norminv(p, mu=0.0, sd=1.0):
    # Acklam's rational approximation, then two bisection-free Newton steps are skipped
    # to keep both implementations bit-for-bit simple.
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        z = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= 1 - plow:
        q = p - 0.5
        r = q * q
        z = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        z = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    return mu + sd * z


def _round(x, digits=0):
    # JS-style rounding: half rounds up (towards +infinity).
    f = 10 ** int(digits)
    return math.floor(x * f + 0.5) / f


def _binom(n, k):
    n, k = int(round(n)), int(round(k))
    if k < 0 or k > n or n < 0:
        return 0.0
    return float(math.comb(n, k))


def _clamp(x, lo, hi):
    return min(max(x, lo), hi)


def _logistic(x):
    if x < -700:
        return 0.0
    return 1 / (1 + math.exp(-x))


FUNCTIONS: dict[str, tuple[object, int, int]] = {
    # name: (fn, min_args, max_args)
    "abs": (abs, 1, 1),
    "sqrt": (math.sqrt, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (_log, 1, 1),
    "ln": (_log, 1, 1),
    "log10": (lambda x: _log(x) / math.log(10), 1, 1),
    "pow": (_pow, 2, 2),
    "min": (min, 1, 16),
    "max": (max, 1, 16),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "round": (_round, 1, 2),
    "clamp": (_clamp, 3, 3),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "atan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "erf": (_erf, 1, 1),
    "normpdf": (_normpdf, 1, 3),
    "normcdf": (_normcdf, 1, 3),
    "norminv": (_norminv, 1, 3),
    "binom": (_binom, 2, 2),
    "logistic": (_logistic, 1, 1),
    "sign": (lambda x: (x > 0) - (x < 0), 1, 1),
}

CONSTANTS = {"pi": math.pi, "e": math.e, "true": 1.0, "false": 0.0}

_KEYWORDS = {"and": "&&", "or": "||", "not": "!"}


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = [("op", _KEYWORDS[v]) if k == "name" and v in _KEYWORDS else (k, v) for k, v in _tokenize(src)]
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, *ops):
        k, v = self.peek()
        if k == "op" and v in ops:
            self.i += 1
            return v
        return None

    def expect(self, op):
        if not self.accept(op):
            raise ExprError(f"expected {op!r} in {self.src!r}")

    def parse(self):
        node = self.ternary()
        if self.peek()[0] != "end":
            raise ExprError(f"unexpected {self.peek()[1]!r} in {self.src!r}")
        return node

    def ternary(self):
        cond = self.or_()
        if self.accept("?"):
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return ("?", cond, a, b)
        return cond

    def or_(self):
        node = self.and_()
        while self.accept("||"):
            node = ("||", node, self.and_())
        return node

    def and_(self):
        node = self.cmp()
        while self.accept("&&"):
            node = ("&&", node, self.cmp())
        return node

    def cmp(self):
        node = self.add()
        op = self.accept("<", "<=", ">", ">=", "==", "!=")
        if op:
            node = (op, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while True:
            op = self.accept("+", "-")
            if not op:
                return node
            node = (op, node, self.mul())

    def mul(self):
        node = self.unary()
        while True:
            op = self.accept("*", "/", "%")
            if not op:
                return node
            node = (op, node, self.unary())

    def unary(self):
        op = self.accept("-", "+", "!")
        if op:
            return ("u" + op, self.unary())
        return self.power()

    def power(self):
        base = self.atom()
        if self.accept("^"):
            return ("^", base, self.unary())
        return base

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v))
        if k == "name":
            if self.accept("("):
                args = []
                if not self.accept(")"):
                    args.append(self.ternary())
                    while self.accept(","):
                        args.append(self.ternary())
                    self.expect(")")
                if v not in FUNCTIONS:
                    raise ExprError(f"unknown function {v!r}")
                _, lo, hi = FUNCTIONS[v]
                if not lo <= len(args) <= hi:
                    raise ExprError(f"{v}() takes {lo}–{hi} arguments, got {len(args)}")
                return ("call", v, args)
            if v in CONSTANTS:
                return ("num", CONSTANTS[v])
            return ("name", v)
        if k == "op" and v == "(":
            node = self.ternary()
            self.expect(")")
            return node
        raise ExprError(f"unexpected {v or 'end of expression'!r} in {self.src!r}")


_cache: dict[str, tuple] = {}


def parse(src: str) -> tuple:
    if isinstance(src, (int, float)) and not isinstance(src, bool):
        return ("num", float(src))
    node = _cache.get(src)
    if node is None:
        node = _Parser(src).parse()
        if len(_cache) < 5000:
            _cache[src] = node
    return node


def names(src) -> set[str]:
    """Variable names an expression reads."""
    out: set[str] = set()

    def walk(n):
        tag = n[0]
        if tag == "name":
            out.add(n[1])
        elif tag == "call":
            for a in n[2]:
                walk(a)
        elif tag != "num":
            for a in n[1:]:
                walk(a)

    walk(parse(src))
    return out


def _b(x) -> float:
    return 1.0 if x else 0.0


def _eval(n, env):
    tag = n[0]
    if tag == "num":
        return n[1]
    if tag == "name":
        try:
            return float(env[n[1]])
        except KeyError:
            raise ExprError(f"unknown name {n[1]!r}") from None
    if tag == "call":
        fn = FUNCTIONS[n[1]][0]
        return _safe(fn)(*[_eval(a, env) for a in n[2]])
    if tag == "?":
        return _eval(n[2], env) if _eval(n[1], env) else _eval(n[3], env)
    if tag == "u-":
        return -_eval(n[1], env)
    if tag == "u+":
        return _eval(n[1], env)
    if tag == "u!":
        return _b(not _eval(n[1], env))
    if tag == "&&":
        return _b(_eval(n[1], env) and _eval(n[2], env))
    if tag == "||":
        return _b(_eval(n[1], env) or _eval(n[2], env))
    a, b = _eval(n[1], env), _eval(n[2], env)
    if tag == "+":
        return a + b
    if tag == "-":
        return a - b
    if tag == "*":
        return a * b
    if tag == "/":
        return _div(a, b)
    if tag == "%":
        return _mod(a, b)
    if tag == "^":
        return _pow(a, b)
    if tag == "<":
        return _b(a < b)
    if tag == "<=":
        return _b(a <= b)
    if tag == ">":
        return _b(a > b)
    if tag == ">=":
        return _b(a >= b)
    if tag == "==":
        return _b(abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b)))
    if tag == "!=":
        return _b(abs(a - b) > 1e-9 * max(1.0, abs(a), abs(b)))
    raise ExprError(f"bad node {tag}")


def evaluate(src, env: dict) -> float:
    try:
        return _eval(parse(src), env)
    except RecursionError:
        raise ExprError("expression is too deeply nested") from None
    except (OverflowError, ZeroDivisionError):
        return math.inf
