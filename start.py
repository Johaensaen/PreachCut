#!/usr/bin/env python3
"""PreachCut - lokaler Predigt-Editor.
Start: Start.bat (Windows), Start.command (macOS) oder `python3 start.py` (Linux)."""
import json, mimetypes, os, re, shutil, subprocess, sys, threading, time, traceback, venv, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent
VENV, WORK, OUT = BASE / ".venv", BASE / "work", BASE / "output"
LANG_DIR = BASE / "languages"
PORT = 8766
JOBS, FF = {}, "ffmpeg"
IMG = (".png", ".jpg", ".jpeg", ".webp")
FULL = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
HALF = "scale=960:1080:force_original_aspect_ratio=decrease,pad=960:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
# Alle Teilvideos werden identisch kodiert, damit sie ohne Neuberechnung zusammengefügt werden können.
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", "25", "-c:a", "aac", "-b:a", "160k",
       "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
QUIET = [FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-stats"]


# ---------- Sprachprofile ----------
def get_available_languages():
    langs = []
    for f in sorted(LANG_DIR.glob("*.json")) if LANG_DIR.exists() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            langs.append({"code": data.get("language_code", f.stem), "name": data.get("name", f.stem.upper()), "file": f.name})
        except Exception:
            pass
    return langs or [{"code": "de", "name": "Deutsch", "file": "de.json"}]


def load_language_config(code):
    f = LANG_DIR / f"{re.sub(r'[^A-Za-z_-]', '', code)}.json"
    if not f.exists():
        f = LANG_DIR / "de.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"language_code": "de", "whisper_language": "de", "hint": "Predigt mit Bibelstellen: Psalm 23, Johannes 3,16, Römer 8,28.",
            "single_books": {}, "numbered_books": {}, "ordinals": {}, "units": {}, "tens": {}}


# ---------- Bibelstellen im Transkript finden (reine Textsuche) ----------
CHAP = {"kapitel", "kap", "chapter", "chap"}
VSEP = {",", ":", "vers", "verse", "verses", "ab", "from"}
RANGE = {"bis", "-", "–", "to", "through", "thru"}


def find_refs(words, cfg):
    """words: [(Sekunde, Wort)] -> [{"t", "ref", "text"}], z. B. Römer 8,28 oder 1. Korinther 13,4-7"""
    single, numbered = cfg.get("single_books", {}), cfg.get("numbered_books", {})
    ords, units, tens = cfg.get("ordinals", {}), cfg.get("units", {}), cfg.get("tens", {})
    german = cfg.get("language_code", "de") == "de"

    def num(w):
        if w.isdigit():
            return int(w)
        h = 0
        for hw in ("hundert", "hundred"):
            if hw in w:
                a, w = w.split(hw, 1)
                h = 100 * (units.get(a, 1) if a else 1)
                if not w:
                    return h
                break
        if w in units or w in tens:
            return h + (units.get(w) or tens[w])
        a, _, b = w.partition("und")
        if b in tens and (a in units and units[a] < 10 or a == "ein"):
            return h + units.get(a, 1) + tens[b]
        return None

    def num_at(toks, k):
        if k >= len(toks):
            return None, k
        w = toks[k][0]
        v = num(w)
        if v is None:
            return None, k
        if w in ("hundert", "hundred") and k + 1 < len(toks):
            w2 = num(toks[k + 1][0])
            if w2 is not None and w2 < 100:
                return 100 + w2, k + 2
        if not german and w in tens and k + 1 < len(toks):  # "twenty three"
            w2 = units.get(toks[k + 1][0])
            if w2 and w2 < 10:
                return v + w2, k + 2
        return v, k + 1

    def ordinal(w):
        if w in ("1", "2", "3", "4", "5"):
            return int(w)
        if w in ords:
            return ords[w]
        return ords.get(w[:-1], 0) if w[-1:] in ("r", "n", "s", "m") else 0

    strip = lambda w: w[:-5] if w.endswith("brief") and len(w) > 7 else w
    toks = [(m.group().lower(), t, wi) for wi, (t, w) in enumerate(words)
            for m in re.finditer(r"\d+|[^\W\d_]+|[,:–-]", w)]
    found, i = [], 0
    while i < len(toks):
        w, t, wi = toks[i]
        book, j = None, i + 1
        n = ordinal(w)
        if n and i + 1 < len(toks) and strip(toks[i + 1][0]) in numbered:
            book, j = f"{n}. {numbered[strip(toks[i + 1][0])]}", i + 2
        elif strip(w) in single:
            book = single[strip(w)]
        if not book:
            i += 1
            continue
        if j < len(toks) and toks[j][0] == "brief":
            j += 1
        if j < len(toks) and toks[j][0] in CHAP:
            j += 1
        ch, k = num_at(toks, j)
        if ch is None or ch > 150:
            i += 1
            continue
        ref, k2 = f"{book} {ch}", k
        while k2 < len(toks) and toks[k2][0] in VSEP:
            k2 += 1
        v, k3 = num_at(toks, k2)
        if v is not None and v <= 176:
            ref, k = f"{ref},{v}", k3
            if k < len(toks) and toks[k][0] in RANGE:
                v2, k4 = num_at(toks, k + 1)
                if v2 is not None and v < v2 <= 176:
                    ref, k = f"{ref}-{v2}", k4
        if not (found and found[-1]["ref"] == ref and t - found[-1]["t"] < 90):  # Wiederholungen zusammenfassen
            found.append({"t": round(max(t - 1, 0), 1), "ref": ref, "text": " ".join(x for _, x in words[max(wi - 5, 0): wi + 14])})
        i = max(k, i + 1)
    return found


# ---------- ffmpeg ----------
def media_info(f):
    t = subprocess.run([FF, "-hide_banner", "-i", str(f)], capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", t)
    return (int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0), "Audio:" in t


def run_ffmpeg(cmd, job, desc, p0, p1, dur=None):
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    job["msg"], job["pct"] = desc, p0
    print(f"--- {desc}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, errors="replace")
    tail = []
    for line in proc.stdout:
        if job.get("state") == "cancelled":
            proc.kill()
            raise InterruptedError("Abgebrochen")
        m = re.search(r"time=(\d+):(\d+):([\d.]+)", line)
        if m and dur:
            job["pct"] = p0 + (p1 - p0) * min((int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])) / dur, 1)
        elif line.strip():
            tail = (tail + [line.strip()])[-12:]
    if proc.wait() != 0:
        raise RuntimeError(f"{desc} fehlgeschlagen:\n" + "\n".join(tail))
    job["pct"] = p1


def segment_cmd(src, has_audio, a, dur, out, slide=None, side="right"):
    """Ein Teilstück: nur Redner, Redner + Folie nebeneinander oder Folie im Vollbild."""
    cmd = QUIET + ["-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    if slide:
        cmd += ["-loop", "1", "-framerate", "25", "-t", f"{dur:.3f}", "-i", str(slide)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    if not slide:
        g = f"[0:v]{FULL},fps=25[v]"
    elif side == "fullscreen":
        g = f"[1:v]{FULL},fps=25[v]"
    else:
        order = "[sl][sp]" if side == "left" else "[sp][sl]"
        g = f"[0:v]{HALF},fps=25[sp];[1:v]{HALF},fps=25[sl];{order}hstack=inputs=2[v]"
    audio = "0:a:0" if has_audio else f"{2 if slide else 1}:a"
    return cmd + ["-filter_complex", g, "-map", "[v]", "-map", audio, "-t", f"{dur:.3f}"] + ENC + [str(out)]


def clip_cmd(f, out):
    """Intro/Outro (Video oder Bild) in dasselbe Format bringen. Rückgabe: (Befehl, Dauer)."""
    img = f.suffix.lower() in IMG
    dur, aud = (5.0, False) if img else media_info(f)
    cmd = QUIET + (["-loop", "1", "-framerate", "25", "-t", "5", "-i", str(f)] if img else ["-i", str(f)])
    if not aud:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    return cmd + ["-filter_complex", f"[0:v]{FULL},fps=25[v]", "-map", "[v]", "-map", "0:a:0" if aud else "1:a",
                  "-t", f"{dur:.3f}"] + ENC + [str(out)], dur


DEFAULT_CROP = ("crop='min(iw,ih*9/16)':ih,scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1,format=yuv420p")


def short_filter(src, t0, dur, face, job):
    """Hochformat-Ausschnitt: folgt dem Gesicht des Redners, sonst Bildmitte."""
    if face:
        try:
            import media_ai
            job["msg"] = "Suche den Redner im Bild ..."
            model = media_ai.ensure_face_model(BASE / "modelle")
            centers = media_ai.track_speaker_centers(src, FF, t0, dur, model, str(WORK))
            if centers:
                return media_ai.vertical_crop_filter(centers, 1080) + ",format=yuv420p"
        except Exception as e:
            print("Gesichtserkennung nicht verfügbar, nutze Bildmitte:", e)
    return DEFAULT_CROP


def process(p):
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    clips = []
    try:
        src = next(d.glob("video.*"))
        total, has_audio = media_info(src)
        if total <= 0:
            raise RuntimeError("Das Video konnte nicht gelesen werden.")
        name = re.sub(r"[^\w\-]", "_", p.get("name") or "Predigt") + time.strftime("_%Y%m%d-%H%M")
        out_main = OUT / f"{name}_16x9.mp4"

        slides = []
        for i in p.get("items", []):
            f = d / Path(i.get("file") or "x").name
            if i.get("file") and f.is_file():
                a = max(float(i["t"]), 0.0)
                slides.append([a, min(a + max(float(i["d"]), 1.0), total), f, i.get("side", "right")])
        slides.sort(key=lambda s: s[0])
        for s, nxt in zip(slides, slides[1:]):
            s[1] = min(s[1], nxt[0])
        slides = [s for s in slides if s[1] - s[0] >= 0.3]

        plan, cur = [], 0.0  # Zeitleiste in Teilstücke zerlegen
        for a, b, f, side in slides:
            if a - cur >= 0.05:
                plan.append((cur, a, None, None))
            plan.append((a, b, f, side))
            cur = b
        if total - cur >= 0.05 or not plan:
            plan.append((cur, total, None, None))

        intro, outro = next(d.glob("intro.*"), None), next(d.glob("outro.*"), None)
        extra = sum(5.0 if f.suffix.lower() in IMG else media_info(f)[0] for f in (intro, outro) if f)
        grand, done = sum(b - a for a, b, _, _ in plan) + extra or 1.0, 0.0

        def step(desc, cmd, out, dur):
            nonlocal done
            run_ffmpeg(cmd, job, desc, 3 + 82 * done / grand, 3 + 82 * (done + dur) / grand, dur)
            done += dur
            clips.append(out)

        if intro:
            c = d / "c_intro.mp4"
            cmd, dur = clip_cmd(intro, c)
            step("Intro wird vorbereitet", cmd, c, dur)
        for n, (a, b, f, side) in enumerate(plan):
            c = d / f"c_{n:03d}.mp4"
            what = f"Folie {sum(1 for x in plan[:n + 1] if x[2])} von {len(slides)}" if f else "Predigt"
            step(f"Schneide {what} (Teil {n + 1} von {len(plan)})", segment_cmd(src, has_audio, a, b - a, c, f, side), c, b - a)
        if outro:
            c = d / "c_outro.mp4"
            cmd, dur = clip_cmd(outro, c)
            step("Outro wird vorbereitet", cmd, c, dur)

        lst = d / "list.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
        run_ffmpeg([FF, "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out_main)], job, "Teile werden zusammengefügt", 86, 92)

        shorts = [x for x in (p.get("shorts") or []) if float(x.get("d") or 0) >= 1] or [
            {"t": slides[0][0] if slides else 60.0, "d": 60.0, "title": "Short"}]
        files, labels = [out_main.name], ["Langversion (16:9)"]
        for n, sh in enumerate(shorts, 1):
            dl = min(float(sh["d"]), total)
            t0 = max(min(float(sh["t"]), total - dl), 0.0)
            out_short = OUT / f"{name}_short{n}_9x16.mp4"
            vf = short_filter(src, t0, dl, p.get("face_tracking", True), job)
            run_ffmpeg(QUIET + ["-ss", f"{t0:.3f}", "-t", f"{dl:.3f}", "-i", str(src), "-vf", vf,
                                "-map", "0:v:0", "-map", "0:a:0?"] + ENC + [str(out_short)], job,
                       f"Short {n} von {len(shorts)} (9:16)", 93 + 6 * (n - 1) / len(shorts), 93 + 6 * n / len(shorts), dl)
            files.append(out_short.name)
            labels.append(f"Short {n}: {sh.get('title') or 'Highlight'}")
        job.update(state="done", pct=100, msg="Fertig!", files=files, labels=labels)
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))
    finally:
        for c in clips:
            c.unlink(missing_ok=True)


# ---------- Spracherkennung ----------
def cuda_ok():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def analyze(p):
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    lang = p.get("language") or "de"
    cfg = load_language_config(lang)
    try:
        cache = d / "words.json"
        if cache.exists() and not p.get("force_retranscribe"):
            job.update(msg="Lade vorherige Transkription ...", pct=50)
            words = [(w["start"], w["word"]) for w in json.loads(cache.read_text(encoding="utf-8"))]
            job.update(state="done", pct=100, msg="Fertig!", refs=find_refs(words, cfg))
            return
        from faster_whisper import WhisperModel
        video = next(d.glob("video.*"))
        name = p.get("model") or "base"
        local = BASE / "modelle" / name  # Offline-Paket: Modell liegt schon im Ordner
        user = (p.get("prompt") or "").strip()
        prompt = f"{user}. {cfg.get('hint', '')}" if user else cfg.get("hint", "")
        for device in (["cuda"] if cuda_ok() else []) + ["cpu"]:
            try:
                job["msg"] = f"Lade Spracherkennung ({'Grafikkarte' if device == 'cuda' else 'Prozessor'}) ..."
                model = WhisperModel(str(local) if local.exists() else name, device=device,
                                     compute_type="float16" if device == "cuda" else "int8")
                segs, info = model.transcribe(str(video), language=cfg.get("whisper_language", lang), vad_filter=True,
                                              word_timestamps=True, initial_prompt=prompt)
                objs = []
                for sg in segs:
                    if job.get("state") == "cancelled":
                        raise InterruptedError("Abgebrochen")
                    objs += [{"start": w.start, "end": w.end, "word": w.word.strip()} for w in (sg.words or [])]
                    job["pct"] = min(99, round(100 * sg.end / max(info.duration, 1)))
                    job["msg"] = f"Erkenne Bibelstellen ... {int(sg.end // 60)} / {int(info.duration // 60)} Min."
                break
            except InterruptedError:
                raise
            except Exception:
                if device == "cpu":
                    raise
                traceback.print_exc()  # z. B. fehlende CUDA-Bibliotheken: automatisch auf den Prozessor wechseln
        cache.write_text(json.dumps(objs, ensure_ascii=False), encoding="utf-8")
        job.update(state="done", pct=100, msg="Fertig.", refs=find_refs([(w["start"], w["word"]) for w in objs], cfg))
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))


def highlights(p):
    """Drei Highlight-Vorschläge für Shorts (lokales Textmodell, sonst zeitbasierte Vorauswahl)."""
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    try:
        import media_ai
        words = json.loads((d / "words.json").read_text(encoding="utf-8"))
        dur = media_info(next(d.glob("video.*")))[0]
        refs = find_refs([(w["start"], w["word"]) for w in words], load_language_config(p.get("language") or "de"))

        def progress(msg, done, total):
            if job.get("state") == "cancelled":
                raise InterruptedError("Abgebrochen")
            job["pct"], job["msg"] = min(99, 100 * done / max(total, 1)), msg
            if "nicht verfügbar" in msg:
                job["note"] = msg

        job.update(state="run", highlights=media_ai.suggest_highlights(words, refs, dur, BASE / "modelle", progress))
        job.update(state="done", pct=100, msg="Fertig.")
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))


# ---------- Server ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, data, ctype="application/json"):
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def serve(self, f, ctype, attach=False):  # mit Range-Unterstützung (nötig für Vorschau/Spulen, v. a. in Safari)
        size = f.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m[1] or m[2]):
            if m[1]:
                start, end = int(m[1]), int(m[2]) if m[2] else size - 1
            else:
                start = max(size - int(m[2]), 0)
            end = min(end, size - 1)
            if start > end:
                return self.send_error(416)
            code = 206
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if attach:
                self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    c = fh.read(min(left, 1 << 20))
                    if not c:
                        break
                    self.wfile.write(c)
                    left -= len(c)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Browser hat die Anfrage beim Spulen abgebrochen: normal

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self.send((BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/favicon.png" and (BASE / "favicon.png").exists():
            return self.send((BASE / "favicon.png").read_bytes(), "image/png")
        if path == "/api/languages":
            return self.send(json.dumps(get_available_languages()).encode())
        if path.startswith("/cancel/"):
            if path[8:] in JOBS:
                JOBS[path[8:]]["state"] = "cancelled"
            return self.send(b'{"ok":true}')
        if path.startswith("/status/"):
            return self.send(json.dumps(JOBS.get(path[8:], {"state": "error", "msg": "Unbekannt"})).encode())
        if path.startswith("/video/"):
            vf = next((WORK / re.sub(r"[^\w\-]", "_", path[7:])).glob("video.*"), None)
            if vf:
                return self.serve(vf, mimetypes.guess_type(vf.name)[0] or "video/mp4")
        f = OUT / Path(path).name
        if path.startswith(("/fertig/", "/output/")) and f.is_file():
            return self.serve(f, "video/mp4", attach=True)
        self.send_error(404)

    def do_PUT(self):  # /upload/<sid>/<dateiname> mit rohem Dateiinhalt
        _, _, sid, name = self.path.split("/", 3)
        clean = lambda x: re.sub(r"[^\w.\-]", "_", Path(unquote(x)).name)
        d = WORK / clean(sid)
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(clean(name).split(".")[0] + ".*"):
            old.unlink()
        n = int(self.headers["Content-Length"])
        with open(d / clean(name), "wb") as f:
            while n > 0:
                c = self.rfile.read(min(n, 1 << 20))
                if not c:
                    break
                f.write(c)
                n -= len(c)
        self.send(b'{"ok":true}')

    def do_POST(self):
        p = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p["sid"] = re.sub(r"[^\w\-]", "_", p["sid"])
        fn, tag = {"/analyze": (analyze, "a"), "/highlights": (highlights, "h")}.get(self.path, (process, "p"))
        p["jid"] = jid = re.sub(r"[^\w\-]", "_", p.get("jid") or p["sid"] + tag)
        JOBS[jid] = {"state": "run", "pct": 0, "msg": "Startet ...", "files": [], "refs": [], "highlights": []}
        threading.Thread(target=fn, args=(p,), daemon=True).start()
        self.send(b'{"ok":true}')


def prepare():
    """Einmal mit Internet ausführen: lädt Pakete und Sprachmodell für den Offline-Betrieb in diesen Ordner."""
    print("Pakete und Sprachmodell werden heruntergeladen ...")
    req = BASE / "requirements.txt"
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "-d", str(BASE / "pakete")]
                          + (["-r", str(req)] if req.exists() else ["faster-whisper", "imageio-ffmpeg"]))
    if (BASE / "requirements-ai.txt").exists():
        subprocess.call([sys.executable, "-m", "pip", "download", "-q", "-d", str(BASE / "pakete"), "-r", str(BASE / "requirements-ai.txt")])
    from faster_whisper.utils import download_model
    download_model("base", output_dir=str(BASE / "modelle" / "base"))
    try:
        import media_ai
        media_ai.prepare_models(BASE / "modelle")  # Textmodell (ca. 940 MB) + Gesichtserkennung
    except Exception as e:
        print("Optionale Modelle (Highlights/Gesichtserkennung) konnten nicht geladen werden:", e)
    print("Fertig. Jetzt den ganzen Ordner (ohne .venv, work, output) als ZIP packen.")


def main():
    global FF
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    QUIET[0] = FF
    if "--vorbereiten" in sys.argv:
        return prepare()
    url = f"http://localhost:{PORT}"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        print(f"Port {PORT} ist belegt, PreachCut läuft vermutlich schon. Öffne {url}")
        webbrowser.open(url)
        return
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    print(f"PreachCut läuft: {url}\nDieses Fenster offen lassen. Zum Beenden schließen (oder Strg+C).")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def bootstrap():
    """Legt beim ersten Start eine eigene Python-Umgebung an und installiert alles Nötige."""
    if sys.version_info < (3, 9):
        sys.exit("Bitte Python 3.9 oder neuer installieren: https://www.python.org/downloads/")
    py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    req, ai_req, wheels = BASE / "requirements.txt", BASE / "requirements-ai.txt", BASE / "pakete"
    offline = ["--no-index", "--find-links", str(wheels)] if wheels.exists() else []
    if not (VENV / ".ok").exists():
        if py.exists() and subprocess.call([str(py), "-c", "import faster_whisper, imageio_ffmpeg"]) == 0:
            (VENV / ".ok").write_text("1")  # vorhandene, funktionierende Umgebung weiterverwenden
        else:
            print("Erster Start: Pakete werden installiert (einmalig, einige Minuten, Internet nötig) ...")
            shutil.rmtree(VENV, ignore_errors=True)
            venv.create(VENV, with_pip=True)
            cmd = [str(py), "-m", "pip", "install", "-q"] + offline
            if subprocess.call(cmd + (["-r", str(req)] if req.exists() else ["faster-whisper", "imageio-ffmpeg"])) != 0:
                shutil.rmtree(VENV, ignore_errors=True)
                sys.exit("Installation fehlgeschlagen. Bitte Internetverbindung prüfen und erneut starten.")
            (VENV / ".ok").write_text("1")
    if ai_req.exists() and not (VENV / ".ai").exists():  # optional: darf scheitern, PreachCut läuft dann ohne
        print("Zusatzpakete für Highlights und Gesichtserkennung werden installiert ...")
        ok = subprocess.call([str(py), "-m", "pip", "install", "-q"] + offline + ["-r", str(ai_req)]) == 0
        (VENV / ".ai").write_text("1" if ok else "0")
        if not ok:
            print("Zusatzpakete nicht installiert: Highlights nutzen Zeitvorschläge, der Short zeigt die Bildmitte.")
    sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *sys.argv[1:]]))


if __name__ == "__main__":
    bootstrap()
    main()
