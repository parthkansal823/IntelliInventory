"""Voice / quick-type billing: turn "दो किलो आटा और एक मैगी" or "2 atta 1 maggi" into bill lines.

Works fully offline: Devanagari is transliterated to Roman, Hindi/English number words become quantities, common
Hindi shop words map to catalogue words (cheeni -> sugar, sabun -> soap ...), then products are fuzzy-matched with
rapidfuzz. The browser's speech recognition (free, built into Chrome/Android) only supplies the text.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process  # noqa: F401
from sqlmodel import Session, select

from app.models import Category, Product

MIN_SCORE = 75

# --- Devanagari -> Roman (simple, good enough for fuzzy matching) -------------------------------------------

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri",
}  # fmt: skip
_MATRAS = {"ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri"}
_MARKS = {"ं": "n", "ँ": "n", "ः": "h", "़": "", "्": ""}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}  # fmt: skip
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def transliterate(text: str) -> str:
    out: list[str] = []
    chars = list(text.translate(_DIGITS))
    for i, ch in enumerate(chars):
        if ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            after = chars[i + 2] if i + 2 < len(chars) else ""
            if nxt == "़":  # nukta: look past it
                nxt = after
            # inherent "a" unless a matra/virama follows or the word ends here (Hindi drops the final schwa)
            if nxt not in _MATRAS and nxt not in ("्",) and nxt in _CONSONANTS | _MARKS | _VOWELS:
                if nxt not in _MARKS or nxt in ("ं", "ँ"):
                    out.append("a")
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _MATRAS:
            out.append(_MATRAS[ch])
        elif ch in _MARKS:
            out.append(_MARKS[ch])
        else:
            out.append(ch)
    return "".join(out)


def skeleton(word: str) -> str:
    """Spelling-insensitive key: cheeni / chini / चीनी -> chini, aata / atta / आटा -> ata."""
    w = word.lower().replace("ee", "i").replace("oo", "u").replace("w", "v").replace("ph", "f").replace("z", "j")
    return re.sub(r"(.)\1+", r"\1", w)


# --- words -----------------------------------------------------------------------------------------------------

NUMBERS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "tin": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
    "panch": 5, "paanch": 5, "five": 5, "chhe": 6, "che": 6, "chheh": 6, "six": 6, "saat": 7, "sat": 7, "seven": 7,
    "aath": 8, "ath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "dus": 10, "ten": 10, "gyarah": 11,
    "barah": 12, "baarah": 12, "twelve": 12, "dozen": 12, "darjan": 12, "pandrah": 15, "bees": 20, "bis": 20,
    "twenty": 20, "pachas": 50,
}  # fmt: skip
FILLER = {
    "kilo", "kg", "kgs", "kilogram", "gram", "grams", "gm", "g", "packet", "packets", "pack", "packs", "pkt",
    "paket", "litre", "liter", "ltr", "l", "bottle", "bottles", "botal", "piece", "pieces", "pcs", "pc", "peece",
    "dabba", "dibba", "box", "wala", "wali", "wale", "vala", "vali", "dena", "de", "dedo", "dijiye",
    "chahiye", "chaiye", "please", "plz", "bhaiya", "bhai", "ji", "ka", "ki", "ke", "the", "of", "a", "an", "bhi",
    "sir", "madam", "aunty", "uncle", "jara", "zara", "aur", "and", "or", "phir", "fir", "tatha",
}  # fmt: skip
SEPARATORS = {"aur", "and", "or", "phir", "fir", "tatha"}
_FILLER_KEYS = {skeleton(w) for w in FILLER} | {"paiket", "paikat", "litar", "botal", "pis", "kilogram", "dajan"}

# Hindi / brand-ish shop words -> words that appear in catalogue names or categories.
ALIASES = {
    "atta": "atta", "aata": "atta", "ata": "atta", "gehu": "atta", "chini": "sugar", "cheeni": "sugar",
    "shakkar": "sugar", "namak": "salt", "tel": "oil", "sarson": "mustard oil", "sarso": "mustard oil",
    "ghee": "ghee", "ghi": "ghee", "chawal": "rice", "chaval": "rice", "basmati": "basmati rice", "dal": "dal",
    "daal": "dal", "arhar": "toor dal", "toor": "toor dal", "chana": "chana", "channa": "chana", "haldi": "haldi",
    "masala": "masala", "badam": "almonds", "kaju": "kaju", "biskut": "biscuits", "biscuit": "biscuits",
    "parle": "glucose biscuits", "bhujia": "bhujia", "namkeen": "bhujia", "rusk": "rusk", "papa": "rusk",
    "chocolate": "chocolate", "maggi": "noodles", "maigi": "noodles", "noodle": "noodles", "chai": "tea",
    "patti": "tea", "chaipatti": "tea", "coke": "cold drink", "pepsi": "cold drink", "thanda": "cold drink",
    "coffee": "coffee", "kofi": "coffee", "juice": "juice", "jus": "juice", "sabun": "soap", "saabun": "soap",
    "manjan": "toothpaste", "colgate": "toothpaste", "paste": "toothpaste", "shampoo": "shampoo",
    "shampu": "shampoo", "nariyal": "coconut hair oil", "surf": "detergent", "sarf": "detergent",
    "washing": "detergent", "bartan": "dishwash", "vim": "dishwash", "phenyl": "floor cleaner",
    "fenyl": "floor cleaner", "pocha": "floor cleaner", "harpic": "toilet cleaner", "bread": "bread",
    "double": "bread", "roti": "bread", "pav": "bread", "paneer": "paneer", "panir": "paneer", "makhan": "butter",
    "makkhan": "butter", "butter": "butter", "amul": "butter", "dahi": "dahi", "curd": "dahi",
    "agarbatti": "agarbatti", "agarbati": "agarbatti", "diya": "diya", "diye": "diya", "deeya": "diya",
    "kapoor": "camphor", "kapur": "camphor", "batti": "wicks", "bati": "wicks", "chay": "tea",
}  # fmt: skip
_ALIAS_KEYS = {skeleton(k): v for k, v in ALIASES.items()}


def _alias(word: str) -> str:
    sk = skeleton(word)
    if sk in _ALIAS_KEYS:
        return _ALIAS_KEYS[sk]
    if len(sk) >= 4:
        hit = process.extractOne(sk, list(_ALIAS_KEYS), scorer=fuzz.ratio, score_cutoff=85)
        if hit:
            return _ALIAS_KEYS[hit[0]]
    return word


def _number(tok: str) -> int | None:
    if tok.isdigit():
        return int(tok)
    return NUMBERS.get(tok) or NUMBERS.get(skeleton(tok))


def split_order(text: str) -> tuple[str, list[tuple[list[str], int]]]:
    """Normalise the text and cut it into (words, quantity) phrases."""
    clean = transliterate(text.lower())
    clean = re.sub(r"(\d+)\s*(kg|g|gm|l|ml|pcs|pc)\b", r"\1", clean)
    tokens = re.findall(r"[a-z]{3}-\d{3,4}|[a-z]+|\d+|[,;।]", clean)
    phrases: list[tuple[list[str], int]] = []
    words: list[str] = []
    qty: int | None = None

    def flush(q: int | None) -> None:
        if words:
            phrases.append((list(words), max(1, q or 1)))
            words.clear()

    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        # "de do" / "dedo" at the end = "please give", not the number two
        if tok == "do" and (nxt is None or (i > 0 and tokens[i - 1] in ("de", "le", "dijiye"))):
            continue
        n = _number(tok)
        if n is not None and not (tok == "do" and nxt is not None and _number(nxt) is not None):
            if words:
                flush(qty if qty is not None else n)
                qty = None if qty is None else n
            else:
                qty = n
            continue
        if tok in SEPARATORS or tok in ",;।":
            flush(qty)
            qty = None
            continue
        if tok in FILLER or skeleton(tok) in _FILLER_KEYS or len(tok) < 2:
            continue
        words.append(tok)
    flush(qty)
    return clean, phrases


_UNIT_TOKEN = re.compile(r"^\d+(kg|g|gm|l|ml|pcs)?$")


def _tokens(text: str) -> list[str]:
    return [
        t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and not _UNIT_TOKEN.match(t) and t not in ("of", "pack")
    ]


def _score(query: list[str], name: list[str]) -> float:
    """Average best word match of the query words against the product's name words."""
    if not query or not name:
        return 0.0
    return sum(max(fuzz.ratio(q, t) for t in name) for q in query) / len(query)


def parse_order(session: Session, text: str) -> dict:
    """Match spoken/typed items to products: {"items": [...], "unmatched": [...], "text": normalised}."""
    clean, phrases = split_order(text)
    products = session.exec(select(Product).where(Product.is_active).order_by(Product.id)).all()
    categories = {c.id: _tokens(c.name) for c in session.exec(select(Category))}
    names = [(p, _tokens(p.name), categories.get(p.category_id, [])) for p in products]
    by_sku = {p.sku.lower(): p for p in products}
    items: list[dict] = []
    unmatched: list[str] = []

    def best(words: list[str]) -> tuple[Product | None, float]:
        query = _tokens(" ".join(_alias(w) for w in words))
        top, top_key = None, (0.0, 0.0)
        for product, name, cat in names:
            score = _score(query, name)
            if score < MIN_SCORE:  # a category word ("masala", "snacks") is a weaker hint
                score = max(score, _score(query, cat) * 0.8)
            covered = sum(1 for t in name if max(fuzz.ratio(q, t) for q in query) >= 80) / len(name) if name else 0
            key = (score, covered)
            if key > top_key:
                top, top_key = product, key
        return (top, top_key[0]) if top_key[0] >= MIN_SCORE else (None, 0.0)

    for words, qty in phrases:
        heard = " ".join(words)
        sku = by_sku.get(heard.replace(" ", "-")) or by_sku.get(heard)
        if sku:
            product, score = sku, 100.0
        else:
            product, score = best(words)
            if product is None and len(words) > 1:  # "atta maggi" said without numbers: try word by word
                for w in words:
                    p, sc = best([w])
                    if p:
                        items.append(_item(p, 1, w, sc))
                    else:
                        unmatched.append(w)
                continue
        if product is None:
            unmatched.append(heard)
            continue
        items.append(_item(product, qty, heard, score))

    merged: dict[int, dict] = {}
    for it in items:
        if it["product_id"] in merged:
            merged[it["product_id"]]["quantity"] += it["quantity"]
        else:
            merged[it["product_id"]] = it
    return {"text": clean, "items": list(merged.values()), "unmatched": unmatched}


def _item(p: Product, qty: int, heard: str, score: float) -> dict:
    return {
        "product_id": p.id,
        "sku": p.sku,
        "name": p.name,
        "quantity": qty,
        "unit": p.unit,
        "heard": heard,
        "score": round(score, 1),
    }
