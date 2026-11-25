"""Mer de nuages vue d'en haut (brume « Volume »).

Le dessus de la nappe est un champ de hauteur : demi-sphères empilées
à plusieurs échelles (cumulus « chou-fleur »), houle large et bancs de
gros dômes qui en sortent, sur une texture 2048 px qui se répète, avec
sa pyramide de moyennes. La nappe est posée sur le plan du sol de la
photo (déduit de la carte d'éloignement) : chaque pixel lance un rayon
découpé en tranches de hauteur (« steep parallax ») et la scène plus
proche que le nuage (murs, arbres, collines) en sort.

Éclairage doux, d'après Schneider (Nubis) et Hillaire (Frostbite) :
normale lissée, ombres portées des bancs, creux plus sombres,
perspective atmosphérique vers la couleur de l'horizon.
"""
import math

import cv2
import numpy as np

_TEX = {}


def _wblur(a, sig):
    """Flou gaussien sur une texture qui se répète."""
    p = int(min(a.shape[0] // 2, 3 * sig + 2))
    b = np.pad(a, p, mode="wrap")
    return cv2.GaussianBlur(b, (0, 0), sig)[p:-p, p:-p]


def _domes(n, r, rng, fill=0.9, inside=None):
    """Union de demi-sphères (rayon ~r px) sur une texture n x n qui se
    répète ; hauteur en unités de rayon. inside : centres gardés
    seulement là où ce masque est vrai."""
    count = max(4, int(fill * n * n / (r * r)))
    pts = rng.random((count, 2)) * n
    if inside is not None:
        ok = inside[pts[:, 1].astype(int), pts[:, 0].astype(int)]
        pts = pts[ok] if ok.sum() >= 4 else pts
        count = len(pts)
    # Tailles très mêlées : petites et grosses volutes côte à côte.
    rad = r * np.clip(rng.lognormal(0.0, 0.45, count), 0.3, 2.5)
    out = np.zeros((n, n), np.float32)
    # Par paquets de rayon voisin : distanceTransform par paquet, puis
    # profil de sphère, union par max.
    order = np.argsort(rad)
    for chunk in np.array_split(order, 6):
        if not len(chunk):
            continue
        rr = float(rad[chunk].mean())
        m = np.full((3 * n, 3 * n), 255, np.uint8)
        for ox in (0, n, 2 * n):
            for oy in (0, n, 2 * n):
                xs = (pts[chunk, 0] + ox).astype(int)
                ys = (pts[chunk, 1] + oy).astype(int)
                m[ys, xs] = 0
        d = cv2.distanceTransform(m, cv2.DIST_L2, 5)[n:2 * n, n:2 * n]
        dome = np.sqrt(np.clip(1 - (d / rr) ** 2, 0, 1)) * rr / r
        np.maximum(out, dome, out=out)
    return out


def _texture(seed, detail):
    """Champ de hauteur cumulus qui se répète, 0..1, et son pyramide."""
    key = (seed, round(detail, 2))
    if key in _TEX:
        return _TEX[key]
    rng = np.random.default_rng(1234 + seed)
    n = 1024
    r0 = 96.0
    h = _domes(n, r0, rng, 0.8)
    # Volutes sur les volutes : chaque octave posée sur le dessus des
    # précédentes, de plus en plus petites.
    w, r = 0.55, r0
    octaves = 3 + int(round(2 * detail))
    for _ in range(octaves):
        r *= 0.42
        if r < 1.5:
            break
        o = _domes(n, r, rng, 1.1)
        # Seulement là où il y a déjà du nuage : pas de grains isolés.
        h = h + w * o * np.clip(h * 2, 0, 1)
        # Bord fractal : petites volutes serrées le long du contour,
        # qui débordent (plus de grand bord lisse).
        m = (h > 0.02).astype(np.uint8)
        kr = max(3, int(r * 0.6)) | 1
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kr, kr))
        bord = (m > 0) & (cv2.erode(m, ker) == 0)
        e = _domes(n, r * 0.6, rng, 3.0, bord)
        # Hauteur du voisinage : la volute de bord est aussi claire que
        # la masse qu'elle prolonge, pas un grain sombre.
        dil = cv2.dilate(h, ker)
        h = np.where(e > 0, np.maximum(h, dil * (0.55 + 0.45 * e)), h)
        w *= 0.6
    h = h / max(1e-3, float(np.percentile(h, 99.7)))
    h = np.clip(h, 0, 1.2).astype(np.float32)
    levels = [h]
    for _ in range(7):
        levels.append(_wblur(levels[-1], 2 ** len(levels) * 0.5))
    _TEX[key] = (levels, r0, n)
    if len(_TEX) > 4:
        _TEX.pop(next(iter(_TEX)))
    return _TEX[key]


def sky_mask(far):
    """Ciel : plateau plat de la carte d'éloignement relié au haut du
    cadre (sa valeur varie d'une photo à l'autre)."""
    top = far[: max(1, far.shape[0] // 20)]
    v = float(np.median(top))
    if v < 0.5 or float(top.std()) > 0.03:
        return far >= 0.97
    return far >= v - 0.02



_SEA = {}


def _wup(a, size):
    """Agrandit une texture qui se répète (raccord sans couture)."""
    k = a.shape[0] / size
    c = ((np.arange(size, dtype=np.float32) + 0.5) * k - 0.5)
    mx, my = np.meshgrid(c, c)
    return cv2.remap(a, mx, my, cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_WRAP)


def _sea_texture(seed):
    """Dessus de la mer, en hauteurs de volute, sur une texture 2048 px
    qui se répète : dômes empilés (chou-fleur), houle large, et tours
    de dômes deux fois plus gros sur les bancs hauts (elles sortent de
    la couche sans couture). Pyramide de moyennes 2x2. ~1,5 s sur le
    Pi, gardé en cache."""
    if seed in _SEA:
        return _SEA[seed]
    rng = np.random.default_rng(4321 + seed)
    n, r0 = 512, 44.0
    h = _domes(n, r0, rng, 0.9)
    w, r = 0.55, r0
    for _ in range(3):
        r *= 0.45
        # Seulement sur le nuage déjà là : pas de grains isolés.
        h = h + w * _domes(n, r, rng, 1.2) * np.clip(h * 2, 0, 1)
        w *= 0.6
    h = np.clip(h / max(1e-3, float(np.percentile(h, 99.5))), 0, 1.1)
    # Creux entre dômes comblés en douceur : pas de puits.
    h = np.maximum(h, 0.7 * _wblur(h, r0 * 0.5)).astype(np.float32)
    N = 4 * n
    wv = _wblur(rng.standard_normal((N // 32, N // 32)), 2.5)
    wv = _wup(((wv - wv.mean()) / (wv.std() + 1e-6)).astype(np.float32), N)
    # Bancs hauts : sur la houle, dômes deux fois plus gros (pied
    # adouci, pas de falaise) qui sortent de la couche sans couture.
    big = _wblur(np.roll(h, (n // 3, n // 5), (0, 1)), r0 * 0.2)
    big = np.tile(_wup(big.astype(np.float32), 2 * n), (2, 2))
    bm = np.clip((wv - 0.4) / 1.3, 0, 1)
    bm = bm * bm * (3 - 2 * bm)
    f = 0.3 * wv + (np.tile(h, (4, 4)) - 0.3) + 2.1 * bm * big
    mips = [f.astype(np.float32)]
    while mips[-1].shape[0] > 8:
        mips.append(cv2.resize(mips[-1], None, fx=0.5, fy=0.5,
                               interpolation=cv2.INTER_AREA))
    _SEA[seed] = (mips, r0, N, float(f.min()), float(f.max()))
    if len(_SEA) > 2:
        _SEA.pop(next(iter(_SEA)))
    return _SEA[seed]


def _by_lod(mips, u, v, lod, interp=cv2.INTER_LINEAR):
    """Échantillonne la pyramide en (u, v) px du niveau 0 ; niveau
    choisi par bande de lignes (la taille d'un pixel au sol varie
    surtout avec la ligne), fondu entre deux niveaux."""
    out = np.empty(u.shape, np.float32)
    top = len(mips) - 2
    # Le plus fin de la ligne : les rayons perdus (ciel, objets) ne
    # floutent pas le reste.
    k = np.clip(lod.min(axis=1), 0, top).astype(int)
    start = 0
    for i in range(1, len(k) + 1):
        if i < len(k) and k[i] == k[start]:
            continue
        sl, q = slice(start, i), int(k[start])
        a, b = (cv2.remap(mips[j], (u[sl] + 0.5) / 2 ** j - 0.5,
                          (v[sl] + 0.5) / 2 ** j - 0.5, interp,
                          borderMode=cv2.BORDER_WRAP)
                for j in (q, q + 1))
        out[sl] = a + (b - a) * np.clip(lod[sl] - q, 0, 1)
        start = i
    return out


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


_VOL_CACHE = {}


def _noise3(seed, n=48):
    """Bruit 3D périodique n³ (2 octaves), 0..1, mis en cache."""
    if seed not in _VOL_CACHE:
        rng = np.random.default_rng(1234 + seed)
        out = np.zeros((n, n, n), np.float32)
        for sig, w in ((4.0, 0.7), (1.6, 0.3)):
            r = rng.random((n, n, n)).astype(np.float32)
            f = np.fft.fftn(r)
            k = np.fft.fftfreq(n)
            kk = k[:, None, None] ** 2 + k[None, :, None] ** 2 + \
                k[None, None, :] ** 2
            r = np.real(np.fft.ifftn(f * np.exp(-2 * (np.pi * sig) ** 2
                                                * kk)))
            r = (r - r.mean()) / (r.std() + 1e-6)
            out += w * r.astype(np.float32)
        out = 0.5 + 0.22 * out
        _VOL_CACHE[seed] = np.clip(out, 0, 1)
    return _VOL_CACHE[seed]


def _tri(v, x, y, z):
    """Lecture trilinéaire périodique de v en coordonnées voxels."""
    n = v.shape[0]
    x0, y0, z0 = np.floor(x), np.floor(y), np.floor(z)
    fx, fy, fz = x - x0, y - y0, z - z0
    x0 = x0.astype(np.int32) % n
    y0 = y0.astype(np.int32) % n
    z0 = z0.astype(np.int32) % n
    x1, y1, z1 = (x0 + 1) % n, (y0 + 1) % n, (z0 + 1) % n
    c00 = v[x0, y0, z0] * (1 - fx) + v[x1, y0, z0] * fx
    c10 = v[x0, y1, z0] * (1 - fx) + v[x1, y1, z0] * fx
    c01 = v[x0, y0, z1] * (1 - fx) + v[x1, y0, z1] * fx
    c11 = v[x0, y1, z1] * (1 - fx) + v[x1, y1, z1] * fx
    c0 = c00 * (1 - fy) + c10 * fy
    c1 = c01 * (1 - fy) + c11 * fy
    return c0 * (1 - fz) + c1 * fz


def _face_volume(img, far, yh, layer, size, billow, detail, soft, amount,
                 warmth, sun, seed, fade, visible, shift=(0.0, 0.0),
                 fov=60.0):
    """Vue de face : vrai volume de cumulus en 3D, marché le long de
    chaque rayon de l'œil jusqu'à l'objet (carte de profondeur). Œil à
    1 au-dessus du sol (y = -1) ; nuages du sol jusqu'à y = -1 + T."""
    H, W = far.shape
    s = min(1.0, 320.0 / max(H, W))
    rh, rw = max(16, int(H * s)), max(16, int(W * s))
    foc = 0.5 * rw / math.tan(math.radians(fov) / 2)
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    dx = (xx - rw / 2) / foc
    dy = (yh * rh - yy) / foc
    farl = cv2.resize(far.astype(np.float32), (rw, rh),
                      interpolation=cv2.INTER_AREA)
    skym = sky_mask(farl)
    # Distance de la scène : profondeur relative recalée sur le plan du
    # sol (rayons descendants), ciel au loin.
    zr = np.exp(farl * math.log(80.0))
    gp = np.where(dy < -1e-3, -1.0 / np.minimum(dy, -1e-3), np.inf)
    ok = (~skym) & np.isfinite(gp) & (gp < 60)
    k = (float(np.median(gp[ok] / zr[ok])) if ok.sum() > 50 else 1.0)
    tmax = 90.0
    ts = np.where(skym, tmax, np.minimum(zr * k, tmax)).astype(np.float32)
    ts = cv2.erode(ts, np.ones((3, 3), np.uint8))  # pas de halo
    ts = np.exp(cv2.GaussianBlur(np.log(ts), (0, 0), 3))
    # Nuage : épaisseur (Hauteur), taille des cellules (Taille),
    # bosses (Bosses), détail (Grain).
    T = 1.2 + 6.0 * float(np.clip(layer, 0, 1))
    L = 2.5 + 3.5 * float(np.clip(size, 0.5, 2.0))  # cellule monde
    cov = 0.45 + 0.2 * float(np.clip(fade, 0, 1))
    kb = float(np.clip(billow - 0.5, 0, 0.5)) * 2  # cumulus
    bil = 0.6 + 0.8 * float(np.clip(billow, 0, 0.5))
    det = float(np.clip(detail, 0, 1))
    nv = _noise3(int(seed))
    n = nv.shape[0]
    cx = float(shift[0]) * 3.0
    cy = 0.0  # ponytail: caméra à hauteur fixe, x seul

    from cloud_volume import _noise, _fbm
    tex = _noise(int(seed))[0]
    q = 64.0 / L  # voxels par unité monde (1 cellule = L)
    # Forme : 3 octaves ; Grain : octaves fines qui rongent les bords ;
    # opacité : bruit large indépendant (trouées, densité variable).
    base_o = ((0.25, 0.6, 0.0), (0.5, 0.28, 11.0), (1.0, 0.12, 23.0))
    fine_o = ((2.0, 0.5, 5.0), (4.0, 0.3, 17.0), (8.0, 0.2, 29.0))

    def dens(px, py, pz):
        hf = (py + 1.0) / T
        X, Y, Z = px * q, py * q * 1.6, pz * q
        # Volutes : coordonnées tordues par un bruit (domain warp).
        w1 = _fbm(tex, X * 0.5 + 91, Y * 0.5, Z * 0.5, ((1, 1, 0),))
        w2 = _fbm(tex, X * 0.5, Y * 0.5 + 53, Z * 0.5 - 7, ((1, 1, 0),))
        X = X + (w1 - 0.5) * 12 * bil
        Y = Y + (w2 - 0.5) * 8 * bil
        m = _fbm(tex, X, Y, Z, base_o)
        d = (m - (1 - cov)) * 4 * bil + 0.35 - hf * 0.8
        e = _fbm(tex, X + 7, Y, Z - 3, fine_o)
        d = d - det * 0.5 * (1 - e)
        op = _fbm(tex, X * 0.15 + 40, Y * 0.15, Z * 0.15, ((1, 1, 0),))
        d = d * np.clip(0.3 + (op - 0.4) * 1.6, 0.1, 0.8)
        # Cumulus : bourrelets ronds qui moulent la masse.
        fq = 0.8 * (1 - 0.7 * kb)  # cumulus = grosses masses
        b = _fbm(tex, X * fq + 3, Y * fq * 1.4, Z * fq,
                 ((1, 0.65, 0), (2, 0.35, 9)))
        # Volutes : 0 = brume, 1 = cumulus à bords francs.
        puff = np.clip((b - 0.42) * (4 + 10 * kb), 0, 1)
        puff = puff * puff * (3 - 2 * puff)
        d = d * (1 - 0.9 * bil + 2.2 * bil * puff)
        cum = puff * np.clip(0.6 - hf, 0, 0.6) * 1.2
        d = d * (1 - kb) + kb * cum
        # Nappes proches de l'objectif, basses et légères.
        d = d + 0.6 * puff * np.exp(-pz / (0.3 * L)) * (hf < 0.35)
        d = d * (hf < 1) * (hf > -0.05)
        return np.clip(d, 0, 0.8)

    if sun is None:
        sx_, sy_ = -0.25, -0.45
    else:
        sx_, sy_ = sun[0] / 100.0 - 0.5, sun[1] / 100.0 - 0.5
    ld = np.array([sx_ * 1.5, 0.6 + max(0.0, -sy_), 0.3])
    ld /= np.linalg.norm(ld)
    steps = 48
    tk = np.geomspace(0.15, tmax, steps + 1).astype(np.float32)
    trans = np.ones((rh, rw), np.float32)
    light = np.zeros((rh, rw), np.float32)
    tw = np.zeros((rh, rw), np.float32)
    sigma = 1.6 + 2.0 * (1 - float(np.clip(soft, 0, 1)))
    rng = np.random.default_rng(5 + int(seed))
    jit = rng.random((rh, rw)).astype(np.float32)
    for i in range(steps):
        t = tk[i] + (tk[i + 1] - tk[i]) * jit
        dt = tk[i + 1] - tk[i]
        live = (t < ts) & (trans > 0.01)
        if not live.any():
            break
        px, py, pz = cx + dx * t, cy + dy * t, t
        d = dens(px, py, pz)
        d = np.where(live, d, 0)
        if not d.any():
            continue
        # Ombre : densité vers le soleil (2 prises).
        sh = 2 * dens(px + ld[0] * 0.08 * L, py + ld[1] * 0.08 * L,
                      pz + ld[2] * 0.08 * L) + dens(
            px + ld[0] * 1.2 * L, py + ld[1] * 1.2 * L,
            pz + ld[2] * 1.2 * L)
        hf = np.clip((py + 1.0) / T, 0, 1)
        lum = np.exp(-2.5 * sh) * 0.85 + 0.15 + 0.2 * hf
        # Arêtes : bords fins éclairés (rim), plus forts face au soleil.
        lum = lum + 0.45 * np.exp(-d * 9) * np.exp(-0.8 * sh)
        a = 1 - np.exp(-sigma * d * dt / L)
        light += trans * a * lum
        tw += trans * a * t
        trans *= 1 - a
    trans = cv2.GaussianBlur(trans, (0, 0), 1.2)  # lisse le grain
    light = cv2.GaussianBlur(light, (0, 0), 1.2)
    A = 1 - trans
    lum = light / np.maximum(A, 1e-4)
    tw = tw / np.maximum(A, 1e-4)  # profondeur moyenne de la brume
    # Couleurs de la scène.
    sm = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
    la = sm.mean(axis=2)
    pool = skym if skym.sum() > 0.02 * skym.size else np.ones_like(skym)
    lo = np.percentile(la[pool], 99.0)
    white = sm[pool & (la >= lo)].reshape(-1, 3).mean(0)
    white = white / max(1e-3, float(white.max())) * max(
        0.88, float(white.max()))
    sun_c = np.array([1.0, 1.0 - 0.02 * warmth, 1.0 - 0.08 * warmth])
    lit = np.clip(white * sun_c, 0, 1)
    sky = sm[pool].reshape(-1, 3).mean(0)
    tint = np.clip(sky / max(1e-3, float(sky.max())), 0.6, 1)
    cool = lit * 0.55 * tint ** 0.6
    t3 = np.clip(lum, 0, 1.1)[..., None]
    col = cool + (lit - cool) * t3
    fz = np.clip(np.log1p(tw) / np.log1p(40.0), 0, 1)[..., None]
    haze = 0.5 * (sky + lit)
    col = col * (1 - 0.7 * fz) + haze * 0.7 * fz
    gain = min(1.0, 1.2 * max(amount, 0.0)) * (
        1 - 0.7 * float(np.clip(visible, 0, 1)))
    A = A * gain
    acc = (col * A[..., None]).astype(np.float32)
    accf = cv2.resize(acc, (W, H), interpolation=cv2.INTER_CUBIC)
    af = cv2.resize(A.astype(np.float32), (W, H),
                    interpolation=cv2.INTER_CUBIC)[..., None]
    af = np.clip(af, 0, 1)
    return np.clip(img * (1 - af) + accf, 0, None)


def sea(img, far, layer=0.35, size=0.5, billow=0.5, detail=1.0,
        soft=0.1, amount=0.5, density=1.0, warmth=0.0, sun=None,
        res=960.0, seed=0, recul=0.0, visible=0.0, fov=60.0,
        fade=1.0, horizon=0.0, tilt=0.0, shift=(0.0, 0.0)):
    """Mer de nuages pleine vue d'en haut : couche posée sur le
    plan du sol jusqu'à layer (0 sol .. 1 œil), dessus en dômes, tours
    de cumulus qui en sortent par endroits. Marche de rayons par pixel
    en tranches de hauteur (« steep parallax ») : ce qui est plus
    proche que la nappe (mur, arbres, collines au-dessus) en sort.
    img float RGB 0..1, far 0..1. Retourne l'image, ou None (pas de
    sol trouvé). horizon/tilt (en % de la hauteur, 0 = auto) : ligne
    d'horizon placée à la main, le plan du sol la suit."""
    H, W = far.shape
    s = min(1.0, res / max(H, W))
    rh, rw = max(16, int(H * s)), max(16, int(W * s))
    f = cv2.resize(far.astype(np.float32), (rw, rh),
                   interpolation=cv2.INTER_AREA)
    skym = sky_mask(f)
    zsc = np.where(skym, 1e4, np.exp(f * math.log(80.0))).astype(
        np.float32)
    foc = 0.5 * rw / math.tan(math.radians(fov) / 2)
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    xn = (xx - rw / 2) / foc
    yn = -(yy - rh / 2) / foc
    land = ~skym
    if land.sum() < 50:
        return None
    # Plan du sol : enveloppe basse des points 3D de la scène.
    A = np.stack([(xn * zsc)[land], zsc[land],
                  np.ones(int(land.sum()))], 1)
    yv = (yn * zsc)[land]
    keep = np.ones(len(yv), bool)
    coef = np.array([0.0, 0.0, -1.0])
    for _ in range(4):
        coef = np.linalg.lstsq(A[keep], yv[keep], rcond=None)[0]
        keep = yv <= A @ coef
        if keep.sum() < 20:
            break
    # L'horizon du plan ne peut pas être sous la ligne de ciel (le
    # relief cache l'horizon, jamais l'inverse) : sinon pente forcée.
    top = skym[0]
    if top.sum() > 0.2 * rw:
        yb = float(np.median(np.argmax(~skym[:, top], axis=0)))
        if 0 < yb < 0.9 * rh and rh / 2 - coef[1] * foc > yb + 0.015 * rh:
            c1 = (rh / 2 - yb) / foc
            B = A[:, [0, 2]]
            yr = yv - c1 * A[:, 1]
            keep = np.ones(len(yr), bool)
            for _ in range(4):
                c02 = np.linalg.lstsq(B[keep], yr[keep], rcond=None)[0]
                keep = yr <= B @ c02
                if keep.sum() < 20:
                    break
            coef = np.array([c02[0], c1, c02[1]])
    # Vue de face, terrain plat : l'horizon est la ligne de ciel la plus
    # basse, pas bien au-dessus (sinon la mer est vue « d'en haut »).
    if top.sum() > 0.2 * rw:
        yb = float(np.percentile(np.argmax(~skym[:, top], axis=0), 90))
        if 0.5 * rh < yb < rh and rh / 2 - coef[1] * foc < yb - 0.1 * rh:
            c1 = (rh / 2 - yb) / foc
            yr = yv - c1 * A[:, 1]
            coef = np.array([0.0, c1, float(np.percentile(yr, 3))])
    if horizon > 0:
        # Horizon imposé : pente et recul du plan fixés, seule la
        # hauteur de l'œil reste à ajuster (enveloppe basse).
        c0 = -float(tilt) / 100 * rh / rw
        c1 = (rh / 2 - float(horizon) / 100 * rh) / foc
        yr = yv - c0 * A[:, 0] - c1 * A[:, 1]
        c2 = float(np.percentile(yr, 3))
        if c2 >= 0:  # rien sous l'horizon (contre-plongée)
            c2 = -max(1e-2, float(np.percentile(np.abs(yr), 90)))
        coef = np.array([c0, c1, c2])
    cam = float(-coef[2])  # hauteur de l'œil au-dessus du sol
    y_hz = rh / 2 - coef[1] * foc
    if y_hz > 0.6 * rh:
        # Vue de face (horizon bas) : pas de mer vue d'en haut, banc de
        # cumulus posé sur l'horizon, qui monte dans le ciel.
        return _face_volume(img, far, y_hz / rh, layer, size, billow,
                          detail, soft, amount, warmth, sun, seed, fade,
                          visible, shift)
    if cam <= 1e-3:
        return None
    mips, r0, N, fmin, fmax = _sea_texture(int(seed))
    # Hauteur 0 : pas de nappe ; elle monte et s'épaissit avec layer.
    th = cam * 0.9 * float(np.clip(layer, 0, 1)) ** 0.6
    if th <= 1e-4 * cam:
        return img.copy()
    gap = cam - th  # œil au-dessus de la nappe
    # Rayon des grosses volutes (monde) ; taille 0,5 .. 2.
    R = gap * (0.08 + 0.12 * float(np.clip(size, 0.5, 2.0)))
    tw = R * N / r0  # taille monde de la texture
    # Dômes ronds à 0,5 ; ni volute ni tour au-dessus de l'œil.
    # Nappe basse : dômes aplatis avec elle (apparition continue).
    amp = min(R * (0.5 + float(np.clip(billow, 0, 1))),
              0.95 * gap / fmax, 1.2 * th)
    ymax, ymin = th + amp * fmax, th + amp * fmin
    # Détail : 0 = dômes lissés, 1 = toutes les petites volutes.
    blur = 0.3 + 1.5 * (1 - float(np.clip(detail, 0, 1)))
    rng = np.random.default_rng(77 + int(seed))
    ou, ov = rng.uniform(0, N, 2)
    # Densité en long dégradé : vapeur qui déborde au-dessus des
    # dômes (hv), presque rien au ras du dessus, de plus en plus dense
    # en profondeur sans seuil ; la couche reste translucide vers son
    # sommet. Fondu des bords = longueur du dégradé. Indépendante de
    # la taille des volutes.
    sf = float(np.clip(soft, 0, 1))
    dd = min(amp, 0.14 * gap * (0.5 + float(np.clip(billow, 0, 1)))) * (
        1.5 + 2.0 * sf)
    # fade (Densité) : 1 = nappe pleine ; en baissant, dégradé plus
    # long et nuage plus léger, vaporeux.
    fl = 1.0 - float(np.clip(fade, 0, 1))
    fk = 4.0 ** fl
    dd = dd * fk
    hv = dd * (0.35 + 0.4 * sf)

    def rho(dep):
        x = np.maximum(dep + hv, 0) / (dd + hv)
        x = x * x
        return x / (1 + x)

    def surface(X, Z, lod, interp=cv2.INTER_LINEAR):
        """Hauteur du dessus de la nappe en (X, Z) monde."""
        u = ((X / tw * N + ou) % N).astype(np.float32)
        v = ((Z / tw * N + ov) % N).astype(np.float32)
        return th + amp * _by_lod(mips, u, v, lod + blur, interp)

    def lod_of(fp):
        return np.log2(np.maximum(fp / tw * N, 1e-6))

    # Rayon : hauteur au-dessus du sol cam + g z ; descend si g < 0.
    g = yn - coef[0] * xn - coef[1]
    rows = np.nonzero((g < -1e-5).any(axis=1))[0]
    zmax = 1e4
    # Horizon placé tout en bas : pas de mer vue d'en haut possible,
    # la brume diffuse prend le relais.
    if len(rows) < 0.15 * rh:
        return None
    r_a = int(rows[0])
    gs = np.minimum(g[r_a:], -1e-6)
    xs, zs = xn[r_a:], zsc[r_a:]
    mh = rh - r_a
    # Assez de tranches pour de grosses volutes, décalées par pixel :
    # plus de strates visibles.
    steps = 128
    jit = np.random.default_rng(5 + int(seed)).random(
        (mh, rw)).astype(np.float32) - 0.5
    dy = (ymax + hv - ymin) / (steps - 1)
    thick = np.zeros((mh, rw), np.float32)
    # Opacité de Beer-Lambert sur l'épaisseur pondérée par la densité.
    sig = 2.1 * max(amount, 0.0) * max(density, 0.0) / gap
    sig = sig * (1.0 - 0.6 * fl)
    # Lumière diffuse du volume (avant -> arrière, plus claire en haut)
    # et part d'opacité du premier dôme touché : un rayon qui ne fait
    # que frôler un dôme prend la lumière du volume, sans liseré.
    trans = np.ones((mh, rw), np.float32)
    lv = np.zeros((mh, rw), np.float32)
    front = np.zeros((mh, rw), np.float32)
    lf = 1.5 * R
    ylo, yhi = ymin, ymax + hv
    zhit = np.full((mh, rw), zmax, np.float32)
    hit = np.zeros((mh, rw), bool)
    zp = dp = None
    zlo = np.zeros((mh, rw), np.float32)
    zhi = np.zeros((mh, rw), np.float32)
    lgs = (-np.log2(-gs)).astype(np.float32)
    zw = np.zeros((mh, rw), np.float32)
    cw = np.zeros((mh, rw), np.float32)
    # Pas de fond de mer : les creux et le bas de la couche
    # s'effacent en douceur, seules les volutes entières restent.
    span = amp * (fmax - fmin)

    def crest(Sv):
        t = np.clip(((Sv - th - amp * fmin) / span - 0.05) / 0.3, 0, 1)
        return t * t * (3 - 2 * t)

    for y0 in np.linspace(ymax + hv, ymin, steps):
        y = y0 + jit * dy
        z = np.minimum((y - cam) / gs, zmax)
        # Détail à la taille du pixel ou du pas, sans log par pixel.
        fp = max((cam - y0) / foc, 0.2 * (ymax - ymin) / (steps - 1))
        S = surface(xs * z, z, lgs + math.log2(fp * N / tw))
        d = S - y
        if zp is not None:
            seg = np.maximum(z - zp, 1e-6)
            vis = np.clip((np.minimum(z, zs) - zp) / seg, 0, 1)
            bf = np.clip((y - ymin) / (0.25 * span), 0, 1)
            c = (rho(0.5 * (d + dp)) * crest(S) * bf * bf * vis
                 * seg).astype(np.float32)
            thick += c
            zw += c * z
            cw += c
            ex = np.exp(-sig * c)
            yc = 0.5 * (y + yp)
            lv += trans * (1 - ex) * (0.3 + 0.7 * (yc - ylo) / (yhi - ylo))
            trans *= ex
            zc = zp + seg * np.clip(-dp / (d - dp + 1e-9), 0, 1)
            new = ~hit & (d > 0) & (zc < zs)
            zhit = np.where(new, zc, zhit)
            zlo = np.where(new, zp, zlo)
            zhi = np.where(new, z, zhi)
            hit |= new
            front += np.where(hit & (z < zhit + lf), c, 0)
        zp, dp, yp = z, d, y
    # Point d'entrée affiné par dichotomie (pas de courbes de niveau
    # sur les grands flancs).
    for _ in range(5):
        zm = np.where(hit, 0.5 * (zlo + zhi), 1.0)
        inside = surface(xs * zm, zm, lod_of(zm / foc)) > cam + gs * zm
        zhi = np.where(hit & inside, zm, zhi)
        zlo = np.where(hit & ~inside, zm, zlo)
    zhit = np.where(hit, np.minimum(0.5 * (zlo + zhi), zs), zhit)
    # Sous la dernière tranche tout est nuage : la couche est pleine.
    rest = np.clip(zs - zp, 0, None)
    c = np.zeros_like(rest)  # pas de fond
    thick += c
    ex = np.exp(-sig * c)
    lv += trans * (1 - ex) * 0.3
    front += np.where(rest > 0, np.minimum(c, np.maximum(
        0, zhit + lf - zp) * c / np.maximum(rest, 1e-6)), 0)
    trans *= ex
    # Rayons qui frôlent les dômes : vapeur seule, à sa distance moyenne.
    vap = ~hit & (cw > 1e-6)
    zhit = np.where(vap, zw / np.maximum(cw, 1e-6), zhit)
    hit |= vap
    # Attributs au point touché, détail à la taille du pixel.
    lod = lod_of(zhit / foc)
    X0 = xs * zhit
    cub = cv2.INTER_CUBIC  # pas de facettes de près
    Sh = surface(X0, zhit, lod, cub)
    # Normale lissée (le nuage diffuse : forme large, pas de facettes) ;
    # le petit relief passe par les creux plus bas.
    ln = lod + 2.0
    e = np.maximum(0.25 * R, 4 * zhit / foc)
    nx = -(surface(X0 + e, zhit, ln, cub)
           - surface(X0 - e, zhit, ln, cub)) / (2 * e)
    nz = -(surface(X0, zhit + e, ln, cub)
           - surface(X0, zhit - e, ln, cub)) / (2 * e)
    nn = np.sqrt(nx * nx + nz * nz + 1)
    nx, ny, nz = nx / nn, 1 / nn, nz / nn
    # Soleil : position des Rayons, sinon haut et un peu à gauche.
    if sun is None:
        sx, sy = -0.25, -0.45
    else:
        sx, sy = sun[0] / 100.0 - 0.5, sun[1] / 100.0 - 0.5
    ld = np.array([sx * 2.0, 0.25 + 0.5 * max(0.0, -sy), 0.25])
    ld /= np.linalg.norm(ld)
    # Lumière enveloppante : le nuage diffuse, terminateur doux.
    dif = np.clip((nx * ld[0] + ny * ld[1] + nz * ld[2] + 0.25) / 1.25,
                  0, 1)
    # Ombre portée des volutes et des tours (pas vers le soleil).
    tau = np.zeros_like(Sh)
    for i in range(1, 9):
        t = i * 0.6 * R
        Ss = surface(X0 + ld[0] * t, zhit + ld[2] * t, lod + 1)
        tau += np.clip(Ss - (Sh + ld[1] * t), 0, None)
    shad = np.exp(-tau / (1.5 * amp))
    # Creux (plus bas que leur voisinage) et bases plus sombres.
    cav = np.clip(1 + 1.5 * (Sh - surface(X0, zhit, lod + 3)) / amp,
                  0.45, 1.1)
    hl = np.clip((Sh - th - amp * fmin) / (amp * (fmax - fmin)), 0, 1)
    lum = (0.18 + 0.3 * hl ** 0.7) * cav + 0.85 * dif ** 1.5 * shad
    # Rayons rasants : silhouettes fondues dans la vapeur.
    kf = 1 - np.exp(-front / (0.05 * fk * R))
    lum = lum * kf + (lv / np.maximum(1 - trans, 1e-4)) * (1 - kf)
    # Blanc du nuage = blanc réel de la scène (tons hauts, vrais
    # nuages de préférence), sans points lumineux ni spéculaires.
    sm = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
    k_op = max(5, rw // 30) | 1  # plus grand qu'un soleil ou un reflet
    la = cv2.morphologyEx(sm.mean(axis=2).astype(np.float32),
                          cv2.MORPH_OPEN, cv2.getStructuringElement(
                              cv2.MORPH_ELLIPSE, (k_op, k_op)))
    pool = skym if skym.sum() > 0.02 * skym.size else np.ones_like(skym)
    lo, up = np.percentile(la[pool], [98.0, 99.7])
    sel = pool & (la >= lo) & (la <= up)
    if sel.sum() < 10:
        sel = pool
    white = sm[sel].reshape(-1, 3).mean(0)
    if pool is skym and float(white.mean()) < 0.8 * float(
            np.percentile(la, 99.5)):
        # Ciel sombre : le blanc vient du reste de l'image.
        lo, up = np.percentile(la, [98.5, 99.7])
        white = sm[(la >= lo) & (la <= up)].reshape(-1, 3).mean(0)
    sun_c = np.array([1.0, 1.0 - 0.02 * warmth, 1.0 - 0.08 * warmth])
    lit = np.clip(white * sun_c, 0, 1)
    sky = sm[skym].mean(0) if skym.any() else sm[: max(
        1, rh // 4)].reshape(-1, 3).mean(0)
    tint = np.clip(sky / max(1e-3, float(sky.max())), 0.6, 1)
    cool = lit * 0.6 * tint ** 0.6
    t = np.clip(lum / 0.95, 0, 1)[..., None]
    col = cool + (lit - cool) * t
    # Perspective atmosphérique vers la couleur de l'horizon.
    y_hz = rh / 2 - coef[1] * foc
    ri = int(np.clip(y_hz, 0, rh - 1))
    hz = sm[max(0, ri - 2): ri + 3].reshape(-1, 3).mean(0)
    fog = (0.8 * (1 - np.exp(-zhit / (12 * gap))))[..., None]
    col = col * (1 - fog) + hz * fog
    # Bords et volutes fines vaporeux, couche épaisse quasi opaque.
    a = 1 - trans
    a *= 1 - 0.7 * float(np.clip(visible, 0, 1))
    if recul > 0:
        # Éloignement : la mer s'efface devant, reste au fond.
        fh = np.clip(np.log(np.maximum(zhit, 1)) / math.log(80.0), 0, 1)
        e = 1.3 + max(0.0, recul - 1.0) * 3.0
        k = min(1.0, recul)
        a *= (1 - k) + k * fh ** e
    a = np.where(hit, a, 0).astype(np.float32)
    # Vapeur fine : lumière diffusée, peu de modelé.
    va = np.sqrt(a)[..., None]
    col = col * va + (0.85 * lit * (1 - fog) + hz * fog) * (1 - va)

    def full(x):
        p = np.zeros((rh,) + x.shape[1:], np.float32)
        p[r_a:] = x
        return cv2.resize(p, (W, H), interpolation=cv2.INTER_LINEAR)
    af = full(a)
    colf = full(col.astype(np.float32))
    # Bords nets des objets proches : profondeur pleine résolution.
    zf = full(np.where(hit, zhit, 0)) / np.maximum(
        full(hit.astype(np.float32)), 1e-3)
    zsf = np.exp(far.astype(np.float32) * np.float32(math.log(80.0)))
    zsf[sky_mask(far)] = 1e4
    occ = np.clip((zsf - zf) / (0.08 * zf + 1e-3) + 0.5, 0, 1)
    af = np.clip(af * occ, 0, 1)[..., None]
    del zf, zsf, occ
    # Derrière un voile mince la scène reste visible, mais diffuse
    # (flou calculé en petit : rapide en pleine résolution).
    k = 8 if W > 1600 else 1
    back = cv2.resize(img, (max(1, W // k), max(1, H // k)),
                      interpolation=cv2.INTER_AREA)
    back = cv2.GaussianBlur(back, (0, 0), max(1.0, W / 400 / k))
    back = cv2.resize(back, (W, H), interpolation=cv2.INTER_LINEAR)
    back -= img
    back *= np.clip(af * 2.5, 0, 1)
    back += img
    # back * (1 - af) + colf * af
    colf -= back
    colf *= af
    colf += back
    return colf
