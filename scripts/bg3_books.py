"""Récupère une fois le texte des livres, notes et tablettes de bg3.wiki
et l'enregistre dans data/books.json (lu par le codex : Bibliothèque → « Importer les textes »).
Lancé par GitHub Actions (fichier .github/workflows/bg3-books.yml). Lent et poli avec le wiki."""
import html, json, os, re, time
import requests

UA = {"User-Agent": "CodexBG3-personal-books-cache/1.0 (outil personnel heberge sur GitHub Pages; lecture unique et lente)"}
WIKI = "https://bg3.wiki"
OUT = os.path.join("data", "books.json")
DELAY = 1.5
S = requests.Session()
S.headers.update(UA)

def get(url, **kw):
    wait = 30
    for _ in range(8):
        r = S.get(url, timeout=120, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After")
            pause = min(int(ra) if ra and ra.isdigit() else wait, 600)
            print(f"   le wiki demande une pause ({r.status_code}) : attente {pause} s")
            time.sleep(pause)
            wait = min(wait * 2, 600)
            continue
        r.raise_for_status()
        return r
    raise SystemExit("Le wiki reste saturé : relance plus tard, le travail déjà fait est gardé.")

def val(row, k):
    v = row.get(k, row.get(k.replace("_", " ")))
    if isinstance(v, list):
        v = v[0] if v else None
    return v

def param(wikitext, names):
    """Extrait la valeur d'un paramètre de modèle (gère les {{ }} et [[ ]] imbriqués)."""
    for name in names:
        m = re.search(r"\|\s*" + name + r"\s*=", wikitext, re.I)
        if not m:
            continue
        i = m.end(); depth_t = depth_l = 0; out = []
        while i < len(wikitext):
            two = wikitext[i:i + 2]
            if two == "{{": depth_t += 1; out.append(two); i += 2; continue
            if two == "}}":
                if depth_t == 0: break
                depth_t -= 1; out.append(two); i += 2; continue
            if two == "[[": depth_l += 1; out.append(two); i += 2; continue
            if two == "]]": depth_l = max(0, depth_l - 1); out.append(two); i += 2; continue
            if wikitext[i] == "|" and depth_t == 0 and depth_l == 0 and re.match(r"\|\s*[\w ]+\s*=", wikitext[i:i + 60]):
                break
            out.append(wikitext[i]); i += 1
        txt = "".join(out).strip()
        if txt:
            return txt
    return ""

def clean(t):
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    for _ in range(5):
        t = re.sub(r"\{\{[^{}|]*\|([^{}]*?)\}\}", lambda m: m.group(1).split("|")[-1], t)
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"'''?", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

p = {"title": "Special:CargoExport", "tables": "misc_items", "fields": "_pageName,name,type,legacy,book_author,icon", "limit": "5000", "format": "json"}
rows = get(WIKI + "/w/index.php", params=p).json()
books = {}
for row in rows:
    typ = str(val(row, "type") or "")
    if typ not in ("Books", "Notes", "Slates") or val(row, "legacy"):
        continue
    page = val(row, "_pageName") or val(row, "name")
    if page and page not in books:
        books[page] = {"page": page, "name": html.unescape(str(val(row, "name") or page)), "type": typ,
                       "author": clean(str(val(row, "book_author") or "")), "icon": val(row, "icon"), "text": ""}
print(f"{len(books)} livres, notes et tablettes trouvés")

os.makedirs("data", exist_ok=True)
old = {}
if os.path.exists(OUT):
    old = {b["page"]: b for b in json.load(open(OUT, encoding="utf-8")).get("books", [])}
for page, b in books.items():
    if old.get(page, {}).get("text"):
        b["text"] = old[page]["text"]
todo = [b for b in books.values() if not b["text"]]
print(f"Textes à récupérer : {len(todo)} (déjà présents : {len(books) - len(todo)})")

def save():
    json.dump({"date": time.strftime("%Y-%m-%d"), "books": sorted(books.values(), key=lambda b: b["name"])},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

done = empty = 0
try:
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        q = {"action": "query", "format": "json", "formatversion": "2", "prop": "revisions", "rvprop": "content",
             "rvslots": "main", "redirects": "1", "titles": "|".join(b["page"] for b in batch)}
        data = get(WIKI + "/w/api.php", params=q).json().get("query", {})
        redir = {r["to"]: r["from"] for r in data.get("redirects", [])}
        norm = {n["to"]: n["from"] for n in data.get("normalized", [])}
        for pg in data.get("pages", []):
            title = pg.get("title", "")
            title = redir.get(title, title); title = norm.get(title, title)
            revs = pg.get("revisions") or []
            if not revs:
                continue
            wt = revs[0].get("slots", {}).get("main", {}).get("content", "") or revs[0].get("content", "")
            txt = clean(param(wt, ["book text", "book_text", "text"]))
            b = books.get(title) or books.get(title.replace("_", " "))
            if b is None:
                continue
            if txt:
                b["text"] = txt; done += 1
            else:
                empty += 1
        save()
        print(f"... {done} textes récupérés, {empty} sans texte, {len(todo) - i - len(batch)} restants")
        time.sleep(DELAY)
except SystemExit as e:
    print(e)
save()
print(f"Terminé : {done} nouveaux textes, {empty} pages sans texte. Fichier : {OUT}")
