"""Minimal S-expression reader/writer for KiCad files.

Strings stay distinguishable from bare atoms (Str vs plain str) so a round trip keeps
KiCad's quoting.
"""


class Str(str):
    """A quoted string token."""


def parse(text):
    stack, cur, i, n = [], [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            stack.append(cur)
            cur = []
            i += 1
        elif ch == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
            i += 1
        elif ch == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    nxt = text[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            cur.append(Str("".join(buf)))
            i = j + 1
        elif ch.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            cur.append(text[i:j])
            i = j
    return cur[0]


def quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def dump(node, indent=0):
    if isinstance(node, Str):
        return quote(node)
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return fmt_num(node)
    inner = [dump(x, indent + 1) for x in node]
    flat = "(" + " ".join(inner) + ")"
    if len(flat) < 100 and not any(isinstance(x, list) and len(x) > 4 for x in node):
        return flat
    pad = "\n" + "\t" * (indent + 1)
    head = [inner[0]]
    rest = []
    for x, s in zip(node[1:], inner[1:]):
        if isinstance(x, list):
            rest.append(pad + s)
        else:
            if rest:
                rest.append(pad + s)
            else:
                head.append(s)
    return "(" + " ".join(head) + "".join(rest) + "\n" + "\t" * indent + ")"


def fmt_num(v):
    if isinstance(v, int):
        return str(v)
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(node, key):
    """First child list whose head is key."""
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def find_all(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]
