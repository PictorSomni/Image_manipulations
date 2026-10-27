"""Notifications Web Push (RFC 8030/8291/8292) sans dépendance en plus.

Clé VAPID dans ~/.claude_web_vapid.pem, abonnements des appareils dans
~/.claude_web_push.json. Seul `cryptography` (déjà présent) est utilisé.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_FILE = os.path.expanduser("~/.claude_web_vapid.pem")
SUBS_FILE = os.path.expanduser("~/.claude_web_push.json")
CONTACT = "https://pictorsomni.taild63b02.ts.net"


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _point(key):
    return key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)


def _vapid_key():
    try:
        with open(KEY_FILE, "rb") as f:
            return serialization.load_pem_private_key(f.read(), None)
    except FileNotFoundError:
        key = ec.generate_private_key(ec.SECP256R1())
        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
        os.chmod(KEY_FILE, 0o600)
        return key


def public_key():
    return _b64(_point(_vapid_key()))


def _hkdf(salt, ikm, info, n):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def encrypt(payload, p256dh, auth, salt=None, server_key=None):
    """Chiffrement aes128gcm d'un message pour un abonnement (RFC 8291)."""
    ua_pub = _unb64(p256dh)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_pub = _point(server_key)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey
                                 .from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(_unb64(auth), shared,
                b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([65]) + as_pub + body


def _jwt(endpoint):
    url = urllib.parse.urlsplit(endpoint)
    head = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = _b64(json.dumps({"aud": f"{url.scheme}://{url.netloc}",
                              "exp": int(time.time()) + 12 * 3600,
                              "sub": CONTACT}).encode())
    signing = f"{head}.{claims}".encode()
    r, s = decode_dss_signature(_vapid_key().sign(
        signing, ec.ECDSA(hashes.SHA256())))
    return f"{head}.{claims}." + _b64(r.to_bytes(32, "big")
                                     + s.to_bytes(32, "big"))


def _subs():
    try:
        with open(SUBS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(subs):
    with open(SUBS_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(subs, f)
    os.chmod(SUBS_FILE + ".tmp", 0o600)
    os.replace(SUBS_FILE + ".tmp", SUBS_FILE)


def subscribe(sub):
    subs = [s for s in _subs() if s["endpoint"] != sub["endpoint"]]
    _save(subs + [{"endpoint": sub["endpoint"], "keys": sub["keys"]}])


def send(title, body):
    """Envoie à tous les appareils abonnés ; oublie les abonnements morts."""
    payload = json.dumps({"title": title, "body": body[:300]}).encode()
    subs, dead = _subs(), []
    for s in subs:
        req = urllib.request.Request(
            s["endpoint"], method="POST",
            data=encrypt(payload, s["keys"]["p256dh"], s["keys"]["auth"]),
            headers={"TTL": "3600", "Urgency": "high",
                     "Content-Encoding": "aes128gcm",
                     "Content-Type": "application/octet-stream",
                     "Authorization": f"vapid t={_jwt(s['endpoint'])}, "
                                      f"k={public_key()}"})
        try:
            urllib.request.urlopen(req, timeout=15).close()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                dead.append(s)
            print(f"[Push] {exc.code} {exc.read()[:200]}", flush=True)
        except OSError as exc:
            print(f"[Push] {exc}", flush=True)
    if dead:
        _save([s for s in subs if s not in dead])


if __name__ == "__main__":
    # Aller-retour : on déchiffre comme le ferait le navigateur.
    ua = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    msg = encrypt(b"bonjour", _b64(_point(ua)), _b64(auth))
    salt, as_pub, ct = msg[:16], msg[21:86], msg[86:]
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey
                         .from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + _point(ua) + as_pub, 32)
    pt = AESGCM(_hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
                ).decrypt(_hkdf(salt, ikm, b"Content-Encoding: nonce\x00",
                                12), ct, None)
    assert pt == b"bonjour\x02", pt
    assert len(_jwt("https://web.push.apple.com/x").split(".")) == 3
    print("ok")
