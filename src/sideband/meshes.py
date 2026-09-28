"""Low-poly 3D models and the math to place them. Pure: no Tk.

Model space: x right, y up, z forward (the nose points to +z). A `Mesh` is vertices plus faces;
each face lists vertex indices counter-clockwise when seen from outside, and a base colour. The
renderer rotates, projects, culls back faces, and shades each face from its normal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec = tuple[float, float, float]
RGB = tuple[int, int, int]


@dataclass
class Mesh:
    vertices: list[Vec] = field(default_factory=list)
    faces: list[tuple[tuple[int, ...], RGB]] = field(default_factory=list)

    def add(self, points: list[Vec]) -> list[int]:
        start = len(self.vertices)
        self.vertices.extend(points)
        return list(range(start, start + len(points)))

    def face(self, indices: list[int], colour: RGB) -> None:
        self.faces.append((tuple(indices), colour))

    def merge(self, other: Mesh) -> Mesh:
        offset = len(self.vertices)
        self.vertices.extend(other.vertices)
        self.faces.extend((tuple(i + offset for i in idx), colour) for idx, colour in other.faces)
        return self


# --- vector math -------------------------------------------------------------------------------


def sub(a: Vec, b: Vec) -> Vec:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(v: Vec) -> Vec:
    n = math.sqrt(dot(v, v)) or 1.0
    return v[0] / n, v[1] / n, v[2] / n


def rotation(yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0) -> tuple[Vec, Vec, Vec]:
    """Rows of a rotation matrix: roll about z (nose), then pitch about x, then yaw about y.
    Positive roll banks right wing down, positive pitch raises the nose, positive yaw turns right."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # R = Ry(yaw) · Rx(-pitch) · Rz(-roll), written out
    rz = ((cr, sr, 0.0), (-sr, cr, 0.0), (0.0, 0.0, 1.0))
    rx = ((1.0, 0.0, 0.0), (0.0, cp, sp), (0.0, -sp, cp))
    ry = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))

    def mul(a: tuple[Vec, Vec, Vec], b: tuple[Vec, Vec, Vec]) -> tuple[Vec, Vec, Vec]:
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]

    return mul(ry, mul(rx, rz))


def apply(matrix: tuple[Vec, Vec, Vec], v: Vec) -> Vec:
    return dot(matrix[0], v), dot(matrix[1], v), dot(matrix[2], v)


def face_normal(points: list[Vec]) -> Vec:
    """Newell's method: robust for any planar-ish polygon, points counter-clockwise from outside."""
    nx = ny = nz = 0.0
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return unit((nx, ny, nz))


# --- building blocks ---------------------------------------------------------------------------


def loft(mesh: Mesh, stations: list[tuple[float, float, float, float]], sides: int, colour: RGB,
         nose: RGB | None = None, tail: RGB | None = None) -> None:
    """A tube through cross-sections (z, radius_x, radius_y, y_offset), front to back, capped at both ends."""
    rings = []
    for z, rx, ry, dy in stations:
        ring = [(rx * math.sin(2 * math.pi * k / sides), dy + ry * math.cos(2 * math.pi * k / sides), z) for k in range(sides)]
        rings.append(mesh.add(ring))
    for front, back in zip(rings, rings[1:]):
        for k in range(sides):
            a, b = front[k], front[(k + 1) % sides]
            c, d = back[(k + 1) % sides], back[k]
            mesh.face([a, b, c, d], colour)
    tip = mesh.add([(0.0, stations[0][3], stations[0][0] + 0.25 * max(stations[0][1], 0.2))])[0]
    for k in range(sides):
        mesh.face([rings[0][(k + 1) % sides], rings[0][k], tip], nose or colour)
    end = mesh.add([(0.0, stations[-1][3], stations[-1][0] - 0.2)])[0]
    for k in range(sides):
        mesh.face([rings[-1][k], rings[-1][(k + 1) % sides], end], tail or colour)


def slab(mesh: Mesh, outline: list[tuple[float, float, float]], thickness: float, top: RGB, bottom: RGB) -> None:
    """A thin flat plate from an outline (x, y, z) given counter-clockwise seen from above."""
    half = thickness / 2
    upper = mesh.add([(x, y + half, z) for x, y, z in outline])
    lower = mesh.add([(x, y - half, z) for x, y, z in outline])
    mesh.face(upper, top)
    mesh.face(list(reversed(lower)), bottom)
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        mesh.face([upper[j], upper[i], lower[i], lower[j]], bottom)


def fin(mesh: Mesh, outline: list[tuple[float, float]], x: float, thickness: float, colour: RGB) -> None:
    """A thin vertical plate from an outline (y, z) given counter-clockwise seen from the right."""
    half = thickness / 2
    right = mesh.add([(x + half, y, z) for y, z in outline])
    left = mesh.add([(x - half, y, z) for y, z in outline])
    mesh.face(right, colour)
    mesh.face(list(reversed(left)), colour)
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        mesh.face([right[i], right[j], left[j], left[i]], colour)


def disc(mesh: Mesh, centre: Vec, radius: float, colour: RGB, sides: int = 8, up: bool = True) -> None:
    """A flat disc facing up (or down), for roundels and markings."""
    cx, cy, cz = centre
    points = [(cx + radius * math.cos(2 * math.pi * k / sides), cy, cz + radius * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    idx = mesh.add(points)
    mesh.face(list(reversed(idx)) if up else idx, colour)


# --- aircraft ----------------------------------------------------------------------------------

SPITFIRE = {"body": (104, 112, 72), "belly": (168, 180, 170), "wing": (96, 104, 66), "nose": (70, 72, 60)}
ENEMY = {"body": (122, 128, 136), "belly": (170, 182, 196), "wing": (112, 118, 126), "nose": (226, 190, 40)}
BOMBER = {"body": (92, 98, 70), "belly": (150, 156, 150), "wing": (86, 92, 64), "nose": (120, 150, 170)}
GLASS = (150, 200, 230)
ROUNDEL = ((22, 44, 120), (235, 235, 235), (170, 30, 30))


def fighter(scheme: dict[str, RGB] = SPITFIRE, roundels: bool = True) -> Mesh:
    """A single-engine WWII fighter, about 9 units long and 11 wide."""
    m = Mesh()
    loft(m, [(4.2, 0.38, 0.40, 0.05), (3.3, 0.68, 0.72, 0.0), (1.0, 0.64, 0.74, 0.05), (-1.8, 0.46, 0.55, 0.1), (-4.4, 0.14, 0.22, 0.35)],
         6, scheme["body"], nose=scheme["nose"], tail=scheme["body"])
    # elliptical-ish wing with dihedral: right, then left
    for side in (1, -1):
        outline = [(0.5, -0.25, 1.9), (3.2, -0.05, 1.5), (5.4, 0.15, 0.6), (5.2, 0.15, -0.2), (3.0, -0.05, -0.7), (0.5, -0.25, -1.0)]
        if side < 0:
            outline = [(-x, y, z) for x, y, z in reversed(outline)]
        slab(m, outline, 0.14, scheme["wing"], scheme["belly"])
        if roundels:
            for r, colour in zip((0.55, 0.36, 0.18), ROUNDEL):
                disc(m, (side * 3.6, 0.02 + 0.006 * (0.55 - r) * 10, 0.4), r, colour)
    for side in (1, -1):  # tailplane
        outline = [(0.1, 0.35, -3.3), (1.9, 0.4, -3.7), (1.8, 0.4, -4.2), (0.1, 0.35, -4.3)]
        if side < 0:
            outline = [(-x, y, z) for x, y, z in reversed(outline)]
        slab(m, outline, 0.08, scheme["wing"], scheme["belly"])
    fin(m, [(0.4, -3.1), (1.7, -3.8), (1.8, -4.3), (0.4, -4.4)], 0.0, 0.08, scheme["body"])
    canopy = m.add([(-0.32, 0.72, 1.3), (0.32, 0.72, 1.3), (0.28, 0.72, -0.4), (-0.28, 0.72, -0.4), (0.0, 1.12, 0.5)])
    a, b, c, d, top = canopy
    for face in ([b, a, top], [c, b, top], [d, c, top], [a, d, top]):
        m.face(face, GLASS)
    return m


def bomber(scheme: dict[str, RGB] = BOMBER) -> Mesh:
    """A four-engine heavy bomber, about 20 units long and 30 wide."""
    m = Mesh()
    loft(m, [(9.5, 0.9, 0.9, 0.2), (7.5, 1.35, 1.4, 0.1), (0.0, 1.45, 1.5, 0.0), (-6.0, 1.0, 1.1, 0.3), (-10.0, 0.35, 0.5, 0.8)],
         6, scheme["body"], nose=scheme["nose"], tail=scheme["body"])
    for side in (1, -1):
        outline = [(1.2, 0.0, 3.2), (9.0, 0.35, 2.4), (15.0, 0.6, 1.2), (15.0, 0.6, -0.4), (9.0, 0.35, -0.9), (1.2, 0.0, -1.5)]
        if side < 0:
            outline = [(-x, y, z) for x, y, z in reversed(outline)]
        slab(m, outline, 0.3, scheme["wing"], scheme["belly"])
        for x in (4.2, 8.2):  # engine nacelles
            nacelle = Mesh()
            loft(nacelle, [(4.6, 0.35, 0.4, 0.0), (3.8, 0.55, 0.6, 0.0), (0.5, 0.5, 0.55, 0.0), (-1.2, 0.2, 0.25, 0.0)], 6,
                 scheme["body"], nose=(60, 60, 60))
            nacelle.vertices = [(vx + side * x, vy - 0.05 + 0.03 * x, vz) for vx, vy, vz in nacelle.vertices]
            m.merge(nacelle)
    for side in (1, -1):
        outline = [(0.2, 0.8, -7.8), (5.2, 0.9, -8.8), (5.0, 0.9, -10.0), (0.2, 0.8, -10.2)]
        if side < 0:
            outline = [(-x, y, z) for x, y, z in reversed(outline)]
        slab(m, outline, 0.15, scheme["wing"], scheme["belly"])
    fin(m, [(1.0, -7.0), (4.6, -9.0), (4.8, -10.4), (0.9, -10.4)], 0.0, 0.15, scheme["body"])
    return m


def propeller(angle: float, radius: float = 1.5, blades: int = 3, colour: RGB = (40, 40, 40), z: float = 4.3) -> Mesh:
    """Blades at `angle` radians, in the plane just ahead of the nose."""
    m = Mesh()
    for k in range(blades):
        a = angle + 2 * math.pi * k / blades
        ux, uy = math.cos(a), math.sin(a)
        px, py = -uy * 0.12, ux * 0.12
        idx = m.add([(px, py, z), (ux * radius + px * 0.6, uy * radius + py * 0.6, z),
                     (ux * radius - px * 0.6, uy * radius - py * 0.6, z), (-px, -py, z)])
        m.face(idx, colour)
        m.face(list(reversed(idx)), colour)
    return m
