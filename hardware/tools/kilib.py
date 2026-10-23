"""Read KiCad stock symbols: flatten `extends`, list pins, compute body extents."""
import copy
import math

from sexpr import Str, find, find_all, parse

SYM_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/"
_libs = {}


def _lib(name):
    if name not in _libs:
        with open(SYM_DIR + name + ".kicad_sym") as f:
            _libs[name] = parse(f.read())
    return _libs[name]


def _raw(lib, name):
    for s in find_all(_lib(lib), "symbol"):
        if s[1] == name:
            return s
    raise KeyError(f"{lib}:{name} not found")


def load(lib_id):
    """Flattened symbol definition named 'Lib:Name', ready for a schematic's lib_symbols."""
    lib, name = lib_id.split(":", 1)
    sym = copy.deepcopy(_raw(lib, name))
    ext = find(sym, "extends")
    if ext:
        parent = load(f"{lib}:{ext[1]}")
        child_props = {p[1]: p for p in find_all(sym, "property")}
        flat = [x for x in parent if not (isinstance(x, list) and x[0] in ("property", "symbol"))]
        flat[1] = Str(lib_id)
        props = []
        for p in find_all(parent, "property"):
            props.append(child_props.pop(p[1], p))
        props += list(child_props.values())
        units = []
        pname = parent[1].split(":", 1)[1]
        for u in find_all(parent, "symbol"):
            u = copy.deepcopy(u)
            u[1] = Str(u[1].replace(pname, name, 1))
            units.append(u)
        keep = [x for x in flat if not (isinstance(x, list) and x[0] in ("embedded_fonts",))]
        sym = keep + props + units + [x for x in flat if isinstance(x, list) and x[0] == "embedded_fonts"]
    sym[1] = Str(lib_id)
    return sym


def pins(sym):
    """[(number, name, type, x, y, angle_deg, length)] in symbol coords (Y up), body style 1 only."""
    out = []
    for u in find_all(sym, "symbol"):
        if not u[1].endswith("_1") and not u[1].endswith("_0"):
            continue
        style = u[1].rsplit("_", 1)[1]
        if style not in ("0", "1"):
            continue
        for p in find_all(u, "pin"):
            at = find(p, "at")
            ln = find(p, "length")
            out.append((find(p, "number")[1], find(p, "name")[1], p[1],
                        float(at[1]), float(at[2]), float(at[3]), float(ln[1]) if ln else 2.54))
    return out


def props(sym):
    return {p[1]: p[2] for p in find_all(sym, "property")}


def body_extent(sym):
    """(minx, miny, maxx, maxy) of graphics and pins in schematic orientation (Y down)."""
    xs, ys = [], []

    def add(x, y):
        xs.append(x)
        ys.append(-y)

    for u in find_all(sym, "symbol"):
        for g in u:
            if not isinstance(g, list):
                continue
            if g[0] == "rectangle":
                s, e = find(g, "start"), find(g, "end")
                add(float(s[1]), float(s[2]))
                add(float(e[1]), float(e[2]))
            elif g[0] in ("polyline", "bezier"):
                for xy in find_all(find(g, "pts"), "xy"):
                    add(float(xy[1]), float(xy[2]))
            elif g[0] == "circle":
                c, r = find(g, "center"), float(find(g, "radius")[1])
                add(float(c[1]) - r, float(c[2]) - r)
                add(float(c[1]) + r, float(c[2]) + r)
            elif g[0] == "arc":
                for k in ("start", "mid", "end"):
                    q = find(g, k)
                    add(float(q[1]), float(q[2]))
    for num, name, typ, x, y, ang, ln in pins(sym):
        add(x, y)
        a = math.radians(ang)
        add(x + ln * math.cos(a), y + ln * math.sin(a))
    if not xs:
        return (-2.54, -2.54, 2.54, 2.54)
    return (min(xs), min(ys), max(xs), max(ys))
