"""Télécharge une fois les icônes de bg3.wiki dans le dossier icons/ du site.
Lancé par GitHub Actions (fichier .github/workflows/bg3-icons.yml).
Version 3 : choix des tableaux (TABLES), demandes groupées, pauses automatiques quand le wiki dit « trop de demandes »,
reprise là où il s'était arrêté si on le relance."""
import io, json, os, re, time, unicodedata
import requests
from PIL import Image

UA = {"User-Agent": "CodexBG3-personal-icon-cache/2.0 (outil personnel heberge sur GitHub Pages; telechargement unique et lent)"}
WIKI = "https://bg3.wiki"
OUT = "icons"
DELAY = 1.0            # pause entre deux images (secondes)
MAX_LONG_WAITS = 6     # au-delà, on s'arrête proprement (relancer plus tard reprendra)
S = requests.Session()
S.headers.update(UA)

def slug(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def clean(name):
    return re.sub(r"^(File|Fichier):", "", str(name), flags=re.I).strip()

long_waits = 0
def get(url, **kw):
    """GET avec pauses automatiques sur 429 / 5xx."""
    global long_waits
    wait = 30
    for attempt in range(8):
        r = S.get(url, timeout=90, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After")
            pause = int(ra) if ra and ra.isdigit() else wait
            pause = min(pause, 600)
            print(f"   le wiki demande une pause ({r.status_code}) : attente {pause} s")
            if pause >= 120:
                long_waits += 1
                if long_waits > MAX_LONG_WAITS:
                    raise SystemExit("STOP")
            time.sleep(pause)
            wait = min(wait * 2, 600)
            continue
        return r
    raise SystemExit("STOP")

def export(table, fields):
    p = {"title": "Special:CargoExport", "tables": table, "fields": "_pageName," + fields, "limit": "5000", "format": "json"}
    r = get(WIKI + "/w/index.php", params=p)
    r.raise_for_status()
    return r.json()

def val(row, k):
    v = row.get(k, row.get(k.replace("_", " ")))
    if isinstance(v, list):
        v = v[0] if v else None
    return v

USEFUL_MISC = {"Potions", "Elixirs", "Coatings", "Grenades", "Arrows", "Alchemical Ingredients", "Alchemical Extracts", "Scrolls", "Books", "Notes", "Slates"}
wanted = {}  # nom de fichier -> taille
# Tableaux à parcourir : variable TABLES, par ex. "weapons,equipment,spells" ou "consumables".
# Les icônes déjà présentes dans icons/ ne sont jamais retéléchargées.
tables = [t.strip() for t in (os.environ.get("TABLES") or "weapons,equipment,spells").split(",") if t.strip()]
if os.environ.get("WITH_CREATURES") == "true" and "creatures" not in tables:
    tables.append("creatures")
for table in tables:
    size = 160 if table == "creatures" else 96
    rows, field = None, None
    for fields, f in (("icon,type,legacy", "icon"), ("icon,legacy", "icon"), ("icon", "icon"), ("image", "image")):
        try:
            rows = export(table, fields)
            field = f
            break
        except SystemExit:
            raise
        except Exception:
            continue
    if rows is None:
        print(f"{table}: tableau ou champ d'image introuvable")
        continue
    n = 0
    for row in rows:
        if val(row, "legacy"):
            continue
        if re.search(r"camp clothing|camp shoes|underwear", str(val(row, "type") or ""), re.I):
            continue
        if table == "misc_items" and str(val(row, "type") or "") not in USEFUL_MISC:
            continue
        f = val(row, field) or val(row, "image")
        if f:
            wanted.setdefault(clean(f), size)
            n += 1
    print(f"{table}: {n} images utiles")
    time.sleep(DELAY)

os.makedirs(OUT, exist_ok=True)
idx_path = os.path.join(OUT, "index.json")
index = json.load(open(idx_path, encoding="utf-8")).get("files", {}) if os.path.exists(idx_path) else {}
def save_index():
    json.dump({"files": index, "date": time.strftime("%Y-%m-%d")}, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False)

todo = []
for name, size in sorted(wanted.items()):
    fname = slug(name) + ".webp"
    if os.path.exists(os.path.join(OUT, fname)):
        index[name] = fname
    else:
        todo.append((name, size, fname))
print(f"À télécharger : {len(todo)} (déjà présentes : {len(wanted) - len(todo)})")

ok = fail = 0
try:
    # 1) adresses des miniatures, par paquets de 50 (une seule demande au wiki par paquet)
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        size = max(s for _, s, _ in batch)
        p = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "iiurlwidth": str(size * 2),
             "titles": "|".join("File:" + n for n, _, _ in batch)}
        r = get(WIKI + "/w/api.php", params=p)
        pages = (r.json().get("query") or {}).get("pages") or {}
        urls = {}
        norm = {x["to"]: x["from"] for x in (r.json().get("query") or {}).get("normalized", [])}
        for pg in pages.values():
            title = pg.get("title", "")
            title = norm.get(title, title)
            ii = (pg.get("imageinfo") or [{}])[0]
            u = ii.get("thumburl") or ii.get("url")
            if u:
                urls[clean(title).replace("_", " ")] = u
        time.sleep(DELAY)
        # 2) téléchargement des miniatures, une par une, tranquillement
        for name, sz, fname in batch:
            u = urls.get(name.replace("_", " "))
            if not u:
                fail += 1
                continue
            try:
                r = get(u if u.startswith("http") else WIKI + u)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                img.thumbnail((sz, sz))
                img.save(os.path.join(OUT, fname), "WEBP", quality=85, method=6)
                index[name] = fname
                ok += 1
            except SystemExit:
                raise
            except Exception as e:
                print("échec", name, e)
                fail += 1
            time.sleep(DELAY)
        save_index()
        print(f"... {ok} téléchargées, {fail} introuvables, {len(todo) - i - len(batch)} restantes")
except SystemExit:
    print("Le wiki reste saturé : arrêt propre. Relance l'action plus tard, elle reprendra là où elle s'est arrêtée.")
save_index()
print(f"Terminé : {ok} nouvelles, {fail} introuvables. Total dans le dossier : {len(index)}.")
