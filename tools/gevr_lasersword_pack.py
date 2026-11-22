#!/usr/bin/env python3
"""
Build the downloadable Lasersword asset pack (lasersword.bin) for GoldenEye VR.

Writes binary format GEVRLS1\\0 containing:
  1. Original copyright-safe 3D industrial energy-sword hilt mesh (triangle
     soup with baked directional/rim/AO vertex colors in cm, +Y = blade axis).
  2. Five 22050 Hz mono 16-bit PCM SFX clips (hum, ignite, slash, deflect, clash).

Pure Python 3 standard library only (no external packages required).
"""

import argparse
import math
import os
import struct
import wave
import zipfile

MAGIC = b"GEVRLS1\x00"
SAMPLE_RATE = 22050
MAX_TRIS = 4096
CLIP_NAMES = ("hum", "ignite", "slash", "deflect", "clash")

LIGHT_DIR = (0.42, 0.72, 0.55)
RIM_DIR = (-0.50, -0.25, -0.83)


def _norm3(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if l < 1e-8:
        return (0.0, 1.0, 0.0)
    return (v[0] / l, v[1] / l, v[2] / l)


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
    mul = (0.32 + 0.58 * ndotl + 0.16 * (spec * spec)) * ao
    # Subtle Y gradient along hilt
    mul *= max(0.82, min(1.08, 0.96 + p[1] * 0.005))
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
        (0, 1, 2, 3),  # +Z
        (5, 4, 7, 6),  # -Z
        (4, 0, 3, 7),  # -X
        (1, 5, 6, 2),  # +X
        (3, 2, 6, 7),  # +Y
        (4, 5, 1, 0),  # -Y
    ]
    for a, b, c, d in faces:
        _add_tri(tris, v[a], v[b], v[c], col, ao)
        _add_tri(tris, v[a], v[c], v[d], col, ao)


def build_default_hilt():
    """Original copyright-safe machined metal hilt (~14 cm along Y, emitter at +13.5 cm)."""
    tris = []
    segs = 12

    steel_hi = (195, 202, 212)
    steel_mid = (145, 152, 164)
    steel_dk = (92, 98, 108)
    grip_blk = (42, 46, 54)
    grip_rib = (68, 74, 84)
    accent_teal = (62, 185, 205)
    core_glow = (170, 232, 255)

    # Bottom pommel cap (-10.6..-8.4 cm)
    _add_cap(tris, segs, -10.6, lambda i, a: 1.50, False, steel_dk, 0.85)
    _add_frustum_ring(tris, segs, -10.6, lambda i, a: 1.50, -9.8, lambda i, a: 1.85,
                      lambda i: steel_mid, 0.92)
    _add_frustum_ring(tris, segs, -9.8, lambda i, a: 1.85, -8.5, lambda i, a: 1.85,
                      lambda i: steel_hi if i % 2 == 0 else steel_dk, 0.95)
    _add_frustum_ring(tris, segs, -8.5, lambda i, a: 1.85, -8.2, lambda i, a: 1.62,
                      lambda i: steel_dk, 0.80)

    # Fluted grip cylinder (-8.2..+3.8 cm) with alternating raised axial ribs
    rib = lambda i, a: 1.64 if i % 2 == 0 else 1.46
    _add_frustum_ring(tris, segs, -8.2, rib, 3.8, rib,
                      lambda i: grip_rib if i % 2 == 0 else grip_blk, 0.94)

    # Mid collar & activation switch block (+3.8..+7.6 cm)
    _add_frustum_ring(tris, segs, 3.8, lambda i, a: 1.62, 4.3, lambda i, a: 1.88,
                      lambda i: steel_hi, 0.95)
    _add_frustum_ring(tris, segs, 4.3, lambda i, a: 1.88, 5.1, lambda i, a: 1.88,
                      lambda i: accent_teal, 1.0)
    _add_frustum_ring(tris, segs, 5.1, lambda i, a: 1.88, 6.9, lambda i, a: 1.72,
                      lambda i: steel_mid, 0.96)
    _add_frustum_ring(tris, segs, 6.9, lambda i, a: 1.72, 7.6, lambda i, a: 1.94,
                      lambda i: steel_hi, 0.98)
    _add_box(tris, 0.0, 5.6, 1.86, 0.36, 0.95, 0.24, steel_dk, 0.96)
    _add_box(tris, 0.0, 5.6, 2.08, 0.20, 0.50, 0.08, accent_teal, 1.05)

    # Tapered emitter neck (+7.6..+10.4 cm)
    _add_frustum_ring(tris, segs, 7.6, lambda i, a: 1.94, 8.2, lambda i, a: 1.48,
                      lambda i: steel_dk, 0.85)
    _add_frustum_ring(tris, segs, 8.2, lambda i, a: 1.48, 10.2, lambda i, a: 1.52,
                      lambda i: steel_mid, 0.94)
    _add_frustum_ring(tris, segs, 10.2, lambda i, a: 1.52, 11.1, lambda i, a: 2.15,
                      lambda i: steel_hi, 1.0)

    # Flared emitter crown & recessed energy aperture (+11.1..+13.5 cm)
    _add_frustum_ring(tris, segs, 11.1, lambda i, a: 2.15, 13.5, lambda i, a: 2.22,
                      lambda i: steel_hi if i % 3 != 0 else steel_dk, 1.0)
    _add_cap(tris, segs, 13.5, lambda i, a: 2.22, True, steel_dk, 0.9)
    _add_cap(tris, segs, 13.52, lambda i, a: 1.55, True, core_glow, 1.08)

    # 3 ventilated side shroud fins around the emitter crown
    fin_angles = (math.radians(90.0), math.radians(210.0), math.radians(330.0))
    for ang in fin_angles:
        fx = math.cos(ang) * 2.12
        fz = math.sin(ang) * 2.12
        _add_box(tris, fx, 12.1, fz, 0.28, 1.15, 0.28, steel_mid, 0.98)

    assert 1 <= len(tris) <= MAX_TRIS, f"Unexpected tri count {len(tris)}"
    return tris


def load_obj_tris(path, scale=1.0):
    verts = []
    tris = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "v" and len(parts) >= 4:
                verts.append((
                    float(parts[1]) * scale,
                    float(parts[2]) * scale,
                    float(parts[3]) * scale,
                ))
            elif parts[0] == "f" and len(parts) >= 4:
                idxs = []
                for tok in parts[1:]:
                    vi = int(tok.split("/")[0])
                    idxs.append(vi - 1 if vi > 0 else len(verts) + vi)
                for k in range(1, len(idxs) - 1):
                    p0, p1, p2 = verts[idxs[0]], verts[idxs[k]], verts[idxs[k + 1]]
                    _add_tri(tris, p0, p1, p2, (165, 172, 184), 0.96)
    if not (1 <= len(tris) <= MAX_TRIS):
        raise ValueError(f"OBJ triangle count {len(tris)} outside [1, {MAX_TRIS}]")
    return tris


def export_obj(tris, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# GoldenEye VR Lasersword hilt mesh (units: cm, +Y = blade axis)\n")
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


def _pcm_from_floats(samples):
    return [max(-32767, min(32767, int(round(x * 32767.0)))) for x in samples]


def synth_default_clips():
    """Original synthesized 22050 Hz mono energy-weapon clips."""
    sr = SAMPLE_RATE
    rng = _prng(0x47455652)

    # 0. Idle hum (~1.20 s, integer cycle count @ 55 Hz -> zero-click loop)
    hum_n = int(round(sr * 1.20 / 1.0))
    # Snap sample count to whole cycles of 55 Hz: 66 cycles = 26460 samples
    hum_cycles = 66
    hum_n = int(round(hum_cycles * sr / 55.0))
    hum = []
    for i in range(hum_n):
        u = i / hum_n
        p1 = 2.0 * math.pi * hum_cycles * u
        p2 = 2.0 * math.pi * (hum_cycles * 2) * u
        p3 = 2.0 * math.pi * (hum_cycles * 3) * u
        mod = 0.85 + 0.15 * math.sin(2.0 * math.pi * 2.0 * u)
        v = (0.42 * math.sin(p1) + 0.24 * math.sin(p2 + 0.3) + 0.08 * math.sin(p3)) * mod
        hum.append(v * 0.62)

    # 1. Ignite (~0.42 s)
    ign_n = int(sr * 0.42)
    ign = []
    ph = 0.0
    lp = 0.0
    for i in range(ign_n):
        t = i / sr
        u = i / ign_n
        freq = 75.0 + 360.0 * math.exp(-t * 7.5) + 45.0 * (1.0 - math.exp(-t * 12.0))
        ph += 2.0 * math.pi * freq / sr
        lp = lp * 0.86 + rng() * 0.14
        env = min(1.0, t / 0.018) * ((1.0 - 0.55 * u) * (1.0 - u * u))
        v = (0.55 * math.sin(ph) + 0.22 * math.sin(2.0 * ph) + 0.40 * lp * math.exp(-t * 8.0)) * env
        ign.append(v * 0.78)

    # 2. Slash (~0.28 s)
    sl_n = int(sr * 0.28)
    sl = []
    ph = 0.0
    lp = 0.0
    for i in range(sl_n):
        t = i / sr
        u = i / sl_n
        env = math.sin(math.pi * u) ** 1.15
        freq = 125.0 + 180.0 * math.sin(math.pi * u)
        ph += 2.0 * math.pi * freq / sr
        lp = lp * 0.82 + rng() * 0.18
        v = (0.48 * math.sin(ph) + 0.38 * lp) * env
        sl.append(v * 0.78)

    # 3. Deflect (~0.22 s)
    df_n = int(sr * 0.22)
    df = []
    ph = 0.0
    for i in range(df_n):
        t = i / sr
        freq = 1480.0 * math.exp(-t * 11.0) + 210.0
        ph += 2.0 * math.pi * freq / sr
        env = min(1.0, t / 0.004) * math.exp(-t * 14.0)
        v = (0.65 * math.sin(ph) + 0.25 * math.sin(ph * 1.49) + 0.22 * rng() * math.exp(-t * 25.0)) * env
        df.append(v * 0.85)

    # 4. Clash (~0.30 s)
    cl_n = int(sr * 0.30)
    cl = []
    ph = 0.0
    for i in range(cl_n):
        t = i / sr
        ph += 2.0 * math.pi * (165.0 + 90.0 * math.exp(-t * 14.0)) / sr
        env = min(1.0, t / 0.003) * math.exp(-t * 9.5)
        crackle = rng() * (0.65 if (i % 7 < 3) else 0.15)
        v = (0.50 * math.sin(ph) + 0.45 * crackle) * env
        cl.append(v * 0.85)

    return {
        "hum": (sr, _pcm_from_floats(hum)),
        "ignite": (sr, _pcm_from_floats(ign)),
        "slash": (sr, _pcm_from_floats(sl)),
        "deflect": (sr, _pcm_from_floats(df)),
        "clash": (sr, _pcm_from_floats(cl)),
    }


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


def pack_bytes(tris, clips, emitter_offset_cm, blade_radius_cm):
    out = bytearray()
    out += struct.pack("<8sffII", MAGIC, emitter_offset_cm, blade_radius_cm, len(tris), len(CLIP_NAMES))
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
    zi = zipfile.ZipInfo("lasersword.bin", date_time=(2026, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = (0o644 & 0xFFFF) << 16
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(zi, bin_bytes)


def main():
    ap = argparse.ArgumentParser(description="Build GoldenEye VR lasersword.bin asset pack")
    ap.add_argument("output", help="Output .bin path (e.g. build/lasersword.bin)")
    ap.add_argument("--obj", help="Optional Wavefront .obj hilt mesh (in cm, +Y = blade axis)")
    ap.add_argument("--obj-scale", type=float, default=1.0, help="Scale multiplier for --obj (default: 1.0)")
    ap.add_argument("--export-obj", help="Write the packed hilt triangles as a Wavefront .obj for Blender")
    ap.add_argument("--emitter-y", type=float, default=13.5, help="Blade emitter Y offset in cm (default: 13.5)")
    ap.add_argument("--blade-radius", type=float, default=1.8, help="Blade radius in cm (default: 1.8)")
    ap.add_argument("--zip", help="Also write a deterministic release zip containing lasersword.bin")
    for name in CLIP_NAMES:
        ap.add_argument(f"--wav-{name}", help=f"Optional 16-bit PCM WAV override for '{name}' SFX")
    args = ap.parse_args()

    tris = load_obj_tris(args.obj, args.obj_scale) if args.obj else build_default_hilt()
    if args.export_obj:
        os.makedirs(os.path.dirname(os.path.abspath(args.export_obj)), exist_ok=True)
        export_obj(tris, args.export_obj)

    clips = synth_default_clips()
    for name in CLIP_NAMES:
        wav_path = getattr(args, f"wav_{name}")
        if wav_path:
            clips[name] = load_wav_mono(wav_path)

    blob = pack_bytes(tris, clips, args.emitter_y, args.blade_radius)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(blob)

    print(f"wrote {args.output}: {len(blob)} bytes, {len(tris)} tris, {len(CLIP_NAMES)} clips")
    if args.zip:
        write_deterministic_zip(blob, args.zip)
        print(f"wrote {args.zip}: {os.path.getsize(args.zip)} bytes")


if __name__ == "__main__":
    main()
