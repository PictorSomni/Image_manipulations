"""Mer de nuages en perspective, rendue comme un champ de hauteur.

Le dessus de la nappe est un champ de hauteur fait de demi-sphères
empilées à plusieurs échelles (cumulus « chou-fleur ») posé sur un plan
horizontal. Rendu par marche de rayons colonne par colonne, de l'avant
vers le fond (algorithme « voxel space ») : perspective, occlusion et
taille des volutes justes sans 3D lourde.

Éclairage d'après Schneider (Nubis, Horizon Zero Dawn) et Hillaire
(Frostbite 2016) : ombres portées sur le champ de hauteur
(Beer-Lambert), occlusion des creux, Beer-Powder, phase à deux lobes
(liseré en contre-jour), perspective atmosphérique.
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


def _wgrad(a):
    """Gradients (x, y) d'une texture qui se répète."""
    return ((np.roll(a, -1, 1) - np.roll(a, 1, 1)) * 0.5,
            (np.roll(a, -1, 0) - np.roll(a, 1, 0)) * 0.5)


def _domes(n, r, rng, fill=0.9):
    """Union de demi-sphères (rayon ~r px) sur une texture n x n qui se
    répète ; hauteur en unités de rayon."""
    count = max(4, int(fill * n * n / (r * r)))
    pts = rng.random((count, 2)) * n
    rad = r * rng.uniform(0.6, 1.4, count)
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


def _shadow_tex(hl, ldir, amp, steps=24):
    """Ombre portée du champ de hauteur vers le soleil (Beer-Lambert sur
    l'épaisseur traversée). ldir = (dx, dz, dy) dans l'espace texture,
    en px de texture par unité de hauteur."""
    tau = np.zeros_like(hl)
    for k in range(1, steps + 1):
        t = k * 3.0
        M = np.float32([[1, 0, -ldir[0] * t], [0, 1, ldir[1] * t]])
        hs = cv2.warpAffine(hl, M, hl.shape[::-1], flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_WRAP)
        ray = hl + ldir[2] * t
        tau += np.clip(hs - ray, 0, None)
    return np.exp(-tau * 0.6).astype(np.float32)


def sky_mask(far):
    """Ciel : plateau plat de la carte d'éloignement relié au haut du
    cadre (sa valeur varie d'une photo à l'autre)."""
    top = far[: max(1, far.shape[0] // 20)]
    v = float(np.median(top))
    if v < 0.5 or float(top.std()) > 0.03:
        return far >= 0.97
    return far >= v - 0.02


def render(img, far, layer=0.4, size=0.5, billow=0.6, detail=1.0,
           soft=0.2, density=1.0, warmth=0.0, sun=None, res=800.0,
           seed=0, fov=60.0, waves=1.0, follow=1.0, strength=1.0):
    """img float RGB 0..1, far 0..1 (carte d'éloignement). layer :
    hauteur du dessus de la nappe, 0 au sol .. 1 au niveau de l'œil.
    Retourne l'image composée, ou None si la nappe est au-dessus de
    l'œil (brume unie, gérée ailleurs)."""
    H, W = far.shape
    s = min(1.0, res / max(H, W))
    rh, rw = max(16, int(H * s)), max(16, int(W * s))
    f = cv2.resize(far.astype(np.float32), (rw, rh),
                   interpolation=cv2.INTER_AREA)
    zsc = np.exp(f * math.log(80.0))
    skym = sky_mask(f)
    zsc = np.where(skym, 1e4, zsc)
    foc = 0.5 * rw / math.tan(math.radians(fov) / 2)
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    X = (xx - rw / 2) / foc * zsc
    Y = -(yy - rh / 2) / foc * zsc
    land = ~skym
    if land.sum() < 50:
        return None
    A = np.stack([X[land], zsc[land], np.ones(int(land.sum()))], 1)
    yv = Y[land]
    keep = np.ones(len(yv), bool)
    coef = np.array([0.0, 0.0, -1.0])
    for _ in range(4):
        coef = np.linalg.lstsq(A[keep], yv[keep], rcond=None)[0]
        keep = yv <= A @ coef
        if keep.sum() < 20:
            break
    cam = -coef[2]  # hauteur de l'œil au-dessus du sol (plan)
    if cam <= 1e-3:
        return None
    # Hauteur progressive : le bas du slider garde la brume au sol.
    layer = float(np.clip(layer, 0, 1)) ** 3
    # Dessus de la nappe : layer 0 = sol, 1 = œil.
    base = coef[2] + cam * float(np.clip(layer, 0, 0.97))
    dh = -base  # œil au-dessus de la nappe
    th = cam * float(np.clip(layer, 0, 0.97))  # nappe au-dessus du sol
    levels, r0, n = _texture(int(seed), float(detail))
    # Taille des volutes (rayon de la plus grosse) en unités monde.
    R = cam * (0.05 + 0.7 * size ** 1.5)
    # Hauteur des tours, jamais au-dessus de l'œil.
    amp = min(R * 1.2, 0.7 * dh) * (0.25 + 0.75 * billow)
    tw = R * n / r0  # taille monde de la texture
    # Soleil : position des Rayons (% du cadre) sinon haut à gauche,
    # derrière les nuages.
    if sun is None:
        sx, sy = -0.3, -0.25
    else:
        sx, sy = sun[0] / 100.0 - 0.5, sun[1] / 100.0 - 0.5
    lv = np.array([sx * 2 * math.tan(math.radians(fov) / 2) * rw / rh,
                   max(0.15, -sy * 2 * math.tan(math.radians(fov) / 2))
                   + 0.25, 1.0])
    lv /= np.linalg.norm(lv)
    # Ombres portées pré-calculées en espace texture, niveau 1.
    lh = math.hypot(lv[0], lv[2]) + 1e-6
    ldir = (lv[0] / lh, lv[2] / lh, lv[1] / lh * tw / n / amp)
    shadow = _shadow_tex(levels[1], ldir, 1.0)
    shadows = [_wblur(shadow, 2 ** i * 0.5) if i else shadow
               for i in range(len(levels))]
    grads = [_wgrad(lv_) for lv_ in levels]
    gx_l = [g[0] for g in grads]
    gy_l = [g[1] for g in grads]

    acc = np.zeros((rh, rw), np.float32)
    att = {k: np.zeros((rh, rw), np.float32)
           for k in ("z", "h", "gx", "gz", "sh", "edge")}
    y_hz = rh / 2 - coef[1] * foc
    zmin = max(0.05, dh * foc / max(1.0, rh - y_hz + amp / dh * foc) * 0.5)
    zs = np.geomspace(zmin, 600.0, 420)
    cols = np.arange(rw, dtype=np.float32)
    rows = np.arange(rh, dtype=np.float32)[:, None]
    soft_px = 0.8 + 3.0 * soft
    ratio = zs[1] / zs[0]
    kpen = 6.0 * max(density * strength, 0.02)
    sig = (0.3 + 2.0 * density ** 2) / R
    wmu = float(levels[-1].mean())
    wsd = float(levels[-1].std()) + 1e-4
    sig = density * 6.0 / R
    # Relief de la scène vu de dessus (tranche x colonne) : hauteur des
    # objets au-dessus du plan du sol. La nappe monte contre les arbres
    # et les murets, se creuse dans les vallées.
    hp = Y - (coef[0] * X + coef[1] * zsc + coef[2])
    idx = np.clip(np.searchsorted(zs, zsc), 0, len(zs) - 1)
    ok = ~skym
    G = np.full((len(zs), rw), -1e9, np.float32)
    np.maximum.at(G, (idx[ok], np.broadcast_to(cols, (rh, rw))[ok]
                      .astype(int)), hp[ok].astype(np.float32))
    Wt = (G > -1e8).astype(np.float32)
    G = np.where(Wt > 0, np.clip(G, -cam, 3 * cam), 0).astype(np.float32)
    sgx = max(2.0, rw / 30)
    num = cv2.GaussianBlur(G * Wt, (0, 0), sgx, sigmaY=8)
    den = cv2.GaussianBlur(Wt, (0, 0), sgx, sigmaY=8)
    G = num / np.maximum(den, 1e-3) * np.clip(den * 4, 0, 1)
    for i, z in enumerate(zs):
        Xw = (cols - rw / 2) / foc * z
        # Mip : taille d'un pixel écran en pixels de texture.
        fp = max(z / foc, 0.35 * z * (ratio - 1)) / tw * n
        lvl = int(np.clip(math.log2(max(fp, 1e-6)) + 1, 0, len(levels) - 1))
        uu = Xw / tw * n
        vv = np.full_like(uu, z / tw * n + 0.5 * n)
        u, v = uu % n, vv % n
        mx, my = u[None, :].astype(np.float32), v[None, :].astype(np.float32)

        def samp(t):
            return cv2.remap(t, mx, my, cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_WRAP)[0]
        hgt = samp(levels[lvl])
        # Détail fin au premier plan : la texture répétée 7x plus petite.
        fd = fp * 7.3 * 2
        if fd < 4:
            ld = int(np.clip(math.log2(max(fd, 1e-6)) + 1, 0,
                             len(levels) - 1))
            dmx, dmy = (uu[None] * 7.3) % n, (vv[None] * 7.3) % n
            det = cv2.remap(levels[ld], dmx.astype(np.float32),
                            dmy.astype(np.float32), cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_WRAP)[0]
            hgt = hgt + 0.12 * (det - 0.4) * min(1.0, (4 - fd) / 2) \
                * np.clip(hgt * 3, 0, 1)
        # Houle à grande échelle (deux octaves bien plus larges que les
        # volutes) : bancs hauts aux grosses tours, creux plus bas et
        # plus calmes ; la nappe n'est plus un plan.
        wv = 0.0
        for k, wt in ((5.3, 0.65), (2.1, 0.35)):
            wm = cv2.remap(levels[-1],
                           ((uu[None] / k) % n).astype(np.float32),
                           ((vv[None] / k + 97 * k) % n).astype(np.float32),
                           cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)[0]
            wv = wv + wt * (wm - wmu) / wsd
        wv = np.clip(wv, -2.5, 2.5)
        loc = amp * np.clip(1 + 0.7 * waves * wv, 0.2, 2.6)
        # Plan du sol complet : pente avant-arrière et latérale (roulis).
        top_w = coef[0] * Xw + coef[1] * z + base + loc * (hgt - 0.15) \
            + waves * 1.4 * amp * wv
        # Suit le relief, sans dépasser le haut des obstacles.
        # Obstacle plus bas que la nappe : elle passe dessus en suivant
        # vaguement sa forme ; plus haut : elle le contourne, monte à
        # peine contre lui.
        gp = np.maximum(G[i], 0)
        top_w = top_w + follow * (0.8 * np.clip(G[i], -2 * R, 0)
                                  + 0.35 * np.minimum(gp, th))
        top_w = np.minimum(top_w, coef[0] * Xw + coef[1] * z
                           + coef[2] + 0.92 * cam)
        ytop = rh / 2 - foc * top_w / z
        y0 = int(max(0, math.floor(ytop.min() - 3 * foc * dh / z)))
        if y0 >= rh:
            continue
        sl = slice(y0, rh)
        sp = max(soft_px, 1.5 * foc * dh / z * (1 - 1 / ratio))
        a = np.clip((rows[sl] - ytop[None, :]) / sp + 0.5, 0, 1)
        # Translucidité : chaque tranche ne bouche qu'une partie de la
        # vue (Beer-Lambert sur son épaisseur), le fond transparaît
        # à travers les sommets minces.
        a = a * (1 - math.exp(-sig * z * (ratio - 1)))
        # Épaisseur : le rayon qui frôle le sommet ne traverse que peu
        # de nuage, il ne s'opacifie qu'en s'enfonçant sous la crête.
        pen = np.maximum(rows[sl] - ytop[None, :], 0) * (z / foc / amp)
        a = a * (1 - np.exp(-kpen * pen))
        free = (1 - acc[sl]) * a
        if not free.any():
            continue
        vals = {"z": z, "h": hgt, "gx": samp(gx_l[lvl]),
                "gz": samp(gy_l[lvl]), "sh": samp(shadows[lvl]),
                "edge": np.clip((rows[sl] - ytop[None, :]) /
                                (soft_px * 6 + foc * amp * 0.3 / z), 0, 1)}
        for k, val in vals.items():
            vv = val if np.ndim(val) == 2 else (
                val[None, :] if np.ndim(val) else val)
            att[k][sl] += free * vv
        acc[sl] += free
    m = np.maximum(acc, 1e-4)
    for k in att:
        att[k] = att[k] / m
    # Flancs des volutes (sous le sommet) : sans ça chaque colonne
    # recopie la normale du sommet en traînée verticale ; on les lisse
    # et on les tourne vers l'œil.
    e = att["edge"]
    for k in ("gx", "gz", "h", "sh"):
        sm = cv2.GaussianBlur(att[k], (0, 0), 6, sigmaY=2)
        att[k] = att[k] + (sm - att[k]) * e * e
    att["gz"] = att["gz"] + 0.15 * e * e
    # Couleurs : ciel de la photo pour l'ambiant, soleil chaud.
    sky = img[: max(1, H // 4)].reshape(-1, 3).mean(0)
    sky = np.clip(sky / max(1e-3, sky.max()), 0.3, 1.0)
    sun_c = np.array([1.0, 0.96 + 0.02 * warmth, 0.9 - 0.08 * warmth],
                     np.float32)
    amb = (0.5 * sky + 0.3).astype(np.float32)
    # Normale du champ de hauteur (y vers le haut).
    gs = amp / tw * n
    nx, nz = -att["gx"] * gs, -att["gz"] * gs
    nn = np.sqrt(nx * nx + nz * nz + 1)
    nx, ny, nz = nx / nn, 1 / nn, nz / nn
    ndl = nx * lv[0] + ny * lv[1] - nz * lv[2]
    diff = np.clip(ndl * 0.75 + 0.25, 0, 1) ** 1.5
    sh = att["sh"] ** 1.5
    ao = 0.45 + 0.55 * np.clip(att["h"] / 0.9, 0, 1) ** 0.8
    # Beer-Powder : bord fin (edge bas) plus sombre face à la lumière,
    # liseré clair en contre-jour (phase à deux lobes, Hillaire).
    e = att["edge"]
    powder = 1 - np.exp(-6 * e)
    back = max(0.0, -lv[2])
    rim = (1 - e) * back * 0.8
    lit = diff * sh * (0.6 + 0.4 * powder) + rim
    # Diffusion multiple : l'ombre d'un nuage reste claire et bleutée.
    shade = np.clip(0.22 + 0.85 * lit, 0, 1.3) * (0.75 + 0.25 * ao)
    col = amb[None, None, :] * (1 - np.clip(shade, 0, 1))[..., None] \
        + sun_c[None, None, :] * shade[..., None]
    col = col * 0.97
    # Perspective atmosphérique : le lointain se fond dans le ciel.
    hz = img[int(np.clip(y_hz / s, 0, H - 1))].mean(0) if 0 < y_hz < rh \
        else sky
    fog = 1 - np.exp(-att["z"] / (dh * 25))
    col = col * (1 - fog[..., None] * 0.8) + hz * fog[..., None] * 0.8
    # Le nuage ne passe que devant ce qui est plus loin que lui.
    occ = np.clip((zsc - att["z"]) / (0.1 * att["z"] + 1e-3) + 0.5, 0, 1)
    # Sommets minces translucides : la scène transparaît sous le voile.
    thin = 0.45 + 0.55 * np.clip(att["edge"] * 1.5, 0, 1) ** 0.7
    # Près de l'œil on est dans le voile : diffus, jamais un mur
    # opaque ; il s'épaissit avec la distance.
    near = 1 - np.exp(-att["z"] / (6 * dh))
    alpha = np.clip(acc * occ * thin * near, 0, 0.92).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.6)
    up = (lambda a: cv2.resize(a, (W, H), interpolation=cv2.INTER_LINEAR))
    col = up(col.astype(np.float32))
    alpha = up(alpha)
    # Ce qui dépasse la nappe en sort : le voile de profondeur ne
    # s'y pose pas non plus (pas de brume autour du drapeau).
    # Hauteur de brume jusqu'à 3x l'œil : au-delà de l'œil la nappe
    # n'est plus vue de dessus, seul le voile recouvre l'obstacle.
    tu = cam * 3.0 * float(np.clip(layer, 0, 1))
    under = np.clip((tu - hp) / (0.3 * tu + 1e-6), 0, 1)
    under = np.where(skym, 0, under * under * (3 - 2 * under))
    under = cv2.GaussianBlur(under.astype(np.float32), (0, 0), 1.5)
    # Derrière un voile mince la scène reste visible, mais diffuse.
    back = cv2.GaussianBlur(img, (0, 0), max(1.0, W / 400))
    k = np.clip(alpha * 2.5, 0, 1)[..., None]
    back = img + (back - img) * k
    return (back * (1 - alpha[..., None]) + col * alpha[..., None],
            up(under))
