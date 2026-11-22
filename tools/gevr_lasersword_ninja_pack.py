#!/usr/bin/env python3
"""
Build the downloadable Lasersword & Ninja asset pack (lasersword_ninja.bin) for GoldenEye VR.

Writes binary format GEVRLN1\\0 containing:
  1. Seven original copyright-safe 3D meshes (single hilt, double hilt, silver katana,
     gold katana, ninja buckler shield, shuriken, crescent wing) with baked vertex shading.
  2. Twelve 22050 Hz mono 16-bit PCM SFX clips (4 seamless loops + 8 one-shot events).

Pure Python 3 standard library only (no external packages required).
"""

import argparse
import math
import os
import struct
import wave
import zipfile

MAGIC = b"GEVRLN1\x00"
SAMPLE_RATE = 22050
MAX_TRIS_PER_MESH = 1024

MESH_NAMES = (
    "hilt_single",
    "hilt_double",
    "katana_silver",
    "katana_gold",
    "shield",
    "shuriken",
    "wing",
)

CLIP_NAMES = (
    "hum",
    "force_rumble",
    "lightning",
    "spin",
    "ignite",
    "slash_lasersword",
    "slash_steel",
    "deflect",
    "clash_lasersword",
    "clash_metal",
    "force_push",
    "shadow_step",
)

LIGHT_DIR = (0.42, 0.72, 0.55)
RIM_DIR = (-0.50, -0.25, -0.83)


def _norm3(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-8:
        return (0.0, 1.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _clamp_u8(x):
    return max(0, min(255, int(round(x))))


def _shade(p, n, base_rgb, ao=1.0):
    ld = _norm3(LIGHT_DIR)
    rd = _norm3(RIM_DIR)
    ndotl = max(0.0, _dot(n, ld))
    spec = max(0.0, _dot(n, rd))
    mul = (0.34 + 0.56 * ndotl + 0.16 * (spec * spec)) * ao
    mul *= max(0.84, min(1.08, 0.96 + p[1] * 0.002))
    return (
        _clamp_u8(base_rgb[0] * mul),
        _clamp_u8(base_rgb[1] * mul),
        _clamp_u8(base_rgb[2] * mul),
        255,
    )


def _add_tri(tris, p0, p1, p2, base_rgb, ao=1.0, n0=None, n1=None, n2=None):
    fn = _norm3(_cross(_sub(p1, p0), _sub(p2, p0)))
    v0 = (p0, _shade(p0, n0 or fn, base_rgb, ao))
    v1 = (p1, _shade(p1, n1 or fn, base_rgb, ao))
    v2 = (p2, _shade(p2, n2 or fn, base_rgb, ao))
    tris.append((v0, v1, v2))


def _add_quad(tris, p0, p1, p2, p3, base_rgb, ao=1.0):
    _add_tri(tris, p0, p1, p2, base_rgb, ao)
    _add_tri(tris, p0, p2, p3, base_rgb, ao)


def _add_frustum_ring(tris, segs, y0, r0_fn, y1, r1_fn, rgb_fn, ao=1.0):
    pts0, pts1, n0, n1 = [], [], [], []
    dy = y1 - y0
    for i in range(segs):
        a = (2.0 * math.pi * i) / segs
        ca, sa = math.cos(a), math.sin(a)
        ra = r0_fn(i, a)
        rb = r1_fn(i, a)
        pts0.append((ca * ra, y0, sa * ra))
        pts1.append((ca * rb, y1, sa * rb))
        dr = ra - rb
        nv = _norm3((ca * abs(dy), dr if abs(dy) > 1e-4 else 0.0, sa * abs(dy)))
        if dy == 0.0:
            nv = (0.0, 1.0 if rb >= ra else -1.0, 0.0)
        n0.append(nv)
        n1.append(nv)
    for i in range(segs):
        j = (i + 1) % segs
        col = rgb_fn(i)
        _add_tri(tris, pts0[i], pts1[i], pts1[j], col, ao, n0[i], n1[i], n1[j])
        _add_tri(tris, pts0[i], pts1[j], pts0[j], col, ao, n0[i], n1[j], n0[j])


def _add_cap(tris, segs, y, r_fn, up, col, ao=1.0):
    c = (0.0, y, 0.0)
    n = (0.0, 1.0 if up else -1.0, 0.0)
    ring = []
    for i in range(segs):
        a = (2.0 * math.pi * i) / segs
        r = r_fn(i, a)
        ring.append((math.cos(a) * r, y, math.sin(a) * r))
    for i in range(segs):
        j = (i + 1) % segs
        if up:
            _add_tri(tris, c, ring[j], ring[i], col, ao, n, n, n)
        else:
            _add_tri(tris, c, ring[i], ring[j], col, ao, n, n, n)


def _add_box(tris, cx, cy, cz, hx, hy, hz, col, ao=1.0):
    x0, x1 = cx - hx, cx + hx
    y0, y1 = cy - hy, cy + hy
    z0, z1 = cz - hz, cz + hz
    v = [
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
    ]
    faces = [
        (0, 1, 2, 3),
        (5, 4, 7, 6),
        (4, 0, 3, 7),
        (1, 5, 6, 2),
        (3, 2, 6, 7),
        (4, 5, 1, 0),
    ]
    for a, b, c, d in faces:
        _add_quad(tris, v[a], v[b], v[c], v[d], col, ao)


def build_hilt_single():
    """Original machined single energy-sword hilt (+Y blade axis, emitter at +13.5 cm)."""
    tris = []
    segs = 12
    steel_hi = (195, 202, 212)
    steel_mid = (145, 152, 164)
    steel_dk = (92, 98, 108)
    grip_blk = (42, 46, 54)
    grip_rib = (68, 74, 84)
    accent_teal = (62, 185, 205)
    core_glow = (170, 232, 255)

    _add_cap(tris, segs, -10.6, lambda i, a: 1.50, False, steel_dk, 0.85)
    _add_frustum_ring(tris, segs, -10.6, lambda i, a: 1.50, -9.8, lambda i, a: 1.85, lambda i: steel_mid, 0.92)
    _add_frustum_ring(tris, segs, -9.8, lambda i, a: 1.85, -8.5, lambda i, a: 1.85,
                      lambda i: steel_hi if i % 2 == 0 else steel_dk, 0.95)
    _add_frustum_ring(tris, segs, -8.5, lambda i, a: 1.85, -8.2, lambda i, a: 1.62, lambda i: steel_dk, 0.80)

    rib = lambda i, a: 1.64 if i % 2 == 0 else 1.46
    _add_frustum_ring(tris, segs, -8.2, rib, 3.8, rib, lambda i: grip_rib if i % 2 == 0 else grip_blk, 0.94)

    _add_frustum_ring(tris, segs, 3.8, lambda i, a: 1.62, 4.3, lambda i, a: 1.88, lambda i: steel_hi, 0.95)
    _add_frustum_ring(tris, segs, 4.3, lambda i, a: 1.88, 5.1, lambda i, a: 1.88, lambda i: accent_teal, 1.0)
    _add_frustum_ring(tris, segs, 5.1, lambda i, a: 1.88, 6.9, lambda i, a: 1.72, lambda i: steel_mid, 0.96)
    _add_frustum_ring(tris, segs, 6.9, lambda i, a: 1.72, 7.6, lambda i, a: 1.94, lambda i: steel_hi, 0.98)
    _add_box(tris, 0.0, 5.6, 1.86, 0.36, 0.95, 0.24, steel_dk, 0.96)
    _add_box(tris, 0.0, 5.6, 2.08, 0.20, 0.50, 0.08, accent_teal, 1.05)

    _add_frustum_ring(tris, segs, 7.6, lambda i, a: 1.94, 8.2, lambda i, a: 1.48, lambda i: steel_dk, 0.85)
    _add_frustum_ring(tris, segs, 8.2, lambda i, a: 1.48, 10.2, lambda i, a: 1.52, lambda i: steel_mid, 0.94)
    _add_frustum_ring(tris, segs, 10.2, lambda i, a: 1.52, 11.1, lambda i, a: 2.15, lambda i: steel_hi, 1.0)

    _add_frustum_ring(tris, segs, 11.1, lambda i, a: 2.15, 13.5, lambda i, a: 2.22,
                      lambda i: steel_hi if i % 3 != 0 else steel_dk, 1.0)
    _add_cap(tris, segs, 13.5, lambda i, a: 2.22, True, steel_dk, 0.90)
    _add_cap(tris, segs, 13.52, lambda i, a: 1.55, True, core_glow, 1.08)

    for deg in (90.0, 210.0, 330.0):
        ang = math.radians(deg)
        _add_box(tris, math.cos(ang) * 2.12, 12.1, math.sin(ang) * 2.12, 0.28, 1.15, 0.28, steel_mid, 0.98)
    return 13.5, 2.5, tris


def build_hilt_double():
    """Symmetrical double-bladed staff hilt (-16..+16 cm along Y)."""
    tris = []
    segs = 12
    steel_hi = (192, 198, 210)
    steel_mid = (138, 146, 158)
    steel_dk = (78, 84, 94)
    grip_blk = (38, 42, 50)
    grip_rib = (62, 68, 78)
    accent = (220, 86, 56)
    core_glow = (255, 210, 190)

    # Central reinforced coupler (-2.4..+2.4 cm)
    _add_frustum_ring(tris, segs, -2.4, lambda i, a: 1.92, 2.4, lambda i, a: 1.92,
                      lambda i: steel_hi if i % 2 == 0 else steel_dk, 0.98)
    _add_frustum_ring(tris, segs, -0.7, lambda i, a: 1.98, 0.7, lambda i, a: 1.98, lambda i: accent, 1.04)
    _add_box(tris, 0.0, 0.0, 1.96, 0.34, 1.15, 0.24, steel_dk, 0.95)
    _add_box(tris, 0.0, 0.0, 2.18, 0.18, 0.52, 0.08, accent, 1.06)

    rib = lambda i, a: 1.62 if i % 2 == 0 else 1.44
    # Positive +Y grip + neck + emitter
    _add_frustum_ring(tris, segs, 2.4, rib, 10.6, rib, lambda i: grip_rib if i % 2 == 0 else grip_blk, 0.94)
    _add_frustum_ring(tris, segs, 10.6, lambda i, a: 1.62, 11.4, lambda i, a: 1.96, lambda i: steel_mid, 0.95)
    _add_frustum_ring(tris, segs, 11.4, lambda i, a: 1.96, 12.2, lambda i, a: 1.50, lambda i: steel_dk, 0.85)
    _add_frustum_ring(tris, segs, 12.2, lambda i, a: 1.50, 13.6, lambda i, a: 1.55, lambda i: steel_mid, 0.94)
    _add_frustum_ring(tris, segs, 13.6, lambda i, a: 1.55, 16.0, lambda i, a: 2.22,
                      lambda i: steel_hi if i % 3 != 0 else steel_dk, 1.0)
    _add_cap(tris, segs, 16.0, lambda i, a: 2.22, True, steel_dk, 0.90)
    _add_cap(tris, segs, 16.02, lambda i, a: 1.55, True, core_glow, 1.08)

    # Negative -Y grip + neck + emitter
    _add_frustum_ring(tris, segs, -10.6, rib, -2.4, rib, lambda i: grip_rib if i % 2 == 0 else grip_blk, 0.94)
    _add_frustum_ring(tris, segs, -11.4, lambda i, a: 1.96, -10.6, lambda i, a: 1.62, lambda i: steel_mid, 0.95)
    _add_frustum_ring(tris, segs, -12.2, lambda i, a: 1.50, -11.4, lambda i, a: 1.96, lambda i: steel_dk, 0.85)
    _add_frustum_ring(tris, segs, -13.6, lambda i, a: 1.55, -12.2, lambda i, a: 1.50, lambda i: steel_mid, 0.94)
    _add_frustum_ring(tris, segs, -16.0, lambda i, a: 2.22, -13.6, lambda i, a: 1.55,
                      lambda i: steel_hi if i % 3 != 0 else steel_dk, 1.0)
    _add_cap(tris, segs, -16.0, lambda i, a: 2.22, False, steel_dk, 0.90)
    _add_cap(tris, segs, -16.02, lambda i, a: 1.55, False, core_glow, 1.08)

    for sign in (1.0, -1.0):
        for deg in (45.0, 165.0, 285.0):
            ang = math.radians(deg)
            _add_box(tris, math.cos(ang) * 2.10, 14.7 * sign, math.sin(ang) * 2.10, 0.25, 1.05, 0.25, steel_mid, 0.98)
    return 16.0, 2.5, tris


def build_katana(is_gold):
    """Sculpted katana along +Y (grip 0..22 cm, tsuba 22..23.8 cm, curved blade 23.8..105 cm)."""
    tris = []
    segs = 10
    if is_gold:
        wrap_dark = (34, 28, 22)
        wrap_hi = (224, 178, 56)
        tsuba_col = (242, 198, 60)
        tsuba_edge = (165, 120, 26)
        habaki_col = (255, 220, 96)
        spine_col = (212, 168, 44)
        edge_col = (255, 240, 148)
    else:
        wrap_dark = (32, 36, 44)
        wrap_hi = (78, 86, 98)
        tsuba_col = (195, 162, 68)
        tsuba_edge = (112, 92, 38)
        habaki_col = (215, 192, 118)
        spine_col = (168, 178, 192)
        edge_col = (242, 248, 255)

    # Kashira pommel cap (-2..0 cm) & diamond-wrapped oval tsuka grip (0..22 cm)
    _add_cap(tris, segs, -2.0, lambda i, a: 1.55, False, tsuba_edge, 0.85)
    _add_frustum_ring(tris, segs, -2.0, lambda i, a: 1.55, 0.0, lambda i, a: 1.65, lambda i: tsuba_col, 0.94)
    for k in range(6):
        y0 = (22.0 / 6.0) * k
        y1 = (22.0 / 6.0) * (k + 1)
        oval = lambda i, a, alt=(k % 2): (1.58 + 0.08 * math.cos(2 * a)) * (1.03 if alt else 0.96)
        _add_frustum_ring(tris, segs, y0, oval, y1, oval,
                          lambda i, k0=k: wrap_hi if (i + k0) % 2 == 0 else wrap_dark, 0.95)

    # Tsuba handguard disc (+22..+23.8 cm)
    _add_cap(tris, 14, 22.0, lambda i, a: 4.0, False, tsuba_edge, 0.90)
    _add_frustum_ring(tris, 14, 22.0, lambda i, a: 4.0, 23.8, lambda i, a: 3.9,
                      lambda i: tsuba_col if i % 2 == 0 else tsuba_edge, 1.0)
    _add_cap(tris, 14, 23.8, lambda i, a: 3.9, True, tsuba_col, 0.98)

    # Habaki brass collar (+23.8..+26.0 cm)
    _add_box(tris, 0.0, 24.9, 0.0, 0.65, 1.10, 1.45, habaki_col, 1.02)

    # Curved 4-sided diamond-section steel blade (+26..+105 cm) with sharp forward cutting edge (+Z)
    n_seg = 12
    rings = []
    for k in range(n_seg + 1):
        u = k / n_seg
        y = 26.0 + u * (105.0 - 26.0)
        z_curve = -(u * u) * 2.2
        half_w = 1.42 * (1.0 - 0.58 * (u ** 1.35))
        half_t = 0.44 * (1.0 - 0.55 * (u ** 1.35))
        if k == n_seg:
            rings.append(((0.0, 105.0, z_curve + 0.65), (0.0, 105.0, z_curve + 0.65),
                          (0.0, 105.0, z_curve + 0.65), (0.0, 105.0, z_curve + 0.65)))
        else:
            p_edge = (0.0, y, z_curve + half_w * 1.15)
            p_right = (half_t, y, z_curve)
            p_spine = (0.0, y, z_curve - half_w * 0.85)
            p_left = (-half_t, y, z_curve)
            rings.append((p_edge, p_right, p_spine, p_left))

    for k in range(n_seg):
        e0, r0, s0, l0 = rings[k]
        e1, r1, s1, l1 = rings[k + 1]
        if k == n_seg - 1:
            _add_tri(tris, e0, r0, e1, edge_col, 1.06)
            _add_tri(tris, r0, s0, e1, spine_col, 0.98)
            _add_tri(tris, s0, l0, e1, spine_col, 0.96)
            _add_tri(tris, l0, e0, e1, edge_col, 1.04)
        else:
            _add_quad(tris, e0, r0, r1, e1, edge_col, 1.05)
            _add_quad(tris, r0, s0, s1, r1, spine_col, 0.96)
            _add_quad(tris, s0, l0, l1, s1, spine_col, 0.94)
            _add_quad(tris, l0, e0, e1, l1, edge_col, 1.04)

    return 22.0, 0.0, tris


def build_shield():
    """Sculpted 3D octagonal buckler shield in XY plane facing +Z (~18 cm outer radius)."""
    tris = []
    segs = 8
    rim_gold = (232, 186, 52)
    rim_dark = (150, 114, 28)
    plate_dk = (52, 60, 72)
    plate_mid = (78, 88, 104)
    boss_hi = (165, 178, 198)
    grip_blk = (34, 38, 44)

    r_boss = 5.4
    r_inner = 14.5
    r_outer = 18.0
    z_front_boss = 3.2
    z_plate = 1.1
    z_rim_front = 1.6
    z_back = -1.2

    boss_tip = (0.0, 0.0, z_front_boss)
    back_center = (0.0, 0.0, z_back)

    def ring_pts(rad, z):
        pts = []
        for i in range(segs):
            a = (2.0 * math.pi * i) / segs
            pts.append((math.cos(a) * rad, math.sin(a) * rad, z))
        return pts

    rb = ring_pts(r_boss, 2.0)
    ri = ring_pts(r_inner, z_plate)
    ro_f = ring_pts(r_outer, z_rim_front)
    ro_b = ring_pts(r_outer, z_back)

    for i in range(segs):
        j = (i + 1) % segs
        _add_tri(tris, boss_tip, rb[i], rb[j], boss_hi, 1.04)
        _add_quad(tris, rb[i], ri[i], ri[j], rb[j], plate_mid if i % 2 == 0 else plate_dk, 0.96)
        _add_quad(tris, ri[i], ro_f[i], ro_f[j], ri[j], rim_gold, 1.02)
        _add_quad(tris, ro_f[i], ro_b[i], ro_b[j], ro_f[j], rim_dark, 0.90)
        _add_tri(tris, back_center, ro_b[j], ro_b[i], plate_dk, 0.82)

    # Rear handle grip bar
    _add_box(tris, 0.0, 0.0, -2.2, 1.4, 5.5, 0.8, grip_blk, 0.90)
    return 0.0, 18.0, tris


def build_shuriken():
    """Sculpted 3D 4-pointed beveled ninja star in XZ plane (radius 17.5 cm)."""
    tris = []
    center_col = (56, 62, 74)
    blade_hi = (232, 240, 250)
    blade_mid = (165, 176, 192)
    hub_top = (0.0, 0.85, 0.0)
    hub_bot = (0.0, -0.85, 0.0)

    ring_in = []
    ring_out = []
    tips = []
    for i in range(4):
        a = i * (math.pi * 0.5)
        ca, sa = math.cos(a), math.sin(a)
        a_mid = a + math.pi * 0.25
        ring_in.append((math.cos(a_mid) * 3.8, 0.72, math.sin(a_mid) * 3.8))
        ring_out.append((math.cos(a_mid) * 5.6, 0.0, math.sin(a_mid) * 5.6))
        tips.append((ca * 17.5, 0.0, sa * 17.5))

    for i in range(4):
        j = (i + 1) % 4
        # Top center facets & double-bevel blades
        _add_tri(tris, hub_top, ring_in[i], ring_in[j], center_col, 0.96)
        _add_tri(tris, ring_in[i], ring_out[i], tips[j], blade_mid, 0.98)
        _add_tri(tris, ring_in[i], tips[j], ring_in[j], blade_hi, 1.04)
        _add_tri(tris, ring_in[j], tips[j], ring_out[j], blade_mid, 0.98)

        # Bottom mirror facets so both faces are opaque when spinning
        in_i_b = (ring_in[i][0], -0.72, ring_in[i][2])
        in_j_b = (ring_in[j][0], -0.72, ring_in[j][2])
        _add_tri(tris, hub_bot, in_j_b, in_i_b, center_col, 0.86)
        _add_tri(tris, in_i_b, tips[j], ring_out[i], blade_mid, 0.88)
        _add_tri(tris, in_i_b, in_j_b, tips[j], blade_hi, 0.92)
        _add_tri(tris, in_j_b, ring_out[j], tips[j], blade_mid, 0.88)
    return 0.0, 17.5, tris


def build_wing():
    """Sculpted 3D crescent wing boomerang in XZ plane (span +/-17.0 cm)."""
    tris = []
    core_col = (50, 56, 66)
    edge_hi = (232, 240, 250)
    mid_col = (168, 178, 194)

    # Profile stations along span (-1..+1): (x, z_lead, z_trail, thickness_y)
    stations = [
        (-17.0, 11.0, 13.5, 0.10),
        (-10.5, 6.2, 9.8, 0.55),
        (-4.0, 1.2, 5.2, 0.75),
        (0.0, -0.8, 3.8, 0.82),
        (4.0, 1.2, 5.2, 0.75),
        (10.5, 6.2, 9.8, 0.55),
        (17.0, 11.0, 13.5, 0.10),
    ]
    for k in range(len(stations) - 1):
        x0, l0, t0, h0 = stations[k]
        x1, l1, t1, h1 = stations[k + 1]
        m0 = 0.5 * (l0 + t0)
        m1 = 0.5 * (l1 + t1)
        is_center = (k == 2 or k == 3)
        c_lead = core_col if is_center else edge_hi
        c_trail = core_col if is_center else mid_col

        pl0, pr0, pt0, pb0 = (x0, 0.0, l0), (x0, 0.0, t0), (x0, h0, m0), (x0, -h0, m0)
        pl1, pr1, pt1, pb1 = (x1, 0.0, l1), (x1, 0.0, t1), (x1, h1, m1), (x1, -h1, m1)
        _add_quad(tris, pl0, pt0, pt1, pl1, c_lead, 1.04)
        _add_quad(tris, pt0, pr0, pr1, pt1, c_trail, 0.98)
        _add_quad(tris, pr0, pb0, pb1, pr1, c_trail, 0.88)
        _add_quad(tris, pb0, pl0, pl1, pb1, c_lead, 0.90)
    return 0.0, 17.5, tris


def build_all_meshes():
    builders = {
        "hilt_single": build_hilt_single,
        "hilt_double": build_hilt_double,
        "katana_silver": lambda: build_katana(False),
        "katana_gold": lambda: build_katana(True),
        "shield": build_shield,
        "shuriken": build_shuriken,
        "wing": build_wing,
    }
    meshes = {}
    for name in MESH_NAMES:
        off, rad, tris = builders[name]()
        assert 1 <= len(tris) <= MAX_TRIS_PER_MESH, f"{name}: tri count {len(tris)} out of bounds"
        meshes[name] = (off, rad, tris)
    return meshes


def export_obj(tris, path, name):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# GoldenEye VR {name} mesh (units: cm)\n")
        idx = 1
        for tri in tris:
            for p, _rgba in tri:
                f.write(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}\n")
            f.write(f"f {idx} {idx + 1} {idx + 2}\n")
            idx += 3


def _prng(seed):
    s = seed & 0xFFFFFFFF

    def nxt():
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return ((s >> 8) / 16777216.0) * 2.0 - 1.0

    return nxt


def _pcm(samples):
    return [max(-32767, min(32767, int(round(x * 32767.0)))) for x in samples]


def synth_default_clips():
    """Twelve 22050 Hz mono PCM SFX clips (4 seamless loops + 8 one-shot events)."""
    sr = SAMPLE_RATE
    rng = _prng(0x47454C4E)

    # 0. Idle hum (~1.20 s, exact 66 cycles @ 55 Hz -> seamless loop)
    hum_cycles = 66
    hum_n = int(round(hum_cycles * sr / 55.0))
    hum = []
    for i in range(hum_n):
        u = i / hum_n
        p1 = 2.0 * math.pi * hum_cycles * u
        mod = 0.86 + 0.14 * math.sin(2.0 * math.pi * 3.0 * u)
        v = (0.46 * math.sin(p1) + 0.25 * math.sin(p1 * 2.0 + 0.3) + 0.10 * math.sin(p1 * 3.0)) * mod
        hum.append(v * 0.62)

    # 1. Force Choke / Pull sub-bass rumble (~0.80 s, exact 44 cycles @ 55 Hz)
    rumble_cycles = 44
    rumble_n = int(round(rumble_cycles * sr / 55.0))
    rumble = []
    for i in range(rumble_n):
        u = i / rumble_n
        p = 2.0 * math.pi * rumble_cycles * u
        lfo = 0.80 + 0.20 * math.sin(2.0 * math.pi * 4.0 * u)
        rumble.append((0.68 * math.sin(p) + 0.28 * math.sin(p * 2.0) + 0.12 * rng() * 0.2) * lfo * 0.60)

    # 2. Force Lightning continuous arc crackle (~0.60 s, crossfaded seamless loop)
    light_n = int(sr * 0.60)
    raw_light = []
    ph = 0.0
    for i in range(light_n):
        ph += 2.0 * math.pi * (195.0 + 55.0 * math.sin(i * 0.02)) / sr
        z = rng()
        snap = z * 1.35 if abs(z) > 0.84 else z * 0.24
        raw_light.append((0.48 * math.sin(ph) + 0.52 * snap) * 0.65)
    fade = int(sr * 0.04)
    lightning = list(raw_light)
    for i in range(fade):
        w = i / fade
        lightning[i] = raw_light[i] * w + raw_light[light_n - fade + i] * (1.0 - w)

    # 3. Thrown blade / boomerang spin whoosh (~0.40 s, exact 5 spin cycles @ 12.5 Hz)
    spin_cycles = 5
    spin_n = int(round(spin_cycles * sr / 12.5))
    spin = []
    lp = 0.0
    for i in range(spin_n):
        u = i / spin_n
        mod = 0.45 + 0.55 * math.sin(2.0 * math.pi * spin_cycles * u)
        lp = lp * 0.78 + rng() * 0.22
        tone = math.sin(2.0 * math.pi * 50.0 * u) * 0.35 + lp * 0.75
        spin.append(tone * mod * 0.66)

    # 4. Ignite (~0.42 s)
    ign_n = int(sr * 0.42)
    ign, ph, lp = [], 0.0, 0.0
    for i in range(ign_n):
        t, u = i / sr, i / ign_n
        freq = 85.0 + 390.0 * math.exp(-t * 7.2) + 50.0 * (1.0 - math.exp(-t * 11.0))
        ph += 2.0 * math.pi * freq / sr
        lp = lp * 0.84 + rng() * 0.16
        env = min(1.0, t / 0.016) * (1.0 - 0.55 * u) * (1.0 - u * u)
        ign.append((0.55 * math.sin(ph) + 0.22 * math.sin(2.0 * ph) + 0.42 * lp * math.exp(-t * 7.5)) * env * 0.78)

    # 5. Slash Lasersword (~0.28 s)
    sl_n = int(sr * 0.28)
    sl, ph, lp = [], 0.0, 0.0
    for i in range(sl_n):
        u = i / sl_n
        env = math.sin(math.pi * u) ** 1.15
        ph += 2.0 * math.pi * (120.0 + 185.0 * math.sin(math.pi * u)) / sr
        lp = lp * 0.82 + rng() * 0.18
        sl.append((0.50 * math.sin(ph) + 0.36 * lp) * env * 0.78)

    # 6. Slash Steel (~0.22 s)
    st_n = int(sr * 0.22)
    st, ph, lp = [], 0.0, 0.0
    for i in range(st_n):
        u = i / st_n
        env = math.sin(math.pi * u) * (1.0 - 0.4 * u)
        ph += 2.0 * math.pi * (860.0 + 680.0 * (1.0 - u)) / sr
        lp = lp * 0.65 + rng() * 0.35
        st.append((0.64 * lp + 0.32 * math.sin(ph)) * env * 0.74)

    # 7. Deflect (~0.26 s)
    df_n = int(sr * 0.26)
    df, ph = [], 0.0
    for i in range(df_n):
        t = i / sr
        ph += 2.0 * math.pi * (1620.0 * math.exp(-t * 10.5) + 230.0) / sr
        env = min(1.0, t / 0.004) * math.exp(-t * 13.0)
        df.append((0.66 * math.sin(ph) + 0.24 * math.sin(ph * 1.49) + 0.22 * rng() * math.exp(-t * 24.0)) * env * 0.85)

    # 8. Clash Lasersword (~0.30 s)
    cl_n = int(sr * 0.30)
    cl, ph, ph2 = [], 0.0, 0.0
    for i in range(cl_n):
        t = i / sr
        ph += 2.0 * math.pi * 290.0 / sr
        ph2 += 2.0 * math.pi * 423.0 / sr
        env = min(1.0, t / 0.003) * math.exp(-t * 9.5)
        crackle = rng() * (0.68 if (i % 7 < 3) else 0.16)
        cl.append((0.46 * math.sin(ph + 1.4 * math.sin(ph2)) + 0.48 * crackle) * env * 0.84)

    # 9. Clash Metal (~0.34 s)
    cm_n = int(sr * 0.34)
    cm, ph, ph2 = [], 0.0, 0.0
    for i in range(cm_n):
        t = i / sr
        ph += 2.0 * math.pi * 1360.0 / sr
        ph2 += 2.0 * math.pi * 2120.0 / sr
        env = min(1.0, t / 0.002) * math.exp(-t * 11.5)
        cm.append((0.56 * math.sin(ph + 1.7 * math.sin(ph2)) + 0.32 * math.sin(ph2) + 0.24 * rng() * math.exp(-t * 24.0)) * env * 0.82)

    # 10. Force Push (~0.46 s)
    fp_n = int(sr * 0.46)
    fp, ph, lp = [], 0.0, 0.0
    for i in range(fp_n):
        t = i / sr
        ph += 2.0 * math.pi * (145.0 * math.exp(-t * 7.5) + 38.0) / sr
        lp = lp * 0.82 + rng() * 0.18
        env = min(1.0, t / 0.010) * math.exp(-t * 6.8)
        fp.append((0.68 * math.sin(ph) + 0.46 * lp * math.exp(-t * 5.0)) * env * 0.86)

    # 11. Shadow-Step (~0.38 s)
    ss_n = int(sr * 0.38)
    ss, ph, lp = [], 0.0, 0.0
    for i in range(ss_n):
        t, u = i / sr, i / ss_n
        ph += 2.0 * math.pi * (580.0 + 480.0 * u) / sr
        lp = lp * 0.70 + rng() * 0.30
        env = min(1.0, t / 0.008) * math.exp(-t * 9.5)
        ss.append((0.72 * lp + 0.28 * math.sin(ph)) * env * 0.78)

    raw_clips = {
        "hum": hum,
        "force_rumble": rumble,
        "lightning": lightning,
        "spin": spin,
        "ignite": ign,
        "slash_lasersword": sl,
        "slash_steel": st,
        "deflect": df,
        "clash_lasersword": cl,
        "clash_metal": cm,
        "force_push": fp,
        "shadow_step": ss,
    }
    return {k: (sr, _pcm(v)) for k, v in raw_clips.items()}


def load_wav_mono(path):
    with wave.open(path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"{path}: expected 16-bit PCM WAV (sampwidth={sw})")
    vals = struct.unpack(f"<{n * ch}h", raw)
    if ch == 1:
        mono = list(vals)
    else:
        mono = [int(sum(vals[i * ch:(i + 1) * ch]) / ch) for i in range(n)]
    return sr, mono


def pack_bytes(meshes, clips):
    out = bytearray()
    out += struct.pack("<8sII", MAGIC, len(MESH_NAMES), len(CLIP_NAMES))
    for name in MESH_NAMES:
        emitter_off, blade_rad, tris = meshes[name]
        out += struct.pack("<ffI", emitter_off, blade_rad, len(tris))
        for tri in tris:
            for p, rgba in tri:
                out += struct.pack("<fffBBBB", p[0], p[1], p[2], rgba[0], rgba[1], rgba[2], rgba[3])
    for name in CLIP_NAMES:
        sr, pcm = clips[name]
        out += struct.pack("<II", sr, len(pcm))
        out += struct.pack(f"<{len(pcm)}h", *pcm)
    return bytes(out)


def write_deterministic_zip(bin_bytes, zip_path):
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    zi = zipfile.ZipInfo("lasersword_ninja.bin", date_time=(2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = (0o644 & 0xFFFF) << 16
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(zi, bin_bytes)


def main():
    ap = argparse.ArgumentParser(description="Build GoldenEye VR lasersword_ninja.bin asset pack")
    ap.add_argument("output", help="Output .bin path (e.g. build/lasersword_ninja.bin)")
    ap.add_argument("--zip", help="Also write a deterministic release zip containing lasersword_ninja.bin")
    ap.add_argument("--export-obj-dir", help="Optional directory to write all 7 meshes as .obj files")
    ap.add_argument("--wav-dir", help="Optional directory of <clip>.wav overrides (16-bit PCM)")
    args = ap.parse_args()

    meshes = build_all_meshes()
    if args.export_obj_dir:
        os.makedirs(args.export_obj_dir, exist_ok=True)
        for name in MESH_NAMES:
            export_obj(meshes[name][2], os.path.join(args.export_obj_dir, f"{name}.obj"), name)

    clips = synth_default_clips()
    if args.wav_dir:
        for name in CLIP_NAMES:
            cand = os.path.join(args.wav_dir, f"{name}.wav")
            if os.path.isfile(cand):
                clips[name] = load_wav_mono(cand)

    blob = pack_bytes(meshes, clips)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(blob)

    total_tris = sum(len(meshes[m][2]) for m in MESH_NAMES)
    print(f"wrote {args.output}: {len(blob)} bytes, {len(MESH_NAMES)} meshes ({total_tris} tris), {len(CLIP_NAMES)} clips")
    if args.zip:
        write_deterministic_zip(blob, args.zip)
        print(f"wrote {args.zip}: {os.path.getsize(args.zip)} bytes")


if __name__ == "__main__":
    main()
