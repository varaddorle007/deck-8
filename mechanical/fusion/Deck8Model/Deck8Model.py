"""Deck-8 Rev A: parametric enclosure, light ring, knobs and reference parts for Fusion.

Run from Utilities > Scripts and Add-Ins. It opens a new design and builds:
  Top Shell, Light Ring (translucent), Bottom Tray, Knob x2, Side Buttons, OLED Lens,
  Switch Plate, plus reference bodies (PCB, keycaps, encoders, OLED module, battery,
  LED strip) for fit and interference checks.

The outline, heights, bevel, skin, ring, tray and knob dimensions are live Fusion user
parameters (Modify > Change Parameters). Feature positions on the top surface come from
the layout table below at build time; change them and re-run.

Coordinates: mm, X right, Y toward the back, Z up, body bottom at Z = 0. "Plane
coordinates" (X, Y, v) are measured on the sloped top surface: Y along the slope from the
key-grid centre, v along the surface normal (negative = into the body).
"""
import json
import math
import os
import time
import traceback

import adsk.core
import adsk.fusion

PARAMS = [
    ("case_w", "98 mm", "Body width"),
    ("case_d", "84 mm", "Body depth"),
    ("front_y", "32 mm", "Key-grid centre to the front edge"),
    ("h_front", "18 mm", "Body height at the front"),
    ("h_back", "30 mm", "Body height at the back"),
    ("skin", "2 mm", "Top shell skin and wall"),
    ("bevel", "3 mm", "45 deg bevel on the top edges"),
    ("ch_back", "10 mm", "Back corner chamfer"),
    ("ch_front", "4 mm", "Front corner chamfer"),
    ("tray_t", "1.5 mm", "Bottom tray floor"),
    ("ring_h", "4 mm", "Light ring visible band"),
    ("ring_t", "2.5 mm", "Light ring wall"),
    ("mix_gap", "4.3 mm", "LED strip face to ring inner face"),
    ("strip_t", "1.2 mm", "LED strip thickness incl. LEDs"),
    ("lwall_t", "1.5 mm", "Light wall thickness"),
    ("lwall_h", "6 mm", "Light wall height above the floor"),
    ("fit_slide", "0.2 mm", "Clearance per side, sliding fits"),
    ("fit_press", "0.1 mm", "Clearance per side, press fits"),
    ("knob_d", "20 mm", "Knob diameter"),
    ("knob_h", "16 mm", "Knob height"),
    ("knob_ch", "0.6 mm", "Knob top chamfer"),
    ("bore_d", "6.1 mm", "Knob D-bore diameter"),
    ("bore_flat", "4.55 mm", "Knob D-bore across the flat"),
    ("cbore_d", "11 mm", "Knob counterbore diameter"),
    ("cbore_h", "4.5 mm", "Knob counterbore depth"),
    ("knob_wall", "3 mm", "Knob top wall over the shaft"),
    ("knurl_n", "40", "Knob grooves"),
    ("knurl_dp", "0.5 mm", "Knob groove depth"),
]

# Layout in plane coordinates (mm), from the plan's shared-coordinate table.
KEY_X = (-28.575, -9.525, 9.525, 28.575)
KEY_Y = (9.525, -9.525)
ROW_Y = 35.0                      # knob and OLED row
KNOB_X = (-28.575, 28.575)
WELL = (80.0, 42.0)               # key well opening
WINDOW = (26.0, 14.0)             # OLED window
LENS = (28.0, 16.0, 1.0)          # lens recess w, h, depth
ENC_HOLE = 8.0
PCB_TOP_V = -9.0                  # PCB top surface below the top surface
PCB_T = 1.6
PLATE_TOP_V = -4.0
PLATE_T = 1.5
KNOB_GAP = 1.0
SHELL_BOSSES = ((-17.6, 28.0), (17.6, 28.0), (-36.0, -25.0), (36.0, -25.0))  # clear of the encoder courtyards
TRAY_BOSSES = ((-34.0, -20.0), (34.0, -20.0), (-36.0, 24.0), (36.0, 24.0))  # clear of strip, encoder pins, battery
STANDOFF_H = 3.0                  # SMD standoff on the PCB bottom
# Fasteners, all M2. Shell: heat-set inserts in the 3.2 mm boss holes, screws up through the board from below. H3/H4
# sit over the light wall and the strip with 1.05 mm under the board, so every shell screw has a thin wafer head.
SHELL_SCREW = (5.0, 4.5, 0.8)     # length, head diameter, head height: M2 x 5 wafer head
INSERT = (3.2, 3.0)               # heat-set insert outside diameter as installed, length
# Tray: pan heads (ISO 7045) up through the tilted bosses into the standoffs. The counterbore holds the tilted head
# clear of the rubber-foot seat; the screw length is picked per boss in fasteners().
TRAY_HEAD = (3.8, 1.6)            # head diameter, height
TRAY_CBORE = (5.0, 2.9)           # counterbore diameter, depth from the tray bottom
TRAY_BOSS_D = 7.0
M2_LENGTHS = (4, 5, 6, 8, 10, 12, 14, 16, 20)
BTN_V = -12.35                    # side-switch actuator axis (PCB bottom side)
L_BUTTONS = (24.0, 10.0)          # L1, L2 on the left wall
SLIDE_Y = -14.0                   # power switch, left wall
SYS_Y = 10.0                      # System button, right wall
PILL = (10.0, 4.0)
SYS_D = 8.0
BTN_PROUD = 1.2
USB = (13.0, 7.0, 3.0)            # back-wall opening w, h, corner radius
USB_AT = (45.7, -12.2)            # receptacle centre (Y, v)
PCB_OUTLINE = (46.0, -28.5, 47.5, 9.0, 3.0)   # half width, front, back, back chamfer, front chamfer
BATTERY = (40.0, 30.0, 8.0, -8.0, 27.0)  # x, y, thickness, centre x and y (world); left of centre so the plug
                                         # in J2 (board X 12-20) lies beside the cell, not on it
OLED_HEADER_Y = 23.0              # OLED module header row (J5): the module's own pins, soldered through the board
# Routed board from KiCad (hardware/tools/export_fit.py): STEP in plane coordinates, plus envelope boxes for parts
# whose 3D model the KiCad install lacks. When present they replace the simple reference PCB in the clash check.
def _repo_root():
    """The deck-8 repo: DECK8_ROOT if set, else the repo this file sits in, else ~/deck-8. (Fusion runs a copy from
    its own Scripts folder, so there put the repo path in deck8_root.txt next to the script, or set DECK8_ROOT.)"""
    env = os.environ.get("DECK8_ROOT")
    if env:
        return os.path.expanduser(env)
    here = os.path.dirname(os.path.realpath(__file__))
    pointer = os.path.join(here, "deck8_root.txt")     # one line: the path of your deck-8 folder
    if os.path.exists(pointer):
        return os.path.expanduser(open(pointer).read().strip())
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    if os.path.isdir(os.path.join(root, "hardware")) and os.path.isdir(os.path.join(root, "mechanical")):
        return root
    return os.path.expanduser("~/deck-8")


REPO = _repo_root()
HW_BUILD = os.path.join(REPO, "hardware", "build")
KICAD_STEP = os.path.join(HW_BUILD, "deck8_pcb.step")
KICAD_ENVELOPES = os.path.join(HW_BUILD, "fit_envelopes.json")

SQ2 = math.sqrt(2.0)
NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation
CUT = adsk.fusion.FeatureOperations.CutFeatureOperation
INTERSECT = adsk.fusion.FeatureOperations.IntersectFeatureOperation
DO = adsk.fusion.DimensionOrientations


def V(expr):
    return adsk.core.ValueInput.createByString(expr)


def R(mm):
    return adsk.core.ValueInput.createByReal(mm / 10.0)


def P3(t):
    return adsk.core.Point3D.create(t[0] / 10.0, t[1] / 10.0, t[2] / 10.0)


def VEC(t):
    return adsk.core.Vector3D.create(t[0], t[1], t[2])


def coll(items):
    c = adsk.core.ObjectCollection.create()
    for i in items:
        c.add(i)
    return c


def add3(a, b, k=1.0):
    return (a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2])


class Builder:
    def __init__(self, app, design, rep):
        self.app, self.design, self.rep = app, design, rep
        self.root = design.rootComponent
        self.v = {}
        self.occ = {}
        self.base_planes = {}
        self.ap_index = None
        self.mat_index = None

    # ------------------------------------------------------------------ setup
    def params(self):
        up = self.design.userParameters
        for name, expr, comment in PARAMS:
            units = "" if expr.replace(".", "", 1).isdigit() else "mm"
            up.add(name, V(expr), units, comment)
        for name, _, _ in PARAMS:
            p = up.itemByName(name)
            self.v[name] = p.value * 10.0 if p.unit == "mm" else p.value
        v = self.v
        self.W, self.D, self.F = v["case_w"], v["case_d"], v["front_y"]
        self.Db = self.D - self.F
        self.th = math.atan((v["h_back"] - v["h_front"]) / self.D)
        self.c, self.s = math.cos(self.th), math.sin(self.th)
        self.z0 = v["h_front"] + self.F * math.tan(self.th)
        self.n = (0.0, -self.s, self.c)
        self.u = (0.0, self.c, self.s)

    def S(self, X, Y, vv=0.0):
        """Plane coordinates -> model mm."""
        return (X, Y * self.c - vv * self.s, self.z0 + Y * self.s + vv * self.c)

    def warn(self, msg):
        self.rep["warnings"].append(msg)

    def new_comp(self, name, matrix=None):
        occ = self.root.occurrences.addNewComponent(matrix or adsk.core.Matrix3D.create())
        occ.component.name = name
        self.occ[name] = occ
        return occ.component

    # --------------------------------------------------------------- sketches
    def skp(self, sk, t):
        p = sk.modelToSketchSpace(P3(t))
        p.z = 0.0  # keep every curve exactly in the sketch plane so loops intersect
        return p

    def poly(self, sk, pts):
        lines = sk.sketchCurves.sketchLines
        sp = [self.skp(sk, p) for p in pts]
        out = []
        for i in range(len(sp)):
            if i == 0:
                ln = lines.addByTwoPoints(sp[0], sp[1])
            elif i < len(sp) - 1:
                ln = lines.addByTwoPoints(out[-1].endSketchPoint, sp[i + 1])
            else:
                ln = lines.addByTwoPoints(out[-1].endSketchPoint, out[0].startSketchPoint)
            out.append(ln)
        return out

    def rect(self, sk, center, u, w, vd, h, r=0.0):
        pts = [add3(add3(center, u, a * w / 2), vd, b * h / 2) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        lines = self.poly(sk, pts)
        if r > 0:
            r = min(r, w / 2 - 0.01, h / 2 - 0.01)
            arcs = sk.sketchCurves.sketchArcs
            for i in range(4):
                a, b = lines[i], lines[(i + 1) % 4]
                try:
                    arcs.addFillet(a, a.endSketchPoint.geometry, b, b.startSketchPoint.geometry, r / 10.0)
                except Exception as e:
                    self.warn(f"fillet r={r} in {sk.name}: {e}")
        return lines

    def circle(self, sk, center, d):
        return sk.sketchCurves.sketchCircles.addByCenterRadius(self.skp(sk, center), d / 20.0)

    def dim(self, sk, p1, p2, orient, expr):
        g1, g2 = p1.geometry, p2.geometry
        tp = adsk.core.Point3D.create((g1.x + g2.x) / 2 + 0.4, (g1.y + g2.y) / 2 + 0.4, 0)
        d = sk.sketchDimensions.addDistanceDimension(p1, p2, orient, tp)
        d.parameter.expression = expr
        return d

    def octagon(self, sk, inset_expr, d):
        """Body outline on an XY sketch, inset by d (mm); dimensioned with parameters."""
        v = self.v
        k = 2 - SQ2
        hw, yb, yf = self.W / 2 - d, self.Db - d, -(self.F - d)
        cb, cf = v["ch_back"] - d * k, v["ch_front"] - d * k
        # deep insets would drive a chamfer to zero or negative; hold it at 0.5 mm instead
        cb_e = f"ch_back - ({inset_expr}) * (2 - sqrt(2))" if cb >= 0.5 else "0.5 mm"
        cf_e = f"ch_front - ({inset_expr}) * (2 - sqrt(2))" if cf >= 0.5 else "0.5 mm"
        cb, cf = max(cb, 0.5), max(cf, 0.5)
        pts = [(-hw + cb, yb, 0), (hw - cb, yb, 0), (hw, yb - cb, 0), (hw, yf + cf, 0),
               (hw - cf, yf, 0), (-hw + cf, yf, 0), (-hw, yf + cf, 0), (-hw, yb - cb, 0)]
        sk.isComputeDeferred = True
        L = self.poly(sk, pts)
        e = inset_expr
        try:
            gc = sk.geometricConstraints
            gc.addHorizontal(L[0]); gc.addVertical(L[2]); gc.addHorizontal(L[4]); gc.addVertical(L[6])
            O = sk.originPoint
            self.dim(sk, O, L[0].startSketchPoint, DO.VerticalDimensionOrientation, f"case_d - front_y - ({e})")
            self.dim(sk, O, L[4].startSketchPoint, DO.VerticalDimensionOrientation, f"front_y - ({e})")
            self.dim(sk, O, L[2].startSketchPoint, DO.HorizontalDimensionOrientation, f"case_w / 2 - ({e})")
            self.dim(sk, O, L[6].startSketchPoint, DO.HorizontalDimensionOrientation, f"case_w / 2 - ({e})")
            for i, ex in ((1, cb_e), (3, cf_e), (5, cf_e), (7, cb_e)):
                self.dim(sk, L[i].startSketchPoint, L[i].endSketchPoint, DO.HorizontalDimensionOrientation, ex)
                self.dim(sk, L[i].startSketchPoint, L[i].endSketchPoint, DO.VerticalDimensionOrientation, ex)
        except Exception as ex:
            self.warn(f"octagon dims ({sk.name}, inset {e}): {ex}")
        sk.isComputeDeferred = False
        return L

    def ring_profile(self, sk):
        for p in sk.profiles:
            if p.profileLoops.count == 2:
                return p
        raise RuntimeError(f"no ring profile in {sk.name}")

    # ----------------------------------------------------------------- planes
    def tilted_plane(self, comp, vv, name):
        """Construction plane parallel to the top surface at plane coordinate v."""
        key = comp.name
        if key not in self.base_planes:
            found = None
            for ang in (self.th, -self.th):
                pin = comp.constructionPlanes.createInput()
                pin.setByAngle(comp.xConstructionAxis, adsk.core.ValueInput.createByReal(ang), comp.xYConstructionPlane)
                pl = comp.constructionPlanes.add(pin)
                nn = pl.geometry.normal
                d = nn.x * self.n[0] + nn.y * self.n[1] + nn.z * self.n[2]
                if abs(abs(d) - 1) < 1e-6:
                    found = (pl, 1 if d > 0 else -1)
                    break
                pl.deleteMe()
            if not found:
                raise RuntimeError("could not build the slope plane")
            found[0].name = "Slope base"
            found[0].isLightBulbOn = False
            self.base_planes[key] = found
        base, sign = self.base_planes[key]
        dist = self.c * self.z0 + vv
        target = self.S(0, 0, vv)
        for sgn in (sign, -sign):
            pin = comp.constructionPlanes.createInput()
            pin.setByOffset(base, R(sgn * dist))
            pl = comp.constructionPlanes.add(pin)
            o = pl.geometry.origin
            err = sum(((o.x, o.y, o.z)[i] * 10 - target[i]) * self.n[i] for i in range(3))
            if abs(err) < 1e-3:
                pl.name = name
                pl.isLightBulbOn = False
                return pl
            pl.deleteMe()
        raise RuntimeError(f"plane {name} misplaced")

    def offset_plane(self, comp, base, expr, axis, expect, name):
        """Offset plane checked against the expected world coordinate on one axis."""
        for e in (expr, f"-({expr})"):
            pin = comp.constructionPlanes.createInput()
            pin.setByOffset(base, V(e))
            pl = comp.constructionPlanes.add(pin)
            o = pl.geometry.origin
            if abs((o.x, o.y, o.z)[axis] * 10 - expect) < 1e-3:
                pl.name = name
                pl.isLightBulbOn = False
                return pl
            pl.deleteMe()
        raise RuntimeError(f"plane {name} misplaced")

    # --------------------------------------------------------------- features
    def extrude(self, comp, profiles, op, dist=None, world_dir=None, to_entity=None, symmetric=None,
                start_offset=None, taper=None, participants=None, name=None):
        feats = comp.features.extrudeFeatures
        profs = profiles if isinstance(profiles, adsk.core.ObjectCollection) else coll(
            profiles if isinstance(profiles, (list, tuple)) else [profiles])
        inp = feats.createInput(profs, op)
        if symmetric is not None:
            inp.setSymmetricExtent(V(symmetric) if isinstance(symmetric, str) else R(symmetric), False)
        else:
            direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
            if world_dir is not None:
                sk = profs.item(0).parentSketch
                nrm = sk.xDirection.crossProduct(sk.yDirection)
                if nrm.dotProduct(VEC(world_dir)) < 0:
                    direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
            if to_entity is not None:
                ext = adsk.fusion.ToEntityExtentDefinition.create(to_entity, False)
            else:
                ext = adsk.fusion.DistanceExtentDefinition.create(V(dist) if isinstance(dist, str) else R(dist))
            if taper is not None:
                inp.setOneSideExtent(ext, direction, V(taper))
            else:
                inp.setOneSideExtent(ext, direction)
        if start_offset is not None:
            inp.startExtent = adsk.fusion.OffsetStartDefinition.create(V(start_offset))
        if participants:
            inp.participantBodies = participants
        f = feats.add(inp)
        if name:
            f.name = name
        return f

    def planar_faces(self, body):
        out = []
        for f in body.faces:
            if f.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
                continue
            ok, nrm = f.evaluator.getNormalAtPoint(f.pointOnFace)
            out.append((f, nrm))
        return out

    # ------------------------------------------------------------ top shell
    def top_shell(self):
        comp = self.new_comp("Top Shell")
        v = self.v
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Outline"
        self.octagon(sk, "0 mm", 0.0)
        f = self.extrude(comp, sk.profiles.item(0), NEW, dist="h_back", world_dir=(0, 0, 1),
                         start_offset="tray_t + ring_h", name="Envelope")
        body = f.bodies.item(0)
        body.name = "Top Shell"

        sk2 = comp.sketches.add(comp.yZConstructionPlane)
        sk2.name = "Side profile"
        A, B = (0, -self.F, 0), (0, self.Db, 0)
        C, D = (0, self.Db, v["h_back"]), (0, -self.F, v["h_front"])
        L = self.poly(sk2, [A, B, C, D])
        try:
            gc = sk2.geometricConstraints
            a, b = L[0].startSketchPoint.geometry, L[0].endSketchPoint.geometry
            if abs(a.y - b.y) < 1e-9:
                gc.addHorizontal(L[0])
            else:
                gc.addVertical(L[0])
            gc.addPerpendicular(L[0], L[1])
            gc.addPerpendicular(L[0], L[3])
            gc.addCoincident(sk2.originPoint, L[0])
            AL = DO.AlignedDimensionOrientation
            self.dim(sk2, sk2.originPoint, L[0].startSketchPoint, AL, "front_y")
            self.dim(sk2, L[0].startSketchPoint, L[0].endSketchPoint, AL, "case_d")
            self.dim(sk2, L[1].startSketchPoint, L[1].endSketchPoint, AL, "h_back")
            self.dim(sk2, L[3].endSketchPoint, L[3].startSketchPoint, AL, "h_front")
        except Exception as ex:
            self.warn(f"side profile dims: {ex}")
        self.extrude(comp, sk2.profiles.item(0), INTERSECT, symmetric="case_w / 2 + 2 mm",
                     participants=[comp.bRepBodies.item(0)], name="Wedge")
        body = comp.bRepBodies.item(0)

        tops = [(f, n) for f, n in self.planar_faces(body) if n.z > 0.5 and n.y < -0.02]
        top = max(tops, key=lambda t: t[0].area)[0]
        ch = comp.features.chamferFeatures
        cin = ch.createInput2()
        cin.chamferEdgeSets.addEqualDistanceChamferEdgeSet(coll(list(top.edges)), V("bevel"), False)
        ch.add(cin).name = "Top bevel"

        body = comp.bRepBodies.item(0)
        bottoms = [(f, n) for f, n in self.planar_faces(body) if n.z < -0.99]
        bottom = max(bottoms, key=lambda t: t[0].area)[0]
        sh = comp.features.shellFeatures
        sin = sh.createInput(coll([bottom]), False)
        sin.insideThickness = V("skin")
        sh.add(sin).name = "Shell"
        body = comp.bRepBodies.item(0)
        skin = v["skin"]

        pl_top = self.tilted_plane(comp, 0.0, "Top surface")
        pl_under = self.tilted_plane(comp, -skin, "Skin underside")
        pl_lens = self.tilted_plane(comp, -(skin - LENS[2]), "Lens seat")
        pl_below = self.tilted_plane(comp, -(skin + 1.0), "Below skin")
        pl_pcb = self.tilted_plane(comp, PCB_TOP_V, "PCB top")
        pl_ins = self.tilted_plane(comp, PCB_TOP_V + 4.0, "Insert depth")
        X3, U, N = (1.0, 0.0, 0.0), self.u, self.n

        sk = comp.sketches.add(pl_top)
        sk.name = "Top openings"
        self.rect(sk, self.S(0, 0), X3, WELL[0], U, WELL[1], 1.5)
        self.rect(sk, self.S(0, ROW_Y), X3, WINDOW[0], U, WINDOW[1], 1.0)
        for x in KNOB_X:
            self.circle(sk, self.S(x, ROW_Y), ENC_HOLE)
        self.extrude(comp, list(sk.profiles), CUT, symmetric="skin + 1 mm", participants=[comp.bRepBodies.item(0)], name="Top openings")

        sk = comp.sketches.add(pl_lens)
        sk.name = "Lens recess"
        self.rect(sk, self.S(0, ROW_Y, -(skin - LENS[2])), X3, LENS[0], U, LENS[1], 1.0)
        self.extrude(comp, list(sk.profiles), CUT, to_entity=pl_below, world_dir=tuple(-x for x in N),
                     participants=[comp.bRepBodies.item(0)], name="Lens recess")

        # bosses start 0.5 mm inside the skin so they fuse with it instead of only touching
        pl_boss = self.tilted_plane(comp, -(skin - 0.5), "Boss start")
        sk = comp.sketches.add(pl_boss)
        sk.name = "Shell bosses"
        for x, y in SHELL_BOSSES:
            self.circle(sk, self.S(x, y, -(skin - 0.5)), 5.0)
        self.extrude(comp, list(sk.profiles), JOIN, to_entity=pl_pcb, world_dir=tuple(-x for x in N),
                     participants=[comp.bRepBodies.item(0)], name="Shell bosses")

        sk = comp.sketches.add(pl_pcb)
        sk.name = "Insert holes"
        for x, y in SHELL_BOSSES:
            self.circle(sk, self.S(x, y, PCB_TOP_V), 3.2)
        self.extrude(comp, list(sk.profiles), CUT, to_entity=pl_ins, world_dir=N,
                     participants=[comp.bRepBodies.item(0)], name="M2 insert holes")

        def btn_center(xw, Y):
            p = self.S(xw, Y, BTN_V)
            return (xw, p[1], p[2])

        pl_left = self.offset_plane(comp, comp.yZConstructionPlane, "case_w / 2", 0, -self.W / 2, "Left wall")
        pl_right = self.offset_plane(comp, comp.yZConstructionPlane, "case_w / 2", 0, self.W / 2, "Right wall")
        pl_back = self.offset_plane(comp, comp.xZConstructionPlane, "case_d - front_y", 1, self.Db, "Back wall")
        fs = v["fit_slide"]
        sk = comp.sketches.add(pl_left)
        sk.name = "Left wall openings"
        for Y in L_BUTTONS:
            self.rect(sk, btn_center(-self.W / 2, Y), U, PILL[0] + 2 * fs, N, PILL[1] + 2 * fs, PILL[1] / 2 + fs)
        self.rect(sk, btn_center(-self.W / 2, SLIDE_Y), U, 6.0 + 2 * fs, N, 3.0 + 2 * fs, 0.5)
        self.extrude(comp, list(sk.profiles), CUT, symmetric="skin + 1 mm", participants=[comp.bRepBodies.item(0)], name="Left openings")
        sk = comp.sketches.add(pl_right)
        sk.name = "Right wall opening"
        self.circle(sk, btn_center(self.W / 2, SYS_Y), SYS_D + 2 * fs)
        self.extrude(comp, list(sk.profiles), CUT, symmetric="skin + 1 mm", participants=[comp.bRepBodies.item(0)], name="System opening")
        usb = self.S(0, USB_AT[0], USB_AT[1])
        sk = comp.sketches.add(pl_back)
        sk.name = "USB-C opening"
        self.rect(sk, (0.0, self.Db, usb[2]), X3, USB[0], (0.0, 0.0, 1.0), USB[1], USB[2])
        self.extrude(comp, list(sk.profiles), CUT, symmetric="skin + 1 mm", participants=[comp.bRepBodies.item(0)], name="USB-C opening")
        self.shell_body = body

    # ------------------------------------------------------------- light ring
    def light_ring(self):
        comp = self.new_comp("Light Ring")
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Ring outline"
        self.octagon(sk, "0 mm", 0.0)
        self.octagon(sk, "ring_t", self.v["ring_t"])
        f = self.extrude(comp, self.ring_profile(sk), NEW, dist="ring_h", world_dir=(0, 0, 1),
                         start_offset="tray_t", name="Ring")
        f.bodies.item(0).name = "Light Ring"

    # ------------------------------------------------------------ bottom tray
    def bottom_tray(self):
        comp = self.new_comp("Bottom Tray")
        v = self.v
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Floor"
        self.octagon(sk, "0 mm", 0.0)
        body = self.extrude(comp, sk.profiles.item(0), NEW, dist="tray_t", world_dir=(0, 0, 1), name="Floor").bodies.item(0)
        body.name = "Bottom Tray"
        loops = [
            ("Ring locator", "ring_t + fit_press", v["ring_t"] + v["fit_press"], 1.2, "1 mm"),
            ("Light wall", "ring_t + mix_gap + strip_t", v["ring_t"] + v["mix_gap"] + v["strip_t"], v["lwall_t"], "lwall_h"),
        ]
        for name, e, d, wdt, h in loops:
            sk = comp.sketches.add(comp.xYConstructionPlane)
            sk.name = name
            self.octagon(sk, e, d)
            e2 = "lwall_t" if name == "Light wall" else "1.2 mm"
            self.octagon(sk, f"{e} + {e2}", d + wdt)
            self.extrude(comp, self.ring_profile(sk), JOIN, dist=h, world_dir=(0, 0, 1), start_offset="tray_t",
                         participants=[comp.bRepBodies.item(0)], name=name)
        bx, by, bt, bcx, bcy = BATTERY
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Battery fence"
        lines = sk.sketchCurves.sketchLines
        for e in (1.25, 0.25):
            lines.addTwoPointRectangle(P3((bcx - bx / 2 - e, bcy - by / 2 - e, 0)), P3((bcx + bx / 2 + e, bcy + by / 2 + e, 0)))
        self.extrude(comp, self.ring_profile(sk), JOIN, dist="1.5 mm", world_dir=(0, 0, 1), start_offset="tray_t",
                     participants=[comp.bRepBodies.item(0)], name="Battery fence")

        seat_v = PCB_TOP_V - PCB_T - STANDOFF_H
        pl_seat = self.tilted_plane(comp, seat_v, "Standoff seat")
        pl_floor = self.offset_plane(comp, comp.xYConstructionPlane, "tray_t", 2, v["tray_t"], "Floor top")
        down = tuple(-x for x in self.n)
        sk = comp.sketches.add(pl_seat)
        sk.name = "Tray bosses"
        for x, y in TRAY_BOSSES:
            self.circle(sk, self.S(x, y, seat_v), TRAY_BOSS_D)
        self.extrude(comp, list(sk.profiles), JOIN, to_entity=pl_floor, world_dir=down, participants=[comp.bRepBodies.item(0)], name="Tray bosses")
        sk = comp.sketches.add(pl_seat)
        sk.name = "Screw holes"
        for x, y in TRAY_BOSSES:
            self.circle(sk, self.S(x, y, seat_v), 2.4)
        self.extrude(comp, list(sk.profiles), CUT, dist="30 mm", world_dir=down, participants=[comp.bRepBodies.item(0)], name="Screw holes")
        exits = []
        for x, y in TRAY_BOSSES:
            p = self.S(x, y, seat_v)
            t = p[2] / self.c
            exits.append((x, p[1] + t * self.s, 0.0))
        for name, d, depth in (("Screw counterbores", TRAY_CBORE[0], f"{TRAY_CBORE[1]} mm"), ("Feet recesses", 8.4, "0.6 mm")):
            sk = comp.sketches.add(comp.xYConstructionPlane)
            sk.name = name
            for e in exits:
                self.circle(sk, e, d)
            self.extrude(comp, list(sk.profiles), CUT, dist=depth, world_dir=(0, 0, 1), participants=[comp.bRepBodies.item(0)], name=name)
        self.tray_screw_exits = exits
        # Where a shell screw head comes down over the light wall (H3/H4), drop the wall to the strip's top edge so the
        # head clears it by more than print tolerance; the strip stays fully backed.
        strip_top = v["tray_t"] + 0.5 + 5.0
        wall_top = v["tray_t"] + v["lwall_h"]
        notches = []
        for x, y in SHELL_BOSSES:
            hc = self.S(x, y, PCB_TOP_V - PCB_T - SHELL_SCREW[2])
            if hc[2] - SHELL_SCREW[1] / 2 * self.s - 1.0 < wall_top:
                notches.append((hc[0], hc[1], 0.0))
        if notches:
            sk = comp.sketches.add(comp.xYConstructionPlane)
            sk.name = "Screw head notches"
            for c in notches:
                self.circle(sk, c, SHELL_SCREW[1] + 1.5)
            self.extrude(comp, list(sk.profiles), CUT, dist=f"{wall_top - strip_top + 1.0} mm", world_dir=(0, 0, 1),
                         start_offset=f"{strip_top} mm", participants=[comp.bRepBodies.item(0)], name="Screw head notches")
        self.rep["wall_notches"] = len(notches)

    # ------------------------------------------------------------------ knobs
    def knob_matrix(self, x):
        o = add3(self.S(x, ROW_Y), self.n, KNOB_GAP)
        m = adsk.core.Matrix3D.create()
        m.setWithCoordinateSystem(P3(o), VEC((1, 0, 0)), VEC(self.u), VEC(self.n))
        return m

    def knobs(self):
        comp = self.new_comp("Knob", self.knob_matrix(KNOB_X[0]))
        v = self.v
        Rk, H, ch = v["knob_d"] / 2, v["knob_h"], v["knob_ch"]
        rb, rc, hc, wall = v["bore_d"] / 2, v["cbore_d"] / 2, v["cbore_h"], v["knob_wall"]
        sk = comp.sketches.add(comp.xZConstructionPlane)
        sk.name = "Knob section"
        self.poly(sk, [(0, 0, H), (Rk - ch, 0, H), (Rk, 0, H - ch), (Rk, 0, 0), (rc, 0, 0), (rc, 0, hc),
                       (rb, 0, hc), (rb, 0, H - wall), (0, 0, H - wall)])
        rv = comp.features.revolveFeatures
        rin = rv.createInput(sk.profiles.item(0), comp.zConstructionAxis, NEW)
        rin.setAngleExtent(False, V("360 deg"))
        body = rv.add(rin).bodies.item(0)
        body.name = "Knob"
        flat_x = v["bore_flat"] - rb
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "D flat"
        sk.sketchCurves.sketchLines.addTwoPointRectangle(P3((flat_x, -rb - 0.3, 0)), P3((rb + 0.3, rb + 0.3, 0)))
        self.extrude(comp, sk.profiles.item(0), JOIN, dist="knob_h - knob_wall - cbore_h", world_dir=(0, 0, 1),
                     start_offset="cbore_h", participants=[comp.bRepBodies.item(0)], name="D flat")
        dp = v["knurl_dp"]
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Groove"
        self.poly(sk, [(Rk - dp, 0, 0), (Rk + 0.3, 0.45, 0), (Rk + 0.3, -0.45, 0)])
        g = self.extrude(comp, sk.profiles.item(0), CUT, dist="knob_h", world_dir=(0, 0, 1), participants=[comp.bRepBodies.item(0)], name="Groove")
        cp = comp.features.circularPatternFeatures
        pin = cp.createInput(coll([g]), comp.zConstructionAxis)
        pin.quantity = V("knurl_n")
        pin.totalAngle = V("360 deg")
        pin.isSymmetric = False
        pin.patternComputeOption = adsk.fusion.PatternComputeOptions.IdenticalPatternCompute
        cp.add(pin).name = "Knurl"
        occ_b = self.root.occurrences.addExistingComponent(comp, self.knob_matrix(KNOB_X[1]))
        self.occ["Knob B"] = occ_b

    # --------------------------------------------------------- side buttons
    def buttons(self):
        comp = self.new_comp("Side Buttons")
        v = self.v
        xin = self.W / 2 - v["skin"]
        pl_l = self.offset_plane(comp, comp.yZConstructionPlane, "case_w / 2 - skin", 0, -xin, "Left wall inside")
        pl_r = self.offset_plane(comp, comp.yZConstructionPlane, "case_w / 2 - skin", 0, xin, "Right wall inside")
        U, N = self.u, self.n

        def center(xw, Y):
            p = self.S(xw, Y, BTN_V)
            return (xw, p[1], p[2])

        caps = [("L1", pl_l, -1, L_BUTTONS[0]), ("L2", pl_l, -1, L_BUTTONS[1]), ("System", pl_r, 1, SYS_Y)]
        for name, pl, side, Y in caps:
            c = center(side * xin, Y)
            sk = comp.sketches.add(pl)
            sk.name = f"{name} head"
            if name == "System":
                self.circle(sk, c, SYS_D)
            else:
                self.rect(sk, c, U, PILL[0], N, PILL[1], PILL[1] / 2)
            btn = self.extrude(comp, list(sk.profiles), NEW, dist="skin + 1.2 mm", world_dir=(side, 0, 0),
                               name=f"{name} head").bodies.item(0)
            btn.name = f"Button {name}"
            sk = comp.sketches.add(pl)
            sk.name = f"{name} flange"
            if name == "System":
                self.circle(sk, c, SYS_D + 2.0)
            else:
                self.rect(sk, c, U, PILL[0] + 2.0, N, PILL[1] + 2.0, PILL[1] / 2 + 1.0)
            self.extrude(comp, list(sk.profiles), JOIN, dist="0.8 mm", world_dir=(-side, 0, 0),
                         participants=[btn], name=f"{name} flange")

    # ------------------------------------------------------------------ lens
    def lens(self):
        comp = self.new_comp("OLED Lens")
        seat = -(self.v["skin"] - LENS[2])
        pl = self.tilted_plane(comp, seat, "Lens seat")
        sk = comp.sketches.add(pl)
        sk.name = "Lens"
        self.rect(sk, self.S(0, ROW_Y, seat), (1, 0, 0), LENS[0] - 0.2, self.u, LENS[1] - 0.2, 0.9)
        b = self.extrude(comp, sk.profiles.item(0), NEW, dist=0.95, world_dir=tuple(-x for x in self.n), name="Lens").bodies.item(0)
        b.name = "OLED Lens"

    # --------------------------------------------------------- switch plate
    def plate(self):
        comp = self.new_comp("Switch Plate")
        pl = self.tilted_plane(comp, PLATE_TOP_V, "Plate top")
        sk = comp.sketches.add(pl)
        sk.name = "Plate"
        X3, U = (1, 0, 0), self.u
        self.rect(sk, self.S(0, -1.5, PLATE_TOP_V), X3, 84.0, U, 41.0)
        for y in KEY_Y:
            for x in KEY_X:
                self.rect(sk, self.S(x, y, PLATE_TOP_V), X3, 14.0, U, 14.0)
        prof = max(sk.profiles, key=lambda p: p.profileLoops.count)
        b = self.extrude(comp, prof, NEW, dist=PLATE_T, world_dir=tuple(-x for x in self.n), name="Plate").bodies.item(0)
        b.name = "Switch Plate"

    # ------------------------------------------------------- reference parts
    def reference_parts(self):
        X3, U, N = (1, 0, 0), self.u, self.n
        down = tuple(-x for x in N)

        comp = self.new_comp("PCB (ref)")
        pl = self.tilted_plane(comp, PCB_TOP_V, "PCB top")
        sk = comp.sketches.add(pl)
        sk.name = "PCB outline"
        hw, yf, yb, cb, cf = PCB_OUTLINE
        pts = [(-hw + cb, yb), (hw - cb, yb), (hw, yb - cb), (hw, yf + cf), (hw - cf, yf), (-hw + cf, yf), (-hw, yf + cf), (-hw, yb - cb)]
        self.poly(sk, [self.S(x, y, PCB_TOP_V) for x, y in pts])
        self.extrude(comp, sk.profiles.item(0), NEW, dist=PCB_T, world_dir=down, name="PCB").bodies.item(0).name = "PCB"
        sk = comp.sketches.add(pl)
        sk.name = "PCB mounting holes"
        for x, y in SHELL_BOSSES:
            self.circle(sk, self.S(x, y, PCB_TOP_V), 2.2)
        self.extrude(comp, list(sk.profiles), CUT, dist=PCB_T + 0.5, world_dir=down,
                     participants=[comp.bRepBodies.item(0)], name="PCB mounting holes")

        comp = self.new_comp("Keycaps (ref)")
        pl = self.tilted_plane(comp, 2.5, "Keycap base")
        sk = comp.sketches.add(pl)
        sk.name = "Keycaps"
        for y in KEY_Y:
            for x in KEY_X:
                self.rect(sk, self.S(x, y, 2.5), X3, 18.0, U, 18.0, 1.0)
        taper = math.degrees(math.atan(2.5 / 9.5))
        f = self.extrude(comp, list(sk.profiles), NEW, dist=9.5, world_dir=N, taper=f"-{taper:.3f} deg", name="Keycaps")
        if f.bodies.item(0).volume * 1000 > 18 * 18 * 9.5:
            f.deleteMe()
            f = self.extrude(comp, list(sk.profiles), NEW, dist=9.5, world_dir=N, taper=f"{taper:.3f} deg", name="Keycaps")
        self.keycap_cols = {1: [], 2: [], 3: [], 4: []}
        for b in f.bodies:
            com = b.physicalProperties.centerOfMass
            col = min(range(4), key=lambda i: abs(KEY_X[i] - com.x * 10))
            row = "back" if com.y * 10 > 0 else "front"
            b.name = f"Keycap {row} {col + 1}"
            self.keycap_cols[col + 1].append(b)

        comp = self.new_comp("Encoders (ref)")
        pl0 = self.tilted_plane(comp, PCB_TOP_V, "Encoder seat")
        sk = comp.sketches.add(pl0)
        sk.name = "Encoder bodies"
        for x in KNOB_X:
            self.rect(sk, self.S(x, ROW_Y, PCB_TOP_V), X3, 12.0, U, 12.5)
        bodies = list(self.extrude(comp, list(sk.profiles), NEW, dist=6.5, world_dir=N, name="Encoder bodies").bodies)
        pl1 = self.tilted_plane(comp, PCB_TOP_V + 6.5, "Bushing base")
        sk = comp.sketches.add(pl1)
        sk.name = "Bushings"
        for x in KNOB_X:
            self.circle(sk, self.S(x, ROW_Y, PCB_TOP_V + 6.5), 7.0)
        self.extrude(comp, list(sk.profiles), JOIN, dist=5.0, world_dir=N, participants=list(comp.bRepBodies), name="Bushings")
        pl2 = self.tilted_plane(comp, PCB_TOP_V + 11.5, "Shaft base")
        sk = comp.sketches.add(pl2)
        sk.name = "Shafts"
        for x in KNOB_X:
            self.circle(sk, self.S(x, ROW_Y, PCB_TOP_V + 11.5), 6.0)
        # shaft tip sits 20 mm above the PCB top
        self.extrude(comp, list(sk.profiles), JOIN, dist=20.0 - 11.5, world_dir=N, participants=list(comp.bRepBodies), name="Shafts")
        sk = comp.sketches.add(pl2)
        sk.name = "Shaft flats"
        for x in KNOB_X:
            c = self.S(x, ROW_Y, PCB_TOP_V + 11.5)
            self.rect(sk, add3(c, X3, 1.5 + 1.25), X3, 2.5, U, 7.0)
        self.extrude(comp, list(sk.profiles), CUT, dist=20.0 - 11.5, world_dir=N, participants=list(comp.bRepBodies), name="Shaft flats")
        for i, b in enumerate(comp.bRepBodies):
            b.name = f"Encoder {'AB'[i] if i < 2 else i}"

        # The shell holds the module: its glass rests on the skin underside past both ends of the lens pocket, and
        # its own header (plastic under the board, long pins down) goes through J5, soldered from below once the
        # board is screwed in. A socket would stand the glass 11 mm off the board; there are 7 mm.
        comp = self.new_comp("OLED Module (ref)")
        v_glass = -self.v["skin"] - 1.3
        v_board = v_glass - 1.0
        pl = self.tilted_plane(comp, v_board, "Module board")
        sk = comp.sketches.add(pl)
        sk.name = "Module board"
        self.rect(sk, self.S(0, ROW_Y, v_board), X3, 27.3, U, 27.8)
        board = self.extrude(comp, sk.profiles.item(0), NEW, dist=1.0, world_dir=N, name="Module board").bodies.item(0)
        board.name = "OLED board"
        sk = comp.sketches.add(pl)
        sk.name = "Header plastic"
        self.rect(sk, self.S(0, OLED_HEADER_Y, v_board), X3, 10.16, U, 2.54)
        self.extrude(comp, sk.profiles.item(0), JOIN, dist=2.5, world_dir=down, participants=[board], name="Header plastic")
        # 0.64 mm square pins: clipped to 1 mm above the module board, 6 mm below the plastic
        pl_tip = self.tilted_plane(comp, v_board + 2.0, "Header pin tips")
        sk = comp.sketches.add(pl_tip)
        sk.name = "Header pins"
        for i in range(4):
            self.rect(sk, self.S(-3.81 + 2.54 * i, OLED_HEADER_Y, v_board + 2.0), X3, 0.64, U, 0.64)
        self.extrude(comp, list(sk.profiles), JOIN, dist=2.0 + 2.5 + 6.0, world_dir=down, participants=[board], name="Header pins")
        pl = self.tilted_plane(comp, v_glass, "Glass base")
        sk = comp.sketches.add(pl)
        sk.name = "Glass"
        self.rect(sk, self.S(0, ROW_Y, v_glass), X3, 26.7, U, 19.3)
        self.extrude(comp, sk.profiles.item(0), NEW, dist=1.3, world_dir=N, name="Glass").bodies.item(0).name = "OLED glass"

        comp = self.new_comp("Battery (ref)")
        bx, by, bt, bcx, bcy = BATTERY
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Battery"
        sk.sketchCurves.sketchLines.addTwoPointRectangle(P3((bcx - bx / 2, bcy - by / 2, 0)), P3((bcx + bx / 2, bcy + by / 2, 0)))
        self.extrude(comp, sk.profiles.item(0), NEW, dist=bt, world_dir=(0, 0, 1), start_offset="tray_t + 0.5 mm",
                     name="Battery").bodies.item(0).name = "LiPo 1000 mAh"

        comp = self.new_comp("LED Strip (ref)")
        sk = comp.sketches.add(comp.xYConstructionPlane)
        sk.name = "Strip"
        v = self.v
        self.octagon(sk, "ring_t + mix_gap", v["ring_t"] + v["mix_gap"])
        self.octagon(sk, "ring_t + mix_gap + strip_t", v["ring_t"] + v["mix_gap"] + v["strip_t"])
        self.extrude(comp, self.ring_profile(sk), NEW, dist="5 mm", world_dir=(0, 0, 1), start_offset="tray_t + 0.5 mm",
                     name="Strip").bodies.item(0).name = "LED Strip"

    # ------------------------------------------------------------- fasteners
    def fasteners(self):
        """Reference screws and inserts, so the clash check covers them, and the screw list for the build."""
        comp = self.new_comp("Fasteners (ref)")
        N, X3, U = self.n, (1, 0, 0), self.u
        down = tuple(-x for x in N)
        bodies, parts = [], []
        v_bot = PCB_TOP_V - PCB_T
        L, hd, hk = SHELL_SCREW
        for i, (x, y) in enumerate(SHELL_BOSSES):
            pl = self.tilted_plane(comp, v_bot, "Board bottom") if i == 0 else pl
            sk = comp.sketches.add(pl)
            sk.name = f"H{i + 1} screw"
            self.circle(sk, self.S(x, y, v_bot), hd)
            head = self.extrude(comp, sk.profiles.item(0), NEW, dist=hk, world_dir=down, name=f"H{i + 1} head").bodies.item(0)
            sk = comp.sketches.add(pl)
            self.circle(sk, self.S(x, y, v_bot), 1.6)      # thread minor diameter
            self.extrude(comp, sk.profiles.item(0), JOIN, dist=L, world_dir=N, participants=[head], name=f"H{i + 1} shank")
            head.name = f"H{i + 1} M2x{L:g} wafer head"
            pl_ins = self.tilted_plane(comp, PCB_TOP_V, "Boss face") if i == 0 else pl_ins
            sk = comp.sketches.add(pl_ins)
            sk.name = f"H{i + 1} insert"
            self.circle(sk, self.S(x, y, PCB_TOP_V), INSERT[0])
            self.circle(sk, self.S(x, y, PCB_TOP_V), 2.0)
            ring = [p for p in sk.profiles if p.profileLoops.count == 2]
            self.extrude(comp, ring[0], NEW, dist=INSERT[1], world_dir=N, name=f"H{i + 1} insert").bodies.item(0).name = f"H{i + 1} insert"
            parts.append({"where": f"H{i + 1} shell boss", "part": f"M2 x {L:g} wafer head (head {hd} x {hk} mm) + M2 x {INSERT[1]:g} heat-set insert"})
        seat_v = PCB_TOP_V - PCB_T - STANDOFF_H
        r, k = TRAY_HEAD[0] / 2, TRAY_HEAD[1]
        for i, (x, y) in enumerate(TRAY_BOSSES):
            p = self.S(x, y, seat_v)
            # head top centre on the screw axis, low enough that its tilted rim just meets the counterbore floor
            z_c = TRAY_CBORE[1] - r * self.s
            clamp = (p[2] - z_c) / self.c
            length = next(n for n in M2_LENGTHS if n - clamp >= 1.8)
            v_head = seat_v - clamp
            pl = self.tilted_plane(comp, v_head, f"ST{i + 1} head")
            sk = comp.sketches.add(pl)
            sk.name = f"ST{i + 1} screw"
            self.circle(sk, self.S(x, y, v_head), TRAY_HEAD[0])
            head = self.extrude(comp, sk.profiles.item(0), NEW, dist=k, world_dir=down, name=f"ST{i + 1} head").bodies.item(0)
            sk = comp.sketches.add(pl)
            self.circle(sk, self.S(x, y, v_head), 1.6)
            self.extrude(comp, sk.profiles.item(0), JOIN, dist=length, world_dir=N, participants=[head], name=f"ST{i + 1} shank")
            head.name = f"ST{i + 1} M2x{length} pan head"
            low = z_c - k * self.c - r * self.s
            parts.append({"where": f"ST{i + 1} tray boss", "part": f"M2 x {length} pan head", "clamp_mm": round(clamp, 2),
                          "into_standoff_mm": round(length - clamp, 2), "head_low_point_z_mm": round(low, 2)})
        self.rep["fasteners"] = parts

    # ------------------------------------------------------- routed KiCad board
    def kicad_pcb(self):
        """Import the routed board, put its top face on the PCB plane, add envelopes for parts with no model, and
        drop the simple reference PCB so the clash check sees the real board."""
        if not os.path.exists(KICAD_STEP):
            self.warn(f"no KiCad STEP at {KICAD_STEP}: clash check uses the reference PCB")
            return
        im = self.app.importManager
        # 1. import once as is, to find the board body and its top face height in the STEP
        probe = self.new_comp("KiCad probe")
        im.importToTarget(im.createSTEPImportOptions(KICAD_STEP), probe)
        board, area = None, 0.0
        for occ in self.all_under(self.occ["KiCad probe"]):
            for b in occ.bRepBodies:
                bb = b.boundingBox
                a = (bb.maxPoint.x - bb.minPoint.x) * (bb.maxPoint.y - bb.minPoint.y)
                if a > area:
                    board, area = b, a
        bb = board.boundingBox
        # the top face itself, not the box: boxes are only guaranteed to enclose
        z_top = max(o[2] for o in self.flat_faces(board, (0.0, 0.0, 1.0)))
        step_box = [round(bb.minPoint.x * 10, 2), round(bb.minPoint.y * 10, 2), round(bb.maxPoint.x * 10, 2),
                    round(bb.maxPoint.y * 10, 2), round(bb.minPoint.z * 10, 2), round(z_top, 4)]
        self.occ.pop("KiCad probe").deleteMe()
        # 2. import again into a component whose transform maps STEP (X, Y, z) to S(X, Y, PCB_TOP_V + z - z_top)
        c, s = self.c, self.s
        dv = PCB_TOP_V - z_top
        m = adsk.core.Matrix3D.create()
        m.setWithArray([1, 0, 0, 0,
                        0, c, -s, -s * dv / 10.0,
                        0, s, c, (self.z0 + c * dv) / 10.0,
                        0, 0, 0, 1])
        comp = self.new_comp("PCB (KiCad)", m)
        im.importToTarget(im.createSTEPImportOptions(KICAD_STEP), comp)
        bodies = [b for occ in self.all_under(self.occ["PCB (KiCad)"]) for b in occ.bRepBodies]
        # 3. the board must land where the reference PCB is: compare the two boxes in world coordinates
        ref = self.bodies_of("PCB (ref)")
        placed = max(bodies, key=lambda b: (b.boundingBox.maxPoint.x - b.boundingBox.minPoint.x) *
                     (b.boundingBox.maxPoint.y - b.boundingBox.minPoint.y))
        def box(b):
            q = b.boundingBox
            return [round(v * 10, 2) for v in (q.minPoint.x, q.minPoint.y, q.minPoint.z, q.maxPoint.x, q.maxPoint.y, q.maxPoint.z)]
        o0 = self.S(0, 0, 0)
        vs = sorted(sum((p[i] - o0[i]) * self.n[i] for i in range(3)) for p in self.flat_faces(placed, self.n))
        fit = {"step_board_box_mm": step_box, "placed_board_world_mm": box(placed), "bodies": len(bodies),
               "board_faces_v_mm": [round(vs[0], 4), round(vs[-1], 4)], "board_top_target_v_mm": PCB_TOP_V}
        if abs(vs[-1] - PCB_TOP_V) > 1e-3:
            self.warn(f"KiCad board top at v = {vs[-1]:.4f} mm, not {PCB_TOP_V}")
        if ref:
            fit["reference_pcb_world_mm"] = box(ref[0])
        # 4. envelopes for the parts KiCad has no model for
        env = json.load(open(KICAD_ENVELOPES))["envelopes"] if os.path.exists(KICAD_ENVELOPES) else []
        if env:
            ecomp = self.new_comp("KiCad envelopes")
            down = tuple(-x for x in self.n)
            for e in env:
                v0 = PCB_TOP_V - PCB_T if e["side"] == "B" else PCB_TOP_V
                pl = self.tilted_plane(ecomp, v0, f"{e['ref']} base")
                sk = ecomp.sketches.add(pl)
                sk.name = e["ref"]
                x0, y0, x1, y1 = e["rect"]
                self.rect(sk, self.S((x0 + x1) / 2, (y0 + y1) / 2, v0), (1, 0, 0), x1 - x0, self.u, y1 - y0)
                f = self.extrude(ecomp, sk.profiles.item(0), NEW, dist=e["height"],
                                 world_dir=down if e["side"] == "B" else self.n, name=f"{e['name']} envelope")
                f.bodies.item(0).name = e["name"]
        fit["envelopes"] = {k: sum(1 for e in env if e["kind"] == k) for k in ("body", "plug")}
        self.rep["kicad_fit"] = fit
        if "PCB (ref)" in self.occ:
            self.occ.pop("PCB (ref)").deleteMe()

    def flat_faces(self, body, normal):
        """Points (mm) on the planar faces of a body that face along or against a direction."""
        out = []
        for f in body.faces:
            g = adsk.core.Plane.cast(f.geometry)
            if g and abs(abs(g.normal.x * normal[0] + g.normal.y * normal[1] + g.normal.z * normal[2]) - 1) < 1e-9:
                out.append((g.origin.x * 10, g.origin.y * 10, g.origin.z * 10))
        return out

    def all_under(self, occ):
        out, todo = [], [occ]
        while todo:
            o = todo.pop()
            out.append(o)
            todo.extend(o.childOccurrences)
        return out

    # ------------------------------------------------------ looks and checks
    def _index(self, kind):
        libs = self.app.materialLibraries
        out = []
        for i in range(libs.count):
            lib = libs.item(i)
            if kind == "appearance" and "appearance" in lib.name.lower():
                items = lib.appearances
            elif kind == "material" and "material" in lib.name.lower() and "appearance" not in lib.name.lower():
                items = lib.materials
            else:
                continue
            for j in range(items.count):
                it = items.item(j)
                out.append((it.name.lower(), it))
        return out

    def find(self, kind, options):
        idx = self.ap_index if kind == "appearance" else self.mat_index
        for kws in options:
            if len(kws) == 1:
                for name, it in idx:
                    if name == kws[0]:
                        return it
        for kws in options:
            for name, it in idx:
                if all(k in name for k in kws):
                    return it
        return None

    def look(self, bodies, label, options, rgb=None):
        base = self.find("appearance", options)
        if base is None:
            self.warn(f"no appearance for {label}")
            return None
        name = f"Deck8 {label}"
        ap = self.design.appearances.itemByName(name)
        if ap is None:
            ap = self.design.appearances.addByCopy(base, name)
            if rgb:
                for k in range(ap.appearanceProperties.count):
                    prop = adsk.core.ColorProperty.cast(ap.appearanceProperties.item(k))
                    if prop and prop.value is not None and "color" in prop.name.lower():
                        try:
                            prop.value = adsk.core.Color.create(rgb[0], rgb[1], rgb[2], 255)
                        except Exception:
                            pass
        for b in bodies:
            b.appearance = ap
        self.rep["appearances"][label] = base.name
        return ap

    def material(self, bodies, label, options):
        m = self.find("material", options)
        if m is None:
            self.warn(f"no material for {label}")
            return
        for b in bodies:
            b.material = m
        self.rep["materials"][label] = m.name

    def bodies_of(self, name):
        occ = self.occ.get(name)
        return list(occ.component.bRepBodies) if occ else []

    def finish_looks(self):
        self.ap_index = self._index("appearance")
        self.mat_index = self._index("material")
        self.rep["library_sizes"] = {"appearances": len(self.ap_index), "materials": len(self.mat_index)}
        A, M = self.look, self.material
        M(self.bodies_of("Top Shell"), "shell", [["aluminum 6063"], ["aluminum 6061"], ["aluminum", "6063"], ["aluminum", "6061"]])
        A(self.bodies_of("Top Shell"), "shell", [["aluminum - anodized rough (grey)"], ["anodized", "rough", "grey"], ["aluminum - satin"]], None)
        M(self.bodies_of("Light Ring"), "ring", [["polycarbonate, clear"], ["polycarbonate"], ["acrylic, clear"], ["acrylic"]])
        A(self.bodies_of("Light Ring"), "ring", [["plastic - translucent matte (white)"], ["translucent", "matte"], ["glass - frosted"]], (236, 228, 255))
        M(self.bodies_of("Bottom Tray"), "tray", [["abs plastic"], ["abs"], ["petg"], ["plastic"]])
        A(self.bodies_of("Bottom Tray"), "tray", [["plastic - matte (black)"], ["plastic", "matte"]], None)
        M(self.bodies_of("Knob"), "knob", [["aluminum 6061"], ["aluminum"]])
        A(self.bodies_of("Knob"), "knob", [["aluminum - anodized rough (grey)"], ["anodized", "rough"]], (30, 31, 35))
        A(self.bodies_of("Side Buttons"), "buttons", [["aluminum - anodized glossy (grey)"], ["anodized", "glossy"]], (88, 91, 98))
        A(self.bodies_of("OLED Lens"), "lens", [["plastic - translucent glossy (gray)"], ["translucent", "glossy"], ["glass (grey)"]], (24, 24, 28))
        A(self.bodies_of("Switch Plate"), "plate", [["plastic", "matte"], ["plastic"]], (18, 18, 20))
        A(self.bodies_of("PCB (ref)"), "pcb", [["plastic", "glossy"], ["plastic"]], (16, 30, 22))
        A(self.bodies_of("Encoders (ref)"), "encoders", [["steel", "satin"], ["steel"], ["aluminum"]], None)
        A([b for b in self.bodies_of("OLED Module (ref)") if "glass" in b.name.lower()], "oled glass", [["plastic", "glossy"], ["glass"]], (8, 8, 10))
        A([b for b in self.bodies_of("OLED Module (ref)") if "board" in b.name.lower()], "oled board", [["plastic", "matte"], ["plastic"]], (20, 40, 110))
        A(self.bodies_of("Battery (ref)"), "battery", [["plastic", "glossy"], ["plastic"]], (196, 168, 86))
        A(self.bodies_of("LED Strip (ref)"), "strip", [["emissive"], ["led"], ["neon"], ["plastic", "glossy"]], (150, 110, 255))
        colors = {1: (168, 142, 255), 2: (92, 203, 227), 3: (241, 196, 83), 4: (243, 156, 85)}
        for col, rgb in colors.items():
            A(getattr(self, "keycap_cols", {}).get(col, []), f"keycap {col}",
              [["plastic - translucent matte (white)"], ["translucent", "matte"], ["plastic"]], rgb)
        for oi in range(self.root.allOccurrences.count):
            for sk in self.root.allOccurrences.item(oi).component.sketches:
                sk.isLightBulbOn = False
        self.rep["appearance_names"] = sorted({n for n, _ in self.ap_index})
        self.rep["material_names"] = sorted({n for n, _ in self.mat_index})

    def measure(self):
        out = {}
        for oi in range(self.root.allOccurrences.count):
            occ = self.root.allOccurrences.item(oi)
            for b in occ.bRepBodies:
                bb = b.boundingBox
                out[f"{occ.name} / {b.name}"] = {
                    "volume_mm3": round(b.volume * 1000, 2),
                    "solid": b.isSolid,
                    "bbox_mm": [[round(bb.minPoint.x * 10, 2), round(bb.minPoint.y * 10, 2), round(bb.minPoint.z * 10, 2)],
                                [round(bb.maxPoint.x * 10, 2), round(bb.maxPoint.y * 10, 2), round(bb.maxPoint.z * 10, 2)]],
                }
        self.rep["bodies"] = out
        ours = {o.name for name, o in self.occ.items() if "KiCad" not in name}   # imported KiCad bodies are named Body1..
        loose = [k for k in out if k.split(" / ")[0] in ours and k.split(" / ")[1].startswith("Body")]
        if loose:
            self.warn(f"loose bodies (a join did not fuse): {loose}")
        v = self.v

        def oct_area(d):
            k = 2 - SQ2
            w, dd = self.W - 2 * d, self.D - 2 * d
            cb, cf = v["ch_back"] - d * k, v["ch_front"] - d * k
            return w * dd - cb * cb - cf * cf

        self.rep["expected"] = {
            "light_ring_mm3": round((oct_area(0) - oct_area(v["ring_t"])) * v["ring_h"], 2),
            "tilt_deg": round(math.degrees(self.th), 3),
        }

    def interference(self):
        bodies = []
        for oi in range(self.root.allOccurrences.count):
            for b in self.root.allOccurrences.item(oi).bRepBodies:
                bodies.append(b)
        inp = self.design.createInterferenceInput(coll(bodies))
        inp.areCoincidentFacesIncluded = False
        res = self.design.analyzeInterference(inp)
        # The results hold native bodies, so a body's place in the assembly comes from its component: anything
        # under the KiCad import or the envelopes is board side, and is named by the occurrence holding the hit.
        board_side = {}
        for top in ("PCB (KiCad)", "KiCad envelopes"):
            if top in self.occ:
                for o in self.all_under(self.occ[top]):
                    board_side.setdefault(o.component.id, []).append(o)
        def label(body, c):
            occs = board_side.get(body.parentComponent.id)
            if occs is None:
                return f"{body.parentComponent.name} / {body.name}", False
            for o in occs:
                # the copy of this body inside that occurrence, in world coordinates
                q = body.createForAssemblyContext(o).boundingBox
                if all(q.minPoint.asArray()[i] - 1e-4 <= c[i] <= q.maxPoint.asArray()[i] + 1e-4 for i in range(3)):
                    # "PCB (KiCad):1+deck8_pcb 1:1+J4:1+JST_SH_...:1" -> "J4 / JST_SH_... / Body1"
                    path = [n.rsplit(":", 1)[0] for n in o.fullPathName.split("+")]
                    return " / ".join(path[2:] if path[0] == "PCB (KiCad)" else path) + f" / {body.name}", True
            return f"KiCad {body.parentComponent.name} / {body.name}", True

        hits, contacts = [], []
        for i in range(res.count):
            r = res.item(i)
            ib = r.interferenceBody
            vol = ib.volume * 1000 if ib else 0.0
            if vol <= 0.05:
                continue
            bb = ib.boundingBox
            c = [(bb.minPoint.asArray()[j] + bb.maxPoint.asArray()[j]) / 2 for j in range(3)]
            (na, ka), (nb, kb) = label(r.entityOne, c), label(r.entityTwo, c)
            # mean thickness of the overlap: a slab of area F and thickness t has volume F t and area about 2 F
            t = 2 * ib.volume / ib.area * 10
            h = {"a": na, "b": nb, "board_side": ka + kb, "volume_mm3": round(vol, 2), "thickness_mm": round(t, 3),
                 "bbox_mm": [[round(v * 10, 2) for v in bb.minPoint.asArray()], [round(v * 10, 2) for v in bb.maxPoint.asArray()]]}
            # faces meant to touch (a boss on the board, a part seated on it) overlap by tessellation-level amounts
            (contacts if t < 0.05 else hits).append(h)
        self.rep["interference"] = hits
        self.rep["contacts"] = contacts
        # board against enclosure is what the fit check is for; overlaps inside KiCad's own models are listed apart
        self.rep["interference_board_vs_enclosure"] = [h for h in hits if h["board_side"] == 1]
        self.rep["interference_within_board"] = [h for h in hits if h["board_side"] == 2]

    def export(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        em = self.design.exportManager
        files = {}
        step = os.path.join(out_dir, "deck8_assembly.step")
        em.execute(em.createSTEPExportOptions(step, self.root))
        files["step"] = step
        f3d = os.path.join(out_dir, "deck8_assembly.f3d")
        em.execute(em.createFusionArchiveExportOptions(f3d))
        files["f3d"] = f3d
        stl_dir = os.path.join(out_dir, "stl")
        os.makedirs(stl_dir, exist_ok=True)
        for name in ("Top Shell", "Light Ring", "Bottom Tray", "OLED Lens", "Switch Plate"):
            for b in self.bodies_of(name):
                p = os.path.join(stl_dir, b.name.replace(" ", "_") + ".stl")
                o = em.createSTLExportOptions(b, p)
                o.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
                em.execute(o)
                files[b.name] = p
        knob = self.occ["Knob"].component
        p = os.path.join(stl_dir, "Knob.stl")
        o = em.createSTLExportOptions(knob.bRepBodies.item(0), p)
        o.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        em.execute(o)
        files["Knob"] = p
        for b in self.bodies_of("Side Buttons"):
            p = os.path.join(stl_dir, b.name.replace(" ", "_") + ".stl")
            em.execute(em.createSTLExportOptions(b, p))
            files[b.name] = p
        self.rep["files"] = files

    def images(self, out_dir):
        vp = self.app.activeViewport
        shots = {}

        def shot(name, eye, target, up):
            cam = vp.camera
            cam.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
            cam.eye = P3(eye)
            cam.target = P3(target)
            cam.upVector = VEC(up)
            cam.isSmoothTransition = False
            vp.camera = cam
            vp.fit()
            adsk.doEvents()
            p = os.path.join(out_dir, f"view_{name}.png")
            vp.saveAsImageFile(p, 1600, 1000)
            shots[name] = p

        vp.visualStyle = adsk.core.VisualStyles.ShadedVisualStyle
        tgt = (0, 10, 14)
        shot("hero", (-230, -300, 220), tgt, (0, 0, 1))
        shot("front_right", (260, -280, 160), tgt, (0, 0, 1))
        shot("top", (0, 10, 420), tgt, (0, 1, 0))
        shot("side", (-420, 10, 16), (0, 10, 16), (0, 0, 1))
        shot("back", (120, 380, 120), tgt, (0, 0, 1))
        hide = ["Top Shell", "OLED Lens", "Knob", "Knob B", "Keycaps (ref)", "Switch Plate"]
        for h in hide:
            if h in self.occ:
                self.occ[h].isLightBulbOn = False
        shot("inside", (-230, -300, 220), tgt, (0, 0, 1))
        # the KiCad envelopes stay, so the tray view shows J2 and its plug beside the cell
        hide2 = ["PCB (ref)", "PCB (KiCad)", "Encoders (ref)", "OLED Module (ref)"]
        for h in hide2:
            if h in self.occ:
                self.occ[h].isLightBulbOn = False
        shot("tray", (-200, -260, 260), (0, 10, 4), (0, 0, 1))
        hide += hide2
        for h in hide:
            if h in self.occ:
                self.occ[h].isLightBulbOn = True
        vp.fit()
        self.rep["images"] = shots


def close_previous(app):
    for i in range(app.documents.count - 1, -1, -1):
        doc = app.documents.item(i)
        try:
            des = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
            if des and des.attributes.itemByName("deck8", "build") and not doc.isSaved:
                doc.close(False)
        except Exception:
            pass


def build(export_dir=None, images=True, exports=True):
    t0 = time.time()
    rep = {"errors": [], "warnings": [], "steps": [], "appearances": {}, "materials": {}, "debug": {}}
    app = adsk.core.Application.get()
    close_previous(app)
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    design.attributes.add("deck8", "build", time.strftime("%Y-%m-%d %H:%M:%S"))
    rep["design_intent"] = str(getattr(design, "designIntent", "n/a"))
    b = Builder(app, design, rep)
    b.params()
    rep["parameters"] = dict(b.v)
    steps = [("top_shell", b.top_shell), ("light_ring", b.light_ring), ("bottom_tray", b.bottom_tray),
             ("knobs", b.knobs), ("buttons", b.buttons), ("lens", b.lens), ("plate", b.plate),
             ("reference_parts", b.reference_parts), ("fasteners", b.fasteners), ("kicad_pcb", b.kicad_pcb), ("looks", b.finish_looks),
             ("measure", b.measure),
             ("interference", b.interference)]
    if export_dir and exports:
        steps.append(("export", lambda: b.export(export_dir)))
    if export_dir and images:
        steps.append(("images", lambda: b.images(export_dir)))
    for name, fn in steps:
        ts = time.time()
        try:
            fn()
            rep["steps"].append([name, round(time.time() - ts, 2)])
        except Exception:
            rep["errors"].append({"step": name, "trace": traceback.format_exc()})
    tl = design.timeline
    rep["timeline"] = {"count": tl.count, "errored": [tl.item(i).name for i in range(tl.count)
                                                       if tl.item(i).healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState]}
    rep["seconds"] = round(time.time() - t0, 2)
    if export_dir:
        with open(os.path.join(export_dir, "build_report.json"), "w") as f:
            json.dump(rep, f, indent=1, default=str)
    return rep


PROJECT_EXPORTS = os.path.join(REPO, "mechanical", "exports")


def run(context):
    app = adsk.core.Application.get()
    out = PROJECT_EXPORTS if os.path.isdir(PROJECT_EXPORTS) else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "exports")
    try:
        rep = build(out)
        msg = (f"Deck-8 built in {rep['seconds']} s. Errors: {len(rep['errors'])}. "
               f"Interference: {len(rep.get('interference', []))} "
               f"({len(rep.get('interference_board_vs_enclosure', []))} board vs enclosure), "
               f"{len(rep.get('contacts', []))} seated contacts.\nReport: {out}")
        app.userInterface.messageBox(msg)
    except Exception:
        app.userInterface.messageBox(traceback.format_exc())
