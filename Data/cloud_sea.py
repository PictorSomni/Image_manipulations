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


def sea(img, far, layer=0.35, size=0.5, billow=0.5, detail=1.0,
        soft=0.1, amount=0.5, density=1.0, warmth=0.0, sun=None,
        res=960.0, seed=0, recul=0.0, visible=0.0, fov=60.0):
    """Mer de nuages pleine vue d'en haut : couche opaque posée sur le
    plan du sol jusqu'à layer (0 sol .. 1 œil), dessus en dômes, tours
    de cumulus qui en sortent par endroits. Marche de rayons par pixel
    en tranches de hauteur (« steep parallax ») : ce qui est plus
    proche que la nappe (mur, arbres, collines au-dessus) en sort.
    img float RGB 0..1, far 0..1. Retourne l'image, ou None (pas de
    sol trouvé)."""
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
    cam = float(-coef[2])  # hauteur de l'œil au-dessus du sol
    if cam <= 1e-3:
        return None
    mips, r0, N, fmin, fmax = _sea_texture(int(seed))
    th = cam * (0.1 + 0.8 * float(np.clip(layer, 0, 1)) ** 0.6)
    gap = cam - th  # œil au-dessus de la nappe
    # Rayon des grosses volutes (monde) ; taille 0,5 .. 2.
    R = gap * (0.08 + 0.12 * float(np.clip(size, 0.5, 2.0)))
    tw = R * N / r0  # taille monde de la texture
    # Dômes ronds à 0,5 ; ni volute ni tour au-dessus de l'œil.
    amp = min(R * (0.5 + float(np.clip(billow, 0, 1))),
              0.95 * gap / fmax)
    ymax, ymin = th + amp * fmax, th + amp * fmin
    # Détail : 0 = dômes lissés, 1 = toutes les petites volutes.
    blur = 0.3 + 1.5 * (1 - float(np.clip(detail, 0, 1)))
    rng = np.random.default_rng(77 + int(seed))
    ou, ov = rng.uniform(0, N, 2)

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
    if not len(rows):
        return None
    r_a = int(rows[0])
    gs = np.minimum(g[r_a:], -1e-6)
    xs, zs = xn[r_a:], zsc[r_a:]
    mh = rh - r_a
    steps = 64
    thick = np.zeros((mh, rw), np.float32)
    zhit = np.full((mh, rw), zmax, np.float32)
    hit = np.zeros((mh, rw), bool)
    zp = dp = None
    zlo = np.zeros((mh, rw), np.float32)
    zhi = np.zeros((mh, rw), np.float32)
    lgs = (-np.log2(-gs)).astype(np.float32)
    for y in np.linspace(ymax, ymin, steps):
        z = np.minimum((y - cam) / gs, zmax)
        # Détail à la taille du pixel ou du pas, sans log par pixel.
        fp = max((cam - y) / foc, 0.2 * (ymax - ymin) / (steps - 1))
        S = surface(xs * z, z, lgs + math.log2(fp * N / tw))
        d = S - y
        if zp is not None:
            seg = np.maximum(z - zp, 1e-6)
            vis = np.clip((np.minimum(z, zs) - zp) / seg, 0, 1)
            fin = np.where(d > 0, np.where(dp > 0, 1.0, d / (d - dp)),
                           np.where(dp > 0, dp / (dp - d), 0.0))
            thick += (fin * vis * seg).astype(np.float32)
            zc = zp + seg * np.clip(-dp / (d - dp + 1e-9), 0, 1)
            new = ~hit & (d > 0) & (zc < zs)
            zhit = np.where(new, zc, zhit)
            zlo = np.where(new, zp, zlo)
            zhi = np.where(new, z, zhi)
            hit |= new
        zp, dp = z, d
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
    thick += rest
    new = ~hit & (rest > 0)
    zhit = np.where(new, zp, zhit)
    hit |= new
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
    # Couleurs de la photo : tons les plus clairs = soleil, ombre
    # froide tirée du ciel.
    sm = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
    la = sm.mean(axis=2)
    hi = sm[la >= np.percentile(la, 98)].mean(0)
    hi = hi / max(1e-3, float(hi.max()))
    sun_c = np.array([1.0, 0.97 + 0.02 * warmth, 0.93 - 0.08 * warmth])
    lit = np.clip(0.55 * hi + 0.45, 0, 1) * sun_c
    sky = sm[: max(1, rh // 4)].reshape(-1, 3).mean(0)
    cool = np.array([0.80, 0.86, 0.96]) * (0.7 + 0.3 * sky / max(
        1e-3, float(sky.max())))
    t = np.clip(lum / 0.95, 0, 1.05)[..., None]
    col = cool * 0.5 + (lit - cool * 0.5) * t
    # Perspective atmosphérique vers la couleur de l'horizon.
    y_hz = rh / 2 - coef[1] * foc
    ri = int(np.clip(y_hz, 0, rh - 1))
    hz = sm[max(0, ri - 2): ri + 3].reshape(-1, 3).mean(0)
    fog = (0.8 * (1 - np.exp(-zhit / (12 * gap))))[..., None]
    col = col * (1 - fog) + hz * fog
    # Opacité : épaisseur traversée (bords des tours plus fins), plafond.
    lam = R * (0.03 + 0.6 * float(np.clip(soft, 0, 1)))
    a = 1 - np.exp(-thick / lam)
    a *= (1 - math.exp(-6.0 * max(amount, 0.0) * density))
    a *= 1 - 0.7 * float(np.clip(visible, 0, 1))
    if recul > 0:
        # Éloignement : la mer s'efface devant, reste au fond.
        fh = np.clip(np.log(np.maximum(zhit, 1)) / math.log(80.0), 0, 1)
        e = 1.3 + max(0.0, recul - 1.0) * 3.0
        dd = min(1.0, recul)
        a *= (1 - dd) + dd * fh ** e
    a = np.where(hit, a, 0).astype(np.float32)

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
