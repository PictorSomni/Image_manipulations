"""Brume et mer de nuages en vrai volume.

Chaque rayon part de l'appareil et traverse un champ de densité 3D
(bruit fractal qui se répète), posé sur le sol estimé depuis la carte
de profondeur : on est dans la brume dès le premier mètre, pas de mur
devant. Éclairage d'après Schneider (Nubis) et Hillaire (Frostbite) :
Beer-Lambert, transmittance vers le soleil, phase à deux lobes,
diffusion multiple approchée.

Le volume est calculé en basse résolution, en gardant la lumière et la
transmittance à chaque pas ; chaque pixel pleine résolution reprend le
pas qui correspond à sa propre profondeur, d'où des bords nets.
"""
import math

import cv2
import numpy as np
from scipy import ndimage

_NOISE = {}
_N = 64


def _noise(seed):
    """Bruit 3D 0..1 qui se répète, mélange doux et « chou-fleur »."""
    if seed in _NOISE:
        return _NOISE[seed]
    rng = np.random.default_rng(777 + seed)
    a = ndimage.gaussian_filter(rng.standard_normal((_N,) * 3), 2.2,
                                mode="wrap")
    b = ndimage.gaussian_filter(rng.standard_normal((_N,) * 3), 1.2,
                                mode="wrap")
    a = (a - a.mean()) / a.std()
    b = (b - b.mean()) / b.std()
    # Volutes : bruit doux + bruit « bosselé » (1 - |n|).
    n = 0.6 * a + 0.4 * (1 - np.abs(b) * 1.6)
    n = (n - n.min()) / (n.max() - n.min())
    n = n.astype(np.float32)
    _NOISE[seed] = (n, float(n.mean()), float(n.std()))
    return _NOISE[seed]


def _samp(tex, x, y, z):
    x, y, z = np.broadcast_arrays(x, y, z)
    c = np.stack([x, y, z]) % _N
    return ndimage.map_coordinates(tex, c, order=1, mode="grid-wrap",
                                   prefilter=False)


def _fbm(tex, x, y, z, octs):
    out = np.zeros(x.shape, np.float32)
    for f, w, o in octs:
        out += w * _samp(tex, x * f + o, y * f + 0.37 * o, z * f - o)
    return out


def _ground(f, foc, rw, rh):
    """Plan du sol Y = c0 X + c1 Z + c2 (roulis, plongée, hauteur)."""
    zsc = np.exp(f * math.log(80.0))
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    X = (xx - rw / 2) / foc * zsc
    Y = -(yy - rh / 2) / foc * zsc
    land = f < 0.97
    if land.sum() < 50:
        return None, zsc
    A = np.stack([X[land], zsc[land], np.ones(int(land.sum()))], 1)
    yv = Y[land]
    keep = np.ones(len(yv), bool)
    coef = np.array([0.0, 0.0, -1.0])
    for _ in range(4):
        coef = np.linalg.lstsq(A[keep], yv[keep], rcond=None)[0]
        keep = yv <= A @ coef
        if keep.sum() < 20:
            break
    return coef, zsc


def render(img, far, layer=0.4, size=0.5, billow=0.6, detail=1.0,
           soft=0.2, density=1.0, warmth=0.0, sun=None, res=400.0,
           seed=0, fov=60.0, waves=1.0, steps=72):
    """img float RGB 0..1, far 0..1. layer : hauteur du dessus de la
    nappe, 0.5 = niveau de l'œil (au-delà, on est dedans)."""
    H, W = far.shape
    s = min(1.0, res / max(H, W))
    rh, rw = max(16, int(H * s)), max(16, int(W * s))
    f = cv2.resize(far.astype(np.float32), (rw, rh),
                   interpolation=cv2.INTER_AREA)
    foc = 0.5 * rw / math.tan(math.radians(fov) / 2)
    coef, zsc = _ground(f, foc, rw, rh)
    if coef is None or -coef[2] <= 1e-3:
        return None
    cam = -coef[2]
    tex, nmu, nsd = _noise(int(seed))
    top0 = cam * (0.15 + 1.7 * float(np.clip(layer, 0, 1)))
    R = cam * (0.12 + 1.0 * size ** 1.5)  # taille des grosses volutes
    land = f < 0.97
    zref = float(np.median(zsc[land]))
    sig0 = (0.4 + 2.5 * density ** 1.5) / zref
    octs = [(1.0, 0.55, 0.0), (2.7, 0.28, 11.3), (6.1, 0.17, 23.9)]
    if detail > 1.2:
        octs.append((13.0, 0.1, 31.7))
    # Soleil.
    t = math.tan(math.radians(fov) / 2)
    if sun is None:
        sx, sy = -0.3, -0.25
    else:
        sx, sy = sun[0] / 100.0 - 0.5, sun[1] / 100.0 - 0.5
    lv = np.array([sx * 2 * t * rw / rh, max(0.15, -sy * 2 * t) + 0.25,
                   1.0])
    lv /= np.linalg.norm(lv)
    # Couleurs prises dans la photo : la brume reflète le ciel bas
    # (horizon), le soleil n'ajoute qu'une lueur.
    skym = cv2.resize((far >= 0.97).astype(np.uint8), (rw, rh),
                      interpolation=cv2.INTER_NEAREST) > 0
    small = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
    rowsky = np.nonzero(skym.any(1))[0]
    if rowsky.size:
        band = rowsky[rowsky >= rowsky.max() - max(2, rh // 10)]
        hz = small[band][skym[band]].mean(0)
        sky = small[skym].mean(0)
    else:
        hz = sky = small.reshape(-1, 3).mean(0)
    lum = float(hz.mean())
    amb = (0.75 * hz / max(1e-3, hz.max()) + 0.25) \
        * np.clip(0.35 + 0.8 * lum, 0.45, 1.0)
    amb = amb.astype(np.float32)
    sun_c = (0.5 * hz / max(1e-3, hz.max()) + 0.5).astype(np.float32) \
        * np.array([1.0, 0.97 + 0.02 * warmth, 0.92 - 0.1 * warmth],
                   np.float32)
    # Rayons (z = profondeur de vue, comme la carte).
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    dx = ((xx - rw / 2) / foc).ravel()
    dy = (-(yy - rh / 2) / foc).ravel()
    dlen = np.sqrt(dx * dx + dy * dy + 1)
    cosv = (dx * lv[0] + dy * lv[1] + lv[2]) / dlen
    g1, g2 = 0.6, -0.25

    def hg(g):
        return (1 - g * g) / (1 + g * g - 2 * g * cosv) ** 1.5 / 4 / math.pi
    phase = np.minimum((0.75 * hg(g1) + 0.25 * hg(g2)) * 4 * math.pi, 2.5)
    zs = np.geomspace(0.05 * cam, 80.0, steps + 1)
    T = np.ones(dx.shape, np.float32)
    L = np.zeros((dx.size, 3), np.float32)
    Ts = np.empty((steps + 1, rh, rw), np.float16)
    Ls = np.empty((steps + 1, rh, rw, 3), np.float16)
    Ts[0] = 1
    Ls[0] = 0
    wscale = 1.0 / R
    for i in range(steps):
        za, zb = zs[i], zs[i + 1]
        rnd = 0.5 if i == 0 else 0.5
        z = za + (zb - za) * rnd
        dz = (zb - za) * dlen
        px, py = dx * z, dy * z
        hp = py - (coef[0] * px + coef[1] * z + coef[2])
        # Dessus de la nappe : houle large + soulèvements.
        wx, wz = px * wscale * 0.18 * _N / 8, z * wscale * 0.18 * _N / 8
        # Gros bancs (cumulus) et creux : bruit large normalisé, deux
        # octaves, bosses arrondies.
        b1 = (_samp(tex, wx, 5.0, wz) - nmu) / nsd
        b2 = (_samp(tex, wx * 2.3 + 17, 9.0, wz * 2.3) - nmu) / nsd
        bb = np.clip(0.7 * b1 + 0.3 * b2, -2.5, 2.5)
        top = top0 * (1 + 0.55 * waves * bb)
        top = np.maximum(top, 0.04 * cam)
        m = hp < top * 1.35
        if not m.any():
            Ts[i + 1] = T.reshape(rh, rw)
            Ls[i + 1] = L.reshape(rh, rw, 3)
            continue
        ix = np.nonzero(m)[0]
        qx = px[ix] * wscale * _N / 4
        qy = hp[ix] * wscale * _N / 4
        qz = z * wscale * _N / 4 * np.ones(ix.size, np.float32)
        nse = _fbm(tex, qx, qy, qz, octs)
        # Densité quasi constante dans la nappe : le bruit ne fait que
        # déplacer sa surface (volutes). Plus on regarde bas, plus on
        # traverse de nuage, plus c'est opaque.
        cov = 0.35 + 0.9 * billow

        def dens_at(h_, n_, t_):
            tn = t_ * (1 + cov * (n_ - nmu) / nsd * 0.12)
            d_ = np.clip((tn - h_) / (0.4 * t_ + 1e-6), 0, 1)
            return d_ * d_ * (3 - 2 * d_) * (0.85 + 0.6 * (n_ - nmu))
        hn = hp[ix] / top[ix]
        dens = dens_at(hp[ix], nse, top[ix])
        sg = sig0 * dens
        if not sg.any():
            Ts[i + 1] = T.reshape(rh, rw)
            Ls[i + 1] = L.reshape(rh, rw, 3)
            continue
        # Transmittance vers le soleil : deux échantillons.
        tau = np.zeros(ix.size, np.float32)
        for d_ in (0.25, 0.9):
            o = d_ * R
            lx, ly, lz = (px[ix] + lv[0] * o, hp[ix] + lv[1] * o,
                          z + lv[2] * o)
            nl = _fbm(tex, lx * wscale * _N / 4, ly * wscale * _N / 4,
                      lz * wscale * _N / 4, octs[:2])
            tau += sig0 * zref * 2.5 * dens_at(ly, nl, top[ix]) * d_
        # Diffusion multiple (Wrenninge) : trois ordres.
        light = np.zeros(ix.size, np.float32)
        for k, (a_, b_) in enumerate(((1, 1), (0.5, 0.4), (0.25, 0.15))):
            ph = phase[ix] if k == 0 else 1.0 + (phase[ix] - 1) * 0.3 ** k
            light += a_ * np.exp(-tau * b_) * ph
        powder = 1 - np.exp(-sig0 * zref * 4 * dens)
        light *= 0.55 + 0.45 * powder
        hgt = np.clip(hn, 0, 1)
        ambk = 0.45 + 0.4 * hgt
        col = (sun_c[None] * light[:, None] * 0.18
               + amb[None] * ambk[:, None] * 0.85)
        ext = np.exp(-sg * dz[ix])
        Ti = T[ix]
        L[ix] += (Ti * (1 - ext))[:, None] * col
        T[ix] = Ti * ext
        Ts[i + 1] = T.reshape(rh, rw)
        Ls[i + 1] = L.reshape(rh, rw, 3)
    # Pleine résolution : chaque pixel reprend le pas de sa profondeur.
    zf = np.exp(far.astype(np.float32) * math.log(80.0))
    zf[far >= 0.97] = 80.0
    lz = np.log(zs)
    kf = np.interp(np.log(np.maximum(zf, zs[0])), lz,
                   np.arange(steps + 1)).astype(np.float32)
    k0 = np.minimum(kf.astype(np.int32), steps - 1)
    fr = (kf - k0)
    Tout = np.ones((H, W), np.float32)
    Lout = np.zeros((H, W, 3), np.float32)
    flat = k0.ravel()
    order = np.argsort(flat, kind="stable")
    bounds = np.searchsorted(flat[order], np.arange(steps + 1))
    To, Lo, frf = Tout.ravel(), Lout.reshape(-1, 3), fr.ravel()
    for k in range(steps):
        sel = order[bounds[k]:bounds[k + 1]]
        if not sel.size:
            continue
        ta = cv2.resize(Ts[k].astype(np.float32), (W, H)).ravel()[sel]
        tb = cv2.resize(Ts[k + 1].astype(np.float32), (W, H)).ravel()[sel]
        la = cv2.resize(Ls[k].astype(np.float32), (W, H)).reshape(-1, 3)
        lb = cv2.resize(Ls[k + 1].astype(np.float32), (W, H)).reshape(-1, 3)
        w = frf[sel]
        To[sel] = ta + (tb - ta) * w
        Lo[sel] = la[sel] + (lb[sel] - la[sel]) * w[:, None]
    return img * Tout[..., None] + Lout
