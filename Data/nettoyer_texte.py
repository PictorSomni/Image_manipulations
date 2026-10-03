"""Nettoyage d'un texte copié d'un PDF/mise en page IA avant de le coller
dans Affinity : espaces exotiques, caractères invisibles, lettres sosies
(cyrillique/grec), ligatures, guillemets/tirets hétérogènes.

clean(text) -> (texte_propre, nb_corrections). Utilisé par l'action
« Nettoyer texte » du Hub (PDF sélectionné ou presse-papiers -> presse-papiers).
"""

__version__ = "2.3.27"

import difflib
import re
import unicodedata

# Invisibles : largeur zéro, joiners, BOM, trait d'union conditionnel…
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"
                                    "᠎⁡⁢⁣⁤"))
# Espaces exotiques -> espace normale (insécables recalculées plus bas).
_SPACES = dict.fromkeys(map(ord, "      "
                                 "      "
                                 "  　 "), " ")
# Lettres sosies -> latin (seulement dans un mot qui contient du latin).
_HOMO = str.maketrans("АВЕКМНОРСТХаеорсухіјѕԁԛԝΑΒΕΖΗΙΚΜΝΟΡΤΥΧονϲ",
                      "ABEKMHOPCTXaeopcyxijsdqwABEZHIKMNOPTYXovc")
_PUNCT = str.maketrans({"‘": "’", "‛": "’", "′": "’", "`": "’",
                        "‟": "“", "″": "“",
                        "‐": "-", "‑": "-", "‒": "–", "―": "—", "−": "-"})
_LATIN = re.compile(r"[A-Za-zÀ-ÿ]")
_WORD = re.compile(r"\w+")


def _fix_word(m):
    w = m.group(0)
    return w.translate(_HOMO) if _LATIN.search(w) else w


def clean(text):
    before = text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_INVISIBLE).translate(_SPACES).translate(_PUNCT)
    # Ligatures (ﬁ ﬂ…) et caractères pleine chasse issus des PDF.
    text = "".join(unicodedata.normalize("NFKC", c)
                   if "ﬀ" <= c <= "ﬆ" or "！" <= c <= "～"
                   else c for c in text)
    text = "".join(c for c in text
                   if c in "\n\t" or unicodedata.category(c) != "Cc")
    text = _WORD.sub(_fix_word, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    # Typo française : insécable avant ; : ! ? » et après «.
    text = re.sub(r" ?([;:!?»])", lambda m: " " + m.group(1)
                  if m.group(0).startswith(" ") or m.group(1) in "»"
                  else m.group(0), text)
    text = re.sub(r"« ?", "« ", text)
    # Espace oubliée : « là? » -> « là ? » (pas « : », heures/URL).
    text = re.sub(r"(?<=\w)([;!?])", " \\1", text)
    text = re.sub(r"\n +", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n ") + (
        "\n" if before.endswith(("\n", "\r")) else "")
    ops = difflib.SequenceMatcher(None, before, text, autojunk=False)
    changed = sum(tag != "equal" for tag, *_ in ops.get_opcodes())
    return text, changed


if __name__ == "__main__":
    t, n = clean("Bonjour​ le monde ! ﬁn  test : « ок »"
                 " Сafé ‑ l‘été\r\n")
    assert t == "Bonjour le monde ! fin test : « ок »" \
        " Cafe - l’été\n".replace("Cafe", "Café"), repr(t)
    assert clean("Москва")[0] == "Москва"  # vrai cyrillique intact
    assert clean("Prix: 5€")[0] == "Prix: 5€"  # pas d'espace ajoutée
    assert clean("bien là? Oui!")[0] == "bien là ? Oui !"
    assert n > 0 and clean("ok")[1] == 0
    print("ok")
