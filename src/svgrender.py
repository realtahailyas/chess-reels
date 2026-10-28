"""Minimal SVG rasterizer built on PIL.

Exists so the pipeline renders chess pieces without a Cairo system library,
which is the single most common install failure on Windows. It handles only
the subset of SVG that python-chess emits for its piece artwork:

  * <g> / <path> / <circle> elements
  * path commands M L H V C S Q T A Z (absolute and relative)
  * transform="matrix(...) translate(...) scale(...) rotate(...)"
  * fill / stroke / stroke-width / fill-rule from attributes or inline style

Shapes are flattened to polylines, drawn supersampled, then downsampled for
antialiasing. This is not a general SVG engine and is not meant to be one.
"""

import math
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageDraw

# ── Tokenizing ────────────────────────────────────────────────────────────

_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_PATH_TOKEN = re.compile(rf"([MmZzLlHhVvCcSsQqTtAa])|({_NUM})")
_NUM_RE = re.compile(_NUM)
_TRANSFORM_RE = re.compile(rf"(\w+)\s*\(([^)]*)\)")

# Argument count per path command, used to support repeated argument groups.
_ARGC = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
         "Q": 4, "T": 2, "A": 7, "Z": 0}


def _tokenize_path(d: str):
    """Yield (command, [numbers]) groups, expanding implicit repeats."""
    tokens = []
    for cmd, num in _PATH_TOKEN.findall(d):
        tokens.append(cmd if cmd else float(num))

    out = []
    i = 0
    current = None
    while i < len(tokens):
        tok = tokens[i]
        if isinstance(tok, str):
            current = tok
            i += 1
        elif current is None:
            i += 1
            continue
        # A repeated coordinate group after M continues as an implicit lineto.
        if current in ("M", "m") and out and out[-1][0] in ("M", "m"):
            pass
        argc = _ARGC[current.upper()]
        if argc == 0:
            out.append((current, []))
            current = None if current.upper() == "Z" else current
            continue
        args = []
        while len(args) < argc and i < len(tokens) and not isinstance(tokens[i], str):
            args.append(tokens[i])
            i += 1
        if len(args) < argc:
            break
        out.append((current, args))
        # After an explicit moveto, further coordinate groups are linetos.
        if current == "M":
            current = "L"
        elif current == "m":
            current = "l"
    return out


# ── Transforms ────────────────────────────────────────────────────────────

class Matrix:
    """2D affine transform [a c e; b d f; 0 0 1]."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    def multiply(self, o: "Matrix") -> "Matrix":
        """Return self * o (o applied first, then self)."""
        return Matrix(
            self.a * o.a + self.c * o.b,
            self.b * o.a + self.d * o.b,
            self.a * o.c + self.c * o.d,
            self.b * o.c + self.d * o.d,
            self.a * o.e + self.c * o.f + self.e,
            self.b * o.e + self.d * o.f + self.f,
        )

    def apply(self, x: float, y: float):
        return (self.a * x + self.c * y + self.e,
                self.b * x + self.d * y + self.f)

    def mean_scale(self) -> float:
        """Average axis scale — used to scale stroke widths."""
        sx = math.hypot(self.a, self.b)
        sy = math.hypot(self.c, self.d)
        return (sx + sy) / 2.0


def parse_transform(text: str) -> Matrix:
    m = Matrix()
    if not text:
        return m
    for name, raw in _TRANSFORM_RE.findall(text):
        vals = [float(v) for v in _NUM_RE.findall(raw)]
        if name == "matrix" and len(vals) == 6:
            t = Matrix(*vals)
        elif name == "translate":
            t = Matrix(e=vals[0], f=vals[1] if len(vals) > 1 else 0.0)
        elif name == "scale":
            sx = vals[0]
            sy = vals[1] if len(vals) > 1 else sx
            t = Matrix(a=sx, d=sy)
        elif name == "rotate":
            ang = math.radians(vals[0])
            cos, sin = math.cos(ang), math.sin(ang)
            t = Matrix(cos, sin, -sin, cos)
            if len(vals) == 3:      # rotate about a point
                cx, cy = vals[1], vals[2]
                t = Matrix(e=cx, f=cy).multiply(t).multiply(Matrix(e=-cx, f=-cy))
        else:
            continue
        m = m.multiply(t)
    return m


# ── Curve flattening ──────────────────────────────────────────────────────

def _steps_for(p0, p3, scale: float) -> int:
    """Pick a subdivision count from the curve's rough on-screen length."""
    span = math.dist(p0, p3) * scale
    return max(6, min(48, int(span / 2.0) + 6))


def _cubic(p0, p1, p2, p3, steps):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = (u * u * u * p0[0] + 3 * u * u * t * p1[0]
             + 3 * u * t * t * p2[0] + t * t * t * p3[0])
        y = (u * u * u * p0[1] + 3 * u * u * t * p1[1]
             + 3 * u * t * t * p2[1] + t * t * t * p3[1])
        pts.append((x, y))
    return pts


def _arc(p0, rx, ry, phi_deg, large_arc, sweep, p1, scale):
    """Endpoint-parameterized elliptical arc, sampled to points (SVG F.6.5)."""
    x0, y0 = p0
    x1, y1 = p1
    if (x0, y0) == (x1, y1):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]

    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2

    # Scale radii up if they are too small to span the endpoints.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx

    cx = cos_p * cxp - sin_p * cyp + (x0 + x1) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y0 + y1) / 2.0

    def angle(ux, uy):
        return math.atan2(uy, ux)

    theta0 = angle((x1p - cxp) / rx, (y1p - cyp) / ry)
    theta1 = angle((-x1p - cxp) / rx, (-y1p - cyp) / ry)
    dtheta = theta1 - theta0
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    steps = max(6, min(64, int(abs(dtheta) * max(rx, ry) * scale / 2.0) + 6))
    pts = []
    for i in range(1, steps + 1):
        th = theta0 + dtheta * (i / steps)
        px = cx + rx * math.cos(th) * cos_p - ry * math.sin(th) * sin_p
        py = cy + rx * math.cos(th) * sin_p + ry * math.sin(th) * cos_p
        pts.append((px, py))
    return pts


def flatten_path(d: str, scale: float = 1.0):
    """Convert a path 'd' string to [(points, closed), ...] in user space."""
    subpaths = []
    pts = []
    closed = False
    start = (0.0, 0.0)
    cur = (0.0, 0.0)
    prev_cubic_ctrl = None
    prev_quad_ctrl = None

    def flush():
        nonlocal pts, closed
        if len(pts) > 1:
            subpaths.append((pts, closed))
        pts = []
        closed = False

    for cmd, a in _tokenize_path(d):
        rel = cmd.islower()
        up = cmd.upper()

        if up == "M":
            flush()
            cur = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
            start = cur
            pts = [cur]
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif up == "Z":
            if pts:
                pts.append(start)
                closed = True
                cur = start
                flush()
                pts = [cur]
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif up in ("L", "H", "V"):
            if up == "L":
                nxt = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
            elif up == "H":
                nxt = (cur[0] + a[0], cur[1]) if rel else (a[0], cur[1])
            else:
                nxt = (cur[0], cur[1] + a[0]) if rel else (cur[0], a[0])
            pts.append(nxt)
            cur = nxt
            prev_cubic_ctrl = prev_quad_ctrl = None

        elif up in ("C", "S"):
            if up == "C":
                c1 = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
                c2 = (cur[0] + a[2], cur[1] + a[3]) if rel else (a[2], a[3])
                end = (cur[0] + a[4], cur[1] + a[5]) if rel else (a[4], a[5])
            else:
                # Smooth curve: reflect the previous control point.
                c1 = (2 * cur[0] - prev_cubic_ctrl[0],
                      2 * cur[1] - prev_cubic_ctrl[1]) if prev_cubic_ctrl else cur
                c2 = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
                end = (cur[0] + a[2], cur[1] + a[3]) if rel else (a[2], a[3])
            pts.extend(_cubic(cur, c1, c2, end, _steps_for(cur, end, scale)))
            prev_cubic_ctrl = c2
            prev_quad_ctrl = None
            cur = end

        elif up in ("Q", "T"):
            if up == "Q":
                q = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
                end = (cur[0] + a[2], cur[1] + a[3]) if rel else (a[2], a[3])
            else:
                q = (2 * cur[0] - prev_quad_ctrl[0],
                     2 * cur[1] - prev_quad_ctrl[1]) if prev_quad_ctrl else cur
                end = (cur[0] + a[0], cur[1] + a[1]) if rel else (a[0], a[1])
            # Elevate the quadratic to an equivalent cubic.
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            pts.extend(_cubic(cur, c1, c2, end, _steps_for(cur, end, scale)))
            prev_quad_ctrl = q
            prev_cubic_ctrl = c2
            cur = end

        elif up == "A":
            end = (cur[0] + a[5], cur[1] + a[6]) if rel else (a[5], a[6])
            pts.extend(_arc(cur, a[0], a[1], a[2], bool(a[3]), bool(a[4]), end, scale))
            cur = end
            prev_cubic_ctrl = prev_quad_ctrl = None

    flush()
    return subpaths


# ── Styling ───────────────────────────────────────────────────────────────

_NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "none": None,
          "red": (255, 0, 0), "gray": (128, 128, 128), "grey": (128, 128, 128)}


def parse_color(text):
    if not text:
        return None
    text = text.strip().lower()
    if text in ("none", "transparent"):
        return None
    if text in _NAMED:
        return _NAMED[text]
    if text.startswith("#"):
        h = text[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if text.startswith("rgb"):
        v = [int(float(n)) for n in _NUM_RE.findall(text)[:3]]
        if len(v) == 3:
            return tuple(v)
    return None


def _style_dict(elem):
    """Merge presentation attributes with inline style (style wins)."""
    props = {}
    for key in ("fill", "stroke", "stroke-width", "fill-rule",
                "opacity", "fill-opacity", "stroke-opacity"):
        if key in elem.attrib:
            props[key] = elem.attrib[key]
    for chunk in elem.attrib.get("style", "").split(";"):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            props[k.strip()] = v.strip()
    return props


def _tag(elem):
    return elem.tag.split("}")[-1]


# ── Rasterizing ───────────────────────────────────────────────────────────

def _draw_shape(canvas, subpaths, style, matrix, scale):
    """Fill and stroke one shape onto an RGBA canvas."""
    fill = parse_color(style.get("fill"))
    stroke = parse_color(style.get("stroke"))
    evenodd = style.get("fill-rule", "").strip() == "evenodd"

    try:
        width = float(_NUM_RE.findall(style.get("stroke-width", "1"))[0])
    except (IndexError, ValueError):
        width = 1.0
    width *= matrix.mean_scale()

    device = [([matrix.apply(x, y) for x, y in pts], closed)
              for pts, closed in subpaths]

    if fill is not None:
        # Even-odd is XOR across subpaths; nonzero is approximated by union,
        # which is correct for these shapes since none self-intersect.
        mask = Image.new("L", canvas.size, 0)
        for pts, _ in device:
            if len(pts) < 3:
                continue
            layer = Image.new("L", canvas.size, 0)
            ImageDraw.Draw(layer).polygon(pts, fill=255)
            mask = ImageChops.logical_xor(
                mask.point(lambda v: 255 if v else 0).convert("1"),
                layer.convert("1"),
            ).convert("L") if evenodd else ImageChops.lighter(mask, layer)
        canvas.paste(Image.new("RGBA", canvas.size, fill + (255,)), (0, 0), mask)

    if stroke is not None and width > 0:
        draw = ImageDraw.Draw(canvas)
        col = stroke + (255,)
        w = max(1, int(round(width)))
        r = w / 2.0
        for pts, closed in device:
            if len(pts) < 2:
                continue
            line = pts + [pts[0]] if closed and pts[0] != pts[-1] else pts
            draw.line(line, fill=col, width=w, joint="curve")
            # PIL leaves gaps at vertices for thick lines; round joins/caps
            # are drawn explicitly.
            if w > 2:
                for x, y in line:
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=col)


def rasterize(svg_text: str, out_px: int, supersample: int = 2) -> Image.Image:
    """Render an SVG string to an RGBA image of out_px x out_px."""
    root = ET.fromstring(svg_text)

    vb = root.attrib.get("viewBox", "0 0 45 45").replace(",", " ").split()
    vx, vy, vw, vh = (float(v) for v in vb)

    ss = max(1, int(supersample))
    size = out_px * ss
    scale = size / max(vw, vh)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base = Matrix(a=scale, d=scale).multiply(Matrix(e=-vx, f=-vy))

    def walk(elem, matrix, inherited):
        matrix = matrix.multiply(parse_transform(elem.attrib.get("transform", "")))
        style = dict(inherited)
        style.update(_style_dict(elem))
        tag = _tag(elem)

        if tag == "path" and elem.attrib.get("d"):
            subs = flatten_path(elem.attrib["d"], matrix.mean_scale())
            _draw_shape(canvas, subs, style, matrix, scale)
        elif tag in ("circle", "ellipse"):
            cx = float(elem.attrib.get("cx", 0))
            cy = float(elem.attrib.get("cy", 0))
            if tag == "circle":
                rx = ry = float(elem.attrib.get("r", 0))
            else:
                rx = float(elem.attrib.get("rx", 0))
                ry = float(elem.attrib.get("ry", 0))
            pts = [(cx + rx * math.cos(a * math.pi / 32),
                    cy + ry * math.sin(a * math.pi / 32)) for a in range(65)]
            _draw_shape(canvas, [(pts, True)], style, matrix, scale)
        elif tag == "rect":
            x = float(elem.attrib.get("x", 0))
            y = float(elem.attrib.get("y", 0))
            w = float(elem.attrib.get("width", 0))
            h = float(elem.attrib.get("height", 0))
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            _draw_shape(canvas, [(pts, True)], style, matrix, scale)

        for child in elem:
            walk(child, matrix, style)

    walk(root, base, {})

    if ss > 1:
        canvas = canvas.resize((out_px, out_px), Image.LANCZOS)
    return canvas
