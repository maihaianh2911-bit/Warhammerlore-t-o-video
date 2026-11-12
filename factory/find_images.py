"""Pictures for a video, searched by the machine (the search of japan-video-factory, extended to 40K artwork).

Usage: python3 -m factory.find_images <out_dir> "<query 1>" "<query 2>" ...
Each query is searched in one place:
  Tyberos the Red Wake        file search of the Warhammer 40k Wiki (Fandom): artwork of characters, chapters, ships
  page:Carcharodons           every picture used on that wiki article (up to 16)
  gallery:Sanguinius          the 40K Gallery catalogue kept in 00-video-mau/kho-anh-40k/ (14,000 titled artworks):
                              every word must be in the title or tags; "gallery:Sanguinius p2" = the next 16
  artstation:Sanguinius       ArtStation, most liked first: modern, high-resolution artwork by named artists
                              (the best-looking source; use it for every character and scene)
  commons:gothic cathedral    Wikimedia Commons, only licences that allow use in a monetised video (public
                              domain, CC0, CC BY, CC BY-SA); incategory:"…" works there
Wiki artwork is copyrighted by Games Workshop and the artists (the owner accepted that); its index entry has the
file page for the credit. Files under 400 px and duplicates of the same picture (also across earlier rounds
listed in FIND_SEEN) are dropped. Writes <out_dir>/<k>-<n>.jpg, <out_dir>/index.json and <out_dir>/sheet_<k>.jpg.
"""
import io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image

from .art import contact_sheet

COMMONS = 'https://commons.wikimedia.org/w/api.php'
WIKI = 'https://warhammer40k.fandom.com/api.php'
ARTSTATION = 'https://www.artstation.com/api/v2/search/projects.json'
CATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '00-video-mau', 'kho-anh-40k')
UA = 'LoreVideoFactory/1.0 (https://github.com/maihaianh2911-bit/Warhammerlore-t-o-video; picture search)'
OK = re.compile(r'^(public domain|pd|cc0|cc[- ]by(-sa)?[- ]?\d|cc[- ]by(-sa)?$)', re.I)


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(10 * (i + 1)); continue
            raise


def strip(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()


def api(base, params):
    d = json.loads(get(base + '?' + urllib.parse.urlencode({'action': 'query', 'format': 'json', **params})))
    return sorted((d.get('query') or {}).get('pages', {}).values(), key=lambda x: x.get('index', 0))


def artstation(q, n):
    """Most liked ArtStation projects for a search, each with the large version of its first picture."""
    d = json.loads(get(ARTSTATION + '?' + urllib.parse.urlencode({'query': q, 'page': 1, 'per_page': n, 'sorting': 'likes'})))
    out = []
    for pr in d.get('data') or []:
        cover = pr.get('smaller_square_cover_url') or ''
        # .../assets/images/images/029/063/820/<timestamp>/smaller_square/<name>.jpg → .../820/large/<name>.jpg
        m = re.match(r'(https://cdn[ab]\.artstation\.com/p/assets/images/images/\d+/\d+/\d+/)(?:\d+/)?smaller_square/(.+)$', cover)
        if not m or pr.get('is_adult_content') or pr.get('hide_as_adult'):
            continue
        artist = (pr.get('user') or {}).get('username', '')
        out.append({'title': (pr.get('title') or '').strip(), 'page': pr.get('url'), 'thumb': m.group(1) + 'large/' + m.group(2),
                    'width': None, 'height': None, 'source': 'ArtStation', 'artist': artist, 'license': '© ' + artist})
    return out


def catalog():
    """The 40K Gallery link catalogue: curated entries (tags, some artists) first, then the general list."""
    import gzip
    rows, seen = [], set()
    for name, opener in (('priority.jsonl', open), ('assets.jsonl.gz', gzip.open)):
        path = os.path.join(CATALOG, name)
        if not os.path.exists(path):
            continue
        with opener(path, 'rt', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get('image_url') not in seen:
                        seen.add(r.get('image_url')); rows.append(r)
    return rows


def gallery(q, n=16):
    """Catalogue entries whose title or tags hold every word of the query; 'p2', 'p3'… pick the next batch."""
    words = q.lower().split()
    page = int(words.pop()[1:]) if words and re.fullmatch(r'p\d+', words[-1]) else 1
    hits = []
    for r in catalog():
        text = (r.get('title', '') + ' ' + ' '.join(r.get('tags') or [])).lower().replace('-', ' ')
        url = r.get('image_url') or ''
        if words and all(w in text for w in words) and re.match(r'https://artwork\.40k\.gallery/[\w./%-]+$', url):
            hits.append({'title': r.get('title', ''), 'page': r.get('source_url'), 'thumb': url, 'width': None, 'height': None,
                         'source': '40K Gallery', 'artist': r.get('artist', ''), 'license': '© ' + (r.get('artist') or '40K Gallery')})
    return hits[(page - 1) * n:page * n]


def search(q, n=12):
    """Results of one query, in search order (see the module text for the kinds of query)."""
    q = q.strip()
    if q.lower().startswith('artstation:'):
        return artstation(q[11:].strip(), 24)
    if q.lower().startswith('gallery:'):
        return gallery(q[8:].strip())
    commons = q.lower().startswith('commons:')
    if commons:
        pages = api(COMMONS, {'generator': 'search', 'gsrsearch': q[8:].strip(), 'gsrnamespace': 6, 'gsrlimit': n,
                              'prop': 'imageinfo', 'iiprop': 'url|extmetadata|size|mime', 'iiurlwidth': 2000, 'maxlag': 5})
    elif q.lower().startswith('page:'):
        pages = api(WIKI, {'generator': 'images', 'titles': q[5:].strip(), 'gimlimit': 50, 'redirects': 1,
                           'prop': 'imageinfo', 'iiprop': 'url|size|mime', 'iiurlwidth': 2000})
        pages.sort(key=lambda pg: -((pg.get('imageinfo') or [{}])[0].get('width') or 0))   # artwork before icons
    else:
        pages = api(WIKI, {'generator': 'search', 'gsrsearch': q, 'gsrnamespace': 6, 'gsrlimit': n,
                           'prop': 'imageinfo', 'iiprop': 'url|size|mime', 'iiurlwidth': 2000})
    out = []
    for pg in pages:
        ii = (pg.get('imageinfo') or [{}])[0]
        if ii.get('mime') not in ('image/jpeg', 'image/png', 'image/tiff', 'image/webp'):
            continue
        r = {'title': pg['title'], 'page': ii.get('descriptionurl'), 'thumb': ii.get('thumburl') or ii.get('url'),
             'width': ii.get('width'), 'height': ii.get('height')}
        if commons:
            md = ii.get('extmetadata') or {}
            lic = strip((md.get('LicenseShortName') or {}).get('value'))
            if not OK.search(lic):
                continue
            r.update({'source': 'Wikimedia Commons', 'license': lic,
                      'artist': strip((md.get('Artist') or {}).get('value'))[:160],
                      'description': strip((md.get('ImageDescription') or {}).get('value'))[:300]})
        else:
            r.update({'source': 'Warhammer 40k Wiki (Fandom)', 'license': '© GW'})
        out.append(r)
    return out


MIN_SIDE = 400   # shorter side in pixels: smaller files only look blurred in the video
MIN_SIDE_CAT = 250   # incategory: searches target one person or work, whose small documents (a 1914 cover)
                     # still serve as a framed print
KEEP = 8         # pictures kept per query (12 are fetched, so dropped ones are replaced)


def dhash(im, n=8):
    """64-bit difference hash: two scans of the same painting differ in a few bits only."""
    if hasattr(im, 'draft'): im.draft('L', (256, 256))   # fast JPEG decode at reduced size
    g = im.convert('L'); g.thumbnail((256, 256)); g = g.resize((n + 1, n), Image.LANCZOS)
    px = list(g.tobytes())
    return sum(1 << i for i in range(n * n) if px[(i // n) * (n + 1) + i % n] > px[(i // n) * (n + 1) + i % n + 1])


def same(a, b):
    return bin(a ^ b).count('1') <= 10


def seen_hashes():
    """Pictures of earlier search rounds of the same video (FIND_SEEN = dirs separated by ':') are not shown again."""
    hs = []
    for d in filter(None, os.environ.get('FIND_SEEN', '').split(':')):
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if re.match(r'^\d+-\d+\.jpg$', f):
                try: hs.append(dhash(Image.open(os.path.join(d, f))))
                except Exception: pass
    return hs


def main():
    out, queries = sys.argv[1], sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    index, kept_hashes, dropped = [], seen_hashes(), {'small': 0, 'duplicate': 0}
    for k, q in enumerate(queries, 1):
        lim = MIN_SIDE_CAT if 'incategory:' in q.lower() else MIN_SIDE
        art = q.strip().lower().startswith(('artstation:', 'gallery:'))
        keep = 16 if art or q.strip().lower().startswith('page:') else KEEP
        lim = 900 if art else lim      # ArtStation has enough large pictures to be strict
        try:
            hits = search(q)
        except Exception as e:   # one bad query (timeout, reset, a site error) must not lose the others or the voice
            print(f'[{k}] {q}: lỗi tìm ảnh, bỏ qua — {type(e).__name__}: {e}', flush=True)
            hits = []
        found = [r for r in hits if r.get('width') is None or min(r.get('width') or 0, r.get('height') or 0) >= lim]
        dropped['small'] += len(hits) - len(found)
        kept = []   # [(result, image, hash)] in search order; a duplicate inside this query keeps the bigger file
        for r in found:
            if len(kept) >= keep:
                break
            try:
                im = Image.open(io.BytesIO(get(r['thumb']))).convert('RGB')
            except Exception as e:
                r['error'] = str(e)[:120]; continue
            finally:
                time.sleep(1)
            if r.get('width') is None:
                r['width'], r['height'] = im.size
                if min(im.size) < lim:
                    dropped['small'] += 1; continue
            h = dhash(im)
            if any(same(h, x) for x in kept_hashes):
                dropped['duplicate'] += 1; continue
            twin = next((i for i, (_, _, kh) in enumerate(kept) if same(h, kh)), None)
            if twin is not None:
                dropped['duplicate'] += 1
                if im.width * im.height > kept[twin][1].width * kept[twin][1].height:
                    kept[twin] = (r, im, h)
                continue
            kept.append((r, im, h))
        files, labels, results = [], {}, []
        for n, (r, im, h) in enumerate(kept, 1):
            im.thumbnail((4000, 4000))   # enough for crops of a detail; keeps the renders branch small
            p = f'{out}/{k}-{n}.jpg'; im.save(p, quality=90)
            r['file'] = p[len(out) + 1:]; files.append(p); results.append(r)
            lic = re.sub(r'(?i)public domain', 'PD', r['license'])
            labels[p] = f"#{n}  {r.get('width')}x{r.get('height')}  {lic}"[:44]
        kept_hashes += [h for _, _, h in kept]
        tiles = []
        for f in files:
            tile = Image.open(f).convert('RGB'); tile.thumbnail((360, 360)); tiles.append((tile, labels[f]))
        contact_sheet(tiles, f'{out}/sheet_{k}.jpg')
        index.append({'k': k, 'query': q, 'results': results})
        print(f'{k}. {q}: {len(results)} kept')
        time.sleep(2)
    json.dump(index, open(f'{out}/index.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"dropped: {dropped['small']} too small, {dropped['duplicate']} duplicates")


if __name__ == '__main__':
    main()
