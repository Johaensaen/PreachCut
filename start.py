#!/usr/bin/env python3
import json, os, re, shutil, subprocess, sys, threading, traceback, venv, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
VENV, WORK, OUT = BASE / ".venv", BASE / "arbeit", BASE / "fertig"
PORT = 8766
JOBS, FF = {}, "ffmpeg"
HINT = "Predigt mit Bibelstellen: 1. Mose 1, Psalm 23, Jesaja 53, Matthäus 5, Johannes 3,16, Römer 8,28, Offenbarung."

SINGLE = {b.lower(): b for b in (
    "Genesis Exodus Levitikus Numeri Deuteronomium Josua Richter Rut Esra Nehemia Ester Hiob Psalm Sprüche "
    "Prediger Hohelied Jesaja Jeremia Klagelieder Hesekiel Daniel Hosea Joel Amos Obadja Jona Micha Nahum "
    "Habakuk Zefanja Haggai Sacharja Maleachi Matthäus Markus Lukas Johannes Apostelgeschichte Römer Galater "
    "Epheser Philipper Kolosser Titus Philemon Hebräer Jakobus Judas Offenbarung").split()}
SINGLE.update({
    "psalmen": "Psalm", "ps": "Psalm", "pss": "Psalm", "ruth": "Rut", "esther": "Ester", "ijob": "Hiob", "sprichwörter": "Sprüche",
    "gen": "Genesis", "ex": "Exodus", "lev": "Levitikus", "num": "Numeri", "dtn": "Deuteronomium",
    "jos": "Josua", "ri": "Richter", "neh": "Nehemia", "est": "Ester", "spr": "Sprüche",
    "pred": "Prediger", "koh": "Prediger", "hld": "Hohelied", "jes": "Jesaja", "jer": "Jeremia",
    "klgl": "Klagelieder", "hes": "Hesekiel", "ez": "Hesekiel", "dan": "Daniel", "hos": "Hosea",
    "am": "Amos", "obd": "Obadja", "jona": "Jona", "mi": "Micha", "nah": "Nahum", "hab": "Habakuk",
    "zef": "Zefanja", "hag": "Haggai", "sach": "Sacharja", "mal": "Maleachi",
    "mt": "Matthäus", "matt": "Matthäus", "matthäus": "Matthäus", "mk": "Markus", "markus": "Markus",
    "lk": "Lukas", "lukas": "Lukas", "joh": "Johannes", "johannes": "Johannes", "apg": "Apostelgeschichte",
    "röm": "Römer", "rom": "Römer", "gal": "Galater", "eph": "Epheser", "phil": "Philipper",
    "kol": "Kolosser", "tit": "Titus", "phlm": "Philemon", "heb": "Hebräer", "jak": "Jakobus",
    "jud": "Judas", "offb": "Offenbarung", "off": "Offenbarung"
})

NUMBERED = {b.lower(): b for b in "Mose Samuel Könige Chronik Korinther Thessalonicher Timotheus Petrus Johannes".split()}
NUMBERED.update({
    "kor": "Korinther", "korinther": "Korinther", "thess": "Thessalonicher", "thessalonicher": "Thessalonicher",
    "tim": "Timotheus", "timotheus": "Timotheus", "petr": "Petrus", "petrus": "Petrus", "pt": "Petrus",
    "sam": "Samuel", "samuel": "Samuel", "kön": "Könige", "könige": "Könige", "kon": "Könige",
    "chr": "Chronik", "chronik": "Chronik", "joh": "Johannes", "mose": "Mose"
})

ORD = re.compile(r"(erste|zweite|dritte|vierte|fünfte)[rnsm]?$")
UNITS = {w: i + 1 for i, w in enumerate("eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn fünfzehn sechzehn siebzehn achtzehn neunzehn".split())}
TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90}

def wordnum(w):
    if w.isdigit(): return int(w)
    h = 0
    if "hundert" in w:
        a, w = w.split("hundert", 1)
        h = 100 * (UNITS.get(a, 1) if a else 1)
        if not w: return h
    if w in UNITS or w in TENS: return h + (UNITS.get(w) or TENS[w])
    a, _, b = w.partition("und")
    if b in TENS and (a in UNITS and UNITS[a] < 10 or a == "ein"): return h + UNITS.get(a, 1) + TENS[b]
    return None

def num_at(toks, k):
    if k >= len(toks): return None, k
    v = wordnum(toks[k][0])
    if v is None: return None, k
    if toks[k][0] == "hundert" and k + 1 < len(toks):
        w2 = wordnum(toks[k+1][0])
        if w2 is not None and w2 < 100: return 100 + w2, k + 2
    return v, k + 1

def find_refs(words):
    toks = [(m.group().lower(), t, wi) for wi, (t, w) in enumerate(words) for m in re.finditer(r"\d+|[^\W\d_]+|[,:–-]", w)]
    strip = lambda w: w[:-5] if w.endswith("brief") and len(w) > 7 else w
    found, i = [], 0
    while i < len(toks):
        w, t, wi = toks[i]
        book, j = None, i + 1
        m = ORD.match(w)
        n = int(w) if w in ("1", "2", "3", "4", "5") else (["erste", "zweite", "dritte", "vierte", "fünfte"].index(m.group(1)) + 1 if m else 0)
        if n and i + 1 < len(toks) and strip(toks[i+1][0]) in NUMBERED:
            book, j = f"{n}. {NUMBERED[strip(toks[i+1][0])]}", i + 2
        elif strip(w) in SINGLE:
            book = SINGLE[strip(w)]
        if not book:
            i += 1
            continue
        if j < len(toks) and toks[j][0] == "brief": j += 1
        if j < len(toks) and toks[j][0] in ("kapitel", "kap"): j += 1
        ch, k = num_at(toks, j)
        if ch is None or ch > 150:
            i += 1
            continue
        ref = f"{book} {ch}"
        k2 = k
        while k2 < len(toks) and toks[k2][0] in (",", ":", "vers", "verse", "ab"): k2 += 1
        v, k3 = num_at(toks, k2)
        if v is not None and v <= 176:
            ref, k = f"{ref},{v}", k3
            if k < len(toks) and toks[k][0] in ("bis", "-", "–"):
                v2, k4 = num_at(toks, k+1)
                if v2 is not None and v < v2 <= 176: ref, k = f"{ref}-{v2}", k4
        text = " ".join(x for _, x in words[max(wi-5,0):wi+14])
        if not (found and found[-1]["ref"] == ref and t - found[-1]["t"] < 90):
            found.append({"t": round(max(t-1, 0), 1), "ref": ref, "text": text})
        i = max(k, i+1)
    return found

def probe(f):
    t = subprocess.run([FF, "-i", str(f)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", t)
    return (int(m[1])*3600 + int(m[2])*60 + float(m[3]) if m else 5)

def run_ffmpeg_with_logging(cmd, job, desc, start_pct, end_pct, total_duration=None):
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    print(f"\n--- [AUSFÜHRUNG] {desc} ---")
    print(" ".join(cmd))
    job["msg"] = desc
    job["pct"] = start_pct
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    for line in process.stdout:
        if job.get("state") == "cancelled":
            process.terminate()
            raise InterruptedError("Abgebrochen")
        stripped = line.strip()
        if stripped:
            print(f"[{desc}] {stripped}")
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", stripped)
            if m and total_duration and total_duration > 0:
                cur_sec = int(m[1])*3600 + int(m[2])*60 + float(m[3])
                ratio = min(1.0, cur_sec / total_duration)
                job["pct"] = start_pct + int((end_pct - start_pct) * ratio)

    ret = process.wait()
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    if ret != 0:
        raise RuntimeError(f"{desc} fehlgeschlagen mit Code {ret}")
    job["pct"] = end_pct

def analyze(p):
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    try:
        words_file = d / "words.json"
        # Wenn die Transkription bereits existiert (Cache), überspringen wir Whisper komplett!
        if words_file.exists() and not p.get("force_retranscribe", False):
            job["msg"] = "Lade vorherige Transkription (Blitz-Cache)..."
            job["pct"] = 50
            with open(words_file, "r", encoding="utf-8") as wf:
                all_word_objs = json.load(wf)
            words = [(w["start"], w["word"]) for w in all_word_objs]
            job.update(state="done", pct=100, msg="Fertig!", refs=find_refs(words))
            return

        from faster_whisper import WhisperModel
        job["msg"] = "Lade KI-Modell (base)..."
        try:
            model = WhisperModel("base", device="cuda", compute_type="float16")
        except Exception:
            try:
                model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
            except Exception:
                model = WhisperModel("base", device="cpu", compute_type="int8")

        if job.get("state") == "cancelled": return

        user_prompt = p.get("prompt", "").strip()
        full_prompt = f"{user_prompt}. {HINT}" if user_prompt else HINT

        video_path = next(d.glob("video.*"))
        segs, info = model.transcribe(str(video_path), language="de", vad_filter=True, word_timestamps=True, initial_prompt=full_prompt)
        
        words = []
        all_word_objs = []
        for sg in segs:
            if job.get("state") == "cancelled": return
            for w in (sg.words or []):
                w_text = w.word.strip()
                words.append((w.start, w_text))
                all_word_objs.append({"start": w.start, "end": w.end, "word": w_text})
            job["pct"] = min(99, round(100 * sg.end / max(info.duration, 1)))
            job["msg"] = f"Erkenne Bibelstellen... {int(sg.end // 60)} / {int(info.duration // 60)} Min."
            
        with open(words_file, "w", encoding="utf-8") as wf:
            json.dump(all_word_objs, wf, ensure_ascii=False)

        job.update(state="done", pct=100, msg="Fertig.", refs=find_refs(words))
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))

def process(p):
    sid, job, d = p["sid"], JOBS[p["jid"]], WORK / p["sid"]
    try:
        src = next(d.glob("video.*"))
        total_dur = probe(src)
        out_main = OUT / "Predigt_Langversion_16x9.mp4"
        out_short = OUT / "Predigt_Highlight_Short_9x16.mp4"

        intro_file = list(d.glob("intro.*"))
        outro_file = list(d.glob("outro.*"))
        has_intro, has_outro = len(intro_file) > 0, len(outro_file) > 0

        job["msg"] = "Starte Videoschnitt..."
        job["pct"] = 5

        items = p.get("items", [])
        slides = []
        for i in items:
            if i.get("file"):
                fpath = d / i["file"]
                if fpath.exists():
                    slides.append((fpath, max(float(i["t"]), 0), min(float(i["t"]) + float(i["d"]), total_dur), i.get("side", "right")))

        fit_full = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        fit_half = "scale=960:1080:force_original_aspect_ratio=decrease,pad=960:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        enc_fast = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]

        predigt_temp = d / "temp_predigt.mp4"

        if slides:
            cmd = [FF, "-y", "-hide_banner", "-i", str(src)]
            for f, _, _, _ in slides: cmd += ["-loop", "1", "-framerate", "25", "-t", f"{total_dur}", "-i", str(f)]
            
            parts = [f"[0:v]{fit_full},fps=25[bg]", f"[0:v]{fit_half},fps=25[speaker_half]"]
            for k, _ in enumerate(slides):
                parts.append(f"[{k+1}:v]{fit_half},fps=25[slide_half_{k}]")
                parts.append(f"[{k+1}:v]{fit_full},fps=25[slide_full_{k}]")
            
            cur = "bg"
            for k, (_, a, b, side) in enumerate(slides):
                if side == "left":
                    parts.append(f"[{cur}][slide_half_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][speaker_half]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                elif side == "fullscreen":
                    parts.append(f"[{cur}][slide_full_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                else:
                    parts.append(f"[{cur}][speaker_half]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][slide_half_{k}]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                cur = f"v{k}"
            parts.append(f"[{cur}]null[out]")

            cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-map", "0:a?"] + enc_fast + [str(predigt_temp)]
            run_ffmpeg_with_logging(cmd, job, f"Rendere Split-Screen Langversion ({len(slides)} Folien)...", 10, 55, total_duration=total_dur)
        else:
            predigt_temp = src

        if has_intro or has_outro:
            concat_list = d / "concat.txt"
            with open(concat_list, "w") as cl:
                if has_intro:
                    intro_conv = d / "intro_conv.mp4"
                    intro_dur = probe(intro_file[0])
                    run_ffmpeg_with_logging([FF, "-y", "-i", str(intro_file[0]), "-vf", fit_full, "-r", "25"] + enc_fast + [str(intro_conv)], job, "Konvertiere Intro-Video", 55, 62, total_duration=intro_dur)
                    cl.write(f"file 'intro_conv.mp4'\n")
                cl.write(f"file '{predigt_temp.name}'\n")
                if has_outro:
                    outro_conv = d / "outro_conv.mp4"
                    outro_dur = probe(outro_file[0])
                    run_ffmpeg_with_logging([FF, "-y", "-i", str(outro_file[0]), "-vf", fit_full, "-r", "25"] + enc_fast + [str(outro_conv)], job, "Konvertiere Outro-Video", 62, 72, total_duration=outro_dur)
                    cl.write(f"file 'outro_conv.mp4'\n")
            run_ffmpeg_with_logging([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(out_main)], job, "Füge Intro, Predigt & Outro zusammen", 72, 80, total_duration=total_dur)
        else:
            if predigt_temp != out_main: shutil.copy(str(predigt_temp), str(out_main))

        job["pct"] = 80

        clip_start = slides[0][1] if slides else 60.0
        clip_dur = 60.0
        if clip_start + clip_dur > total_dur: clip_start = max(0.0, total_dur - clip_dur)

        cmd_short = [
            FF, "-y", "-ss", f"{clip_start}", "-t", f"{clip_dur}", "-i", str(src),
            "-vf", "crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920,setsar=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac",
            str(out_short)
        ]
        run_ffmpeg_with_logging(cmd_short, job, "Rendere Social Media Short (9:16)...", 82, 99, total_duration=clip_dur)

        job.update(state="done", pct=100, msg="Fertig!", files=[out_main.name, out_short.name])
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, data, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send((BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/favicon.png":
            fav = BASE / "favicon.png"
            if fav.exists(): return self.send(fav.read_bytes(), "image/png")
        if path.startswith("/cancel/"):
            jid = path[8:]
            if jid in JOBS: JOBS[jid]["state"] = "cancelled"
            return self.send(b'{"ok":true}')
        if path.startswith("/status/"):
            return self.send(json.dumps(JOBS.get(path[8:], {"state": "error", "msg": "Unbekannt"})).encode())
        if path.startswith("/video/"):
            sid_part = path[7:]
            d = WORK / sid_part
            if d.exists():
                v_files = list(d.glob("video.*"))
                if v_files:
                    vf = v_files[0]
                    file_size = vf.stat().st_size
                    range_header = self.headers.get('Range')
                    
                    if range_header:
                        m = re.search(r'bytes=(\d+)-(\d*)', range_header)
                        if m:
                            start = int(m.group(1))
                            end = int(m.group(2)) if m.group(2) else file_size - 1
                            if start >= file_size:
                                self.send_error(416, "Requested Range Not Satisfiable")
                                self.send_header("Content-Range", f"bytes */{file_size}")
                                self.end_headers()
                                return
                            end = min(end, file_size - 1)
                            length = end - start + 1
                            
                            self.send_response(206)
                            self.send_header("Content-Type", "video/mp4")
                            self.send_header("Content-Length", str(length))
                            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                            self.send_header("Accept-Ranges", "bytes")
                            self.end_headers()
                            
                            with open(vf, "rb") as fh:
                                fh.seek(start)
                                remaining = length
                                while remaining > 0:
                                    chunk_size = min(remaining, 1<<20)
                                    c = fh.read(chunk_size)
                                    if not c: break
                                    self.wfile.write(c)
                                    remaining -= len(c)
                            return
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(file_size))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    with open(vf, "rb") as fh: shutil.copyfileobj(fh, self.wfile, 1<<20)
                    return
        f = OUT / Path(path).name
        if path.startswith("/fertig/") and f.exists():
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
            self.end_headers()
            with open(f, "rb") as fh: shutil.copyfileobj(fh, self.wfile, 1<<20)
            return
        self.send_error(404)

    def do_PUT(self):
        _, _, sid, name = self.path.split("/", 3)
        clean = lambda x: re.sub(r"[^\w.\-]", "_", Path(x).name)
        d = WORK / clean(sid)
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(clean(name).split(".")[0] + ".*"): old.unlink()
        n = int(self.headers["Content-Length"])
        with open(d / clean(name), "wb") as f:
            while n > 0:
                c = self.rfile.read(min(n, 1<<20))
                if not c: break
                f.write(c)
                n -= len(c)
        self.send(b'{"ok":true}')

    def do_POST(self):
        p = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p["sid"] = re.sub(r"[^\w\-]", "_", p["sid"])
        auto = self.path == "/analyze"
        jid = p.get("jid") or (p["sid"] + ("a" if auto else ""))
        p["jid"] = jid
        JOBS[jid] = {"state": "run", "pct": 0, "msg": "Startet...", "files": [], "refs": []}
        threading.Thread(target=analyze if auto else process, args=(p,), daemon=True).start()
        self.send(b'{"ok":true}')

def main():
    global FF
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"Predigt-Cutter läuft: {url}\nDieses Fenster offen lassen.")
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    srv.serve_forever()

def bootstrap():
    py = VENV / ("Scripts/python.exe" in os.name and "Scripts/python.exe" or "bin/python") # fallback
    # ... bootstrap logic bleibt wie gehabt ...
