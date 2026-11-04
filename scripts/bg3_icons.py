"""Télécharge une fois les icônes de bg3.wiki dans le dossier icons/ du site.
Lancé par GitHub Actions (fichier .github/workflows/bg3-icons.yml)."""
import io, json, os, re, time, unicodedata, urllib.parse
import requests
from PIL import Image

UA = {"User-Agent": "CodexBG3-personal-icon-cache/1.0 (outil personnel heberge sur GitHub Pages)"}
EXPORT = "https://bg3.wiki/w/index.php"
OUT = "icons"
TABLES = [("weapons", "icon", 96), ("equipment", "icon", 96), ("spells", "icon", 96)]
if os.environ.get("WITH_CREATURES") == "true":
    TABLES.append(("creatures", "image", 160))

def slug(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def clean(name):
    return re.sub(r"^(File|Fichier):", "", str(name), flags=re.I).strip()

def export(table, field):
    p = {"title": "Special:CargoExport", "tables": table, "fields": f"_pageName,{field}", "limit": "5000", "format": "json"}
    r = requests.get(EXPORT, params=p, headers=UA, timeout=120)
    r.raise_for_status()
    rows = r.json()
    names = set()
    for row in rows:
        v = row.get(field) or row.get(field.replace("_", " "))
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            names.add(clean(v))
    return names

os.makedirs(OUT, exist_ok=True)
idx_path = os.path.join(OUT, "index.json")
index = {}
if os.path.exists(idx_path):
    index = json.load(open(idx_path, encoding="utf-8")).get("files", {})

todo = {}
for table, field, size in TABLES:
    try:
        names = export(table, field)
        print(f"{table}: {len(names)} images")
        for n in names:
            todo.setdefault(n, size)
    except Exception as e:
        print(f"{table}: export impossible ({e})")

ok = skip = fail = 0
for name, size in sorted(todo.items()):
    fname = slug(name) + ".webp"
    path = os.path.join(OUT, fname)
    if os.path.exists(path):
        index[name] = fname
        skip += 1
        continue
    url = "https://bg3.wiki/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_")) + f"?width={size * 2}"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 404:
                raise FileNotFoundError(name)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img.thumbnail((size, size))
            img.save(path, "WEBP", quality=85, method=6)
            index[name] = fname
            ok += 1
            break
        except FileNotFoundError:
            fail += 1
            break
        except Exception as e:
            if attempt == 2:
                print("échec", name, e)
                fail += 1
            time.sleep(2)
    time.sleep(0.15)
    if (ok + fail) % 200 == 0:
        print(f"... {ok} téléchargées, {fail} échecs")
        json.dump({"files": index}, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False)

json.dump({"files": index, "date": time.strftime("%Y-%m-%d")}, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False)
print(f"Terminé : {ok} nouvelles, {skip} déjà présentes, {fail} introuvables. Total {len(index)}.")
