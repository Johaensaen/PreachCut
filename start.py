#!/usr/bin/env python3
import atexit, gc, json, mimetypes, os, re, shutil, signal, subprocess, sys, threading, time, traceback, venv, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from media_ai import ensure_face_model, prepare_models, suggest_highlights, track_speaker_centers, vertical_crop_filter

BASE = Path(__file__).resolve().parent
VENV, WORK, OUT = BASE / ".venv", BASE / "arbeit", BASE / "fertig"
JOBS_DIR = BASE / "auftraege"
MODEL_DIR = BASE / "modelle"
PORT = 8766
JOBS, FF = {}, "ffmpeg"
JOB_PAYLOADS, JOB_TYPES = {}, {}
ACTIVE_JOBS = set()
JOB_LOCK = threading.RLock()
UPLOAD_LOCK = threading.Lock()
REQUIRED_PACKAGES = ["imageio-ffmpeg", "faster-whisper", "av==16.1.0", "gpt4all==2.8.2", "opencv-python-headless==4.13.0.92"]
MAX_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
HINT = "Predigt mit Bibelstellen: 1. Mose 1, Psalm 23, Jesaja 53, Matthäus 5, Johannes 3,16, Römer 8,28, Offenbarung."
_AWAKE_LOCK = threading.Lock()
_AWAKE_COUNT = 0
_AWAKE_PROCESS = None
_AWAKE_STOP_EVENT = None
_AWAKE_THREAD = None

def _start_awake_inhibitor():
    global _AWAKE_PROCESS, _AWAKE_STOP_EVENT, _AWAKE_THREAD
    if os.name == "nt":
        import ctypes

        stop_event = threading.Event()
        def keep_windows_awake():
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            set_execution_state = kernel.SetThreadExecutionState
            set_execution_state.argtypes = [ctypes.c_uint]
            set_execution_state.restype = ctypes.c_uint
            continuous, system_required, display_required = 0x80000000, 0x00000001, 0x00000002
            state = continuous | system_required | display_required
            while True:
                if not set_execution_state(state):
                    print(f"Ruhemodus-Sperre fehlgeschlagen: {ctypes.get_last_error()}")
                    return
                if stop_event.wait(30):
                    set_execution_state(continuous)
                    return

        _AWAKE_STOP_EVENT = stop_event
        _AWAKE_THREAD = threading.Thread(target=keep_windows_awake, daemon=True)
        _AWAKE_THREAD.start()
        return True

    if sys.platform == "darwin":
        command = shutil.which("caffeinate")
        if command:
            _AWAKE_PROCESS = subprocess.Popen([command, "-di"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    if sys.platform.startswith("linux"):
        inhibitor, sleeper = shutil.which("systemd-inhibit"), shutil.which("sleep")
        if inhibitor and sleeper:
            _AWAKE_PROCESS = subprocess.Popen(
                [inhibitor, "--what=idle:sleep", "--mode=block", "--why=Gottesdienst-Video-Cutter arbeitet", sleeper, "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
            )
            time.sleep(0.2)
            if _AWAKE_PROCESS.poll() is None:
                return True
            _AWAKE_PROCESS = None

    print("Hinweis: Für dieses System wurde keine Ruhemodus-Sperre gefunden.")
    return False

def _stop_awake_resources(process, stop_event, thread):
    if stop_event:
        stop_event.set()
    if thread and thread is not threading.current_thread():
        thread.join(timeout=2)
    if process and process.poll() is None:
        try:
            if sys.platform.startswith("linux"):
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

def _stop_awake_inhibitor():
    global _AWAKE_COUNT, _AWAKE_PROCESS, _AWAKE_STOP_EVENT, _AWAKE_THREAD
    with _AWAKE_LOCK:
        _AWAKE_COUNT = 0
        resources = (_AWAKE_PROCESS, _AWAKE_STOP_EVENT, _AWAKE_THREAD)
        _AWAKE_PROCESS = _AWAKE_STOP_EVENT = _AWAKE_THREAD = None
    _stop_awake_resources(*resources)

def acquire_awake():
    global _AWAKE_COUNT
    with _AWAKE_LOCK:
        if _AWAKE_COUNT == 0:
            _start_awake_inhibitor()
        _AWAKE_COUNT += 1

def release_awake():
    global _AWAKE_COUNT, _AWAKE_PROCESS, _AWAKE_STOP_EVENT, _AWAKE_THREAD
    with _AWAKE_LOCK:
        if _AWAKE_COUNT == 0:
            return
        _AWAKE_COUNT -= 1
        if _AWAKE_COUNT > 0:
            return
        resources = (_AWAKE_PROCESS, _AWAKE_STOP_EVENT, _AWAKE_THREAD)
        _AWAKE_PROCESS = _AWAKE_STOP_EVENT = _AWAKE_THREAD = None
    _stop_awake_resources(*resources)

def save_job(jid):
    with JOB_LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        record = {
            "jid": jid,
            "type": JOB_TYPES.get(jid, "process"),
            "job": dict(job),
            "payload": JOB_PAYLOADS.get(jid, {})
        }
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        target = JOBS_DIR / f"{jid}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)

def load_saved_jobs():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for path in JOBS_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            jid, job = record["jid"], record["job"]
            if job.get("state") == "run":
                job.update(state="interrupted", msg="Die Anwendung wurde während dieses Auftrags beendet.")
            JOBS[jid] = job
            JOB_PAYLOADS[jid] = record.get("payload", {})
            JOB_TYPES[jid] = record.get("type", "process")
            if job.get("state") == "interrupted":
                save_job(jid)
        except (OSError, ValueError, KeyError, TypeError):
            print(f"Überspringe beschädigten Auftrag: {path.name}")

def run_job(target, payload):
    jid = payload["jid"]
    stop_heartbeat = threading.Event()
    def persist_progress():
        while not stop_heartbeat.wait(3):
            save_job(jid)

    heartbeat = threading.Thread(target=persist_progress, daemon=True)
    heartbeat.start()
    try:
        target(payload)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=1)
        save_job(jid)
        with JOB_LOCK:
            ACTIVE_JOBS.discard(jid)
        release_awake()

atexit.register(_stop_awake_inhibitor)

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

def format_media_time(seconds):
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"

def run_ffmpeg_with_logging(cmd, job, desc, start_pct, end_pct, total_duration=None):
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    print(f"\n--- [AUSFÜHRUNG] {desc} ---")
    print(" ".join(cmd))
    job["msg"] = desc
    job["pct"] = start_pct
    process_options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "close_fds": True
    }
    if os.name != "nt":
        process_options["preexec_fn"] = os.setsid
    process = subprocess.Popen(cmd, **process_options)
    
    received_sigterm = False
    for line in process.stdout:
        if job.get("state") == "cancelled":
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    process.terminate()
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        process.kill()
                else:
                    process.kill()
                process.wait()
            raise InterruptedError("Abgebrochen")
        stripped = line.strip()
        if stripped:
            print(f"[{desc}] {stripped}")
            received_sigterm = received_sigterm or "received signal 15" in stripped.lower()
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", stripped)
            if m and total_duration and total_duration > 0:
                cur_sec = int(m[1])*3600 + int(m[2])*60 + float(m[3])
                ratio = min(1.0, cur_sec / total_duration)
                job["pct"] = start_pct + (end_pct - start_pct) * ratio
                job["msg"] = f"{desc} · {format_media_time(cur_sec)} / {format_media_time(total_duration)}"

    ret = process.wait()
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    if ret in (-signal.SIGTERM, 255) and received_sigterm:
        raise InterruptedError("FFmpeg wurde durch SIGTERM unterbrochen.")
    if ret != 0:
        raise RuntimeError(f"{desc} fehlgeschlagen mit Code {ret}")
    job["pct"] = end_pct

def analyze(p):
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    try:
        videos = list(d.glob("video.*"))
        if not videos:
            raise FileNotFoundError("Das Predigtvideo ist nicht angekommen. Bitte Datei erneut auswählen und den Upload abwarten.")
        video_path = videos[0]
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

        segs, info = model.transcribe(str(video_path), language="de", vad_filter=True, word_timestamps=True, initial_prompt=full_prompt)
        
        words = []
        all_word_objs = []
        for sg in segs:
            if job.get("state") == "cancelled": return
            for w in (sg.words or []):
                w_text = w.word.strip()
                words.append((w.start, w_text))
                all_word_objs.append({"start": w.start, "end": w.end, "word": w_text})
            job["pct"] = min(78, round(78 * sg.end / max(info.duration, 1)))
            job["msg"] = f"Erkenne Bibelstellen... {int(sg.end // 60)} / {int(info.duration // 60)} Min."
            
        with open(d / "words.json", "w", encoding="utf-8") as wf:
            json.dump(all_word_objs, wf, ensure_ascii=False)

        duration = info.duration
        refs = find_refs(words)
        del model, segs
        gc.collect()
        job["msg"] = "Erstelle drei Highlight-Vorschläge mit dem lokalen Textmodell..."
        job["pct"] = 80
        def candidate_progress(message, done, total):
            if job.get("state") == "cancelled":
                raise InterruptedError("Abgebrochen")
            job["msg"] = message
            if total:
                job["pct"] = min(98, 80 + round(18 * done / total))
        candidates = suggest_highlights(all_word_objs, refs, duration, MODEL_DIR, candidate_progress)
        job.update(state="done", pct=100, msg="Analyse fertig.", refs=refs, candidates=candidates)
    except Exception as e:
        if job.get("state") != "cancelled":
            if not isinstance(e, FileNotFoundError):
                traceback.print_exc()
            job.update(state="error", msg=str(e))

def process(p):
    sid, job, d = p["sid"], JOBS[p["jid"]], WORK / p["sid"]
    try:
        preview = p.get("stage") == "preview"
        src = next(d.glob("video.*"))
        total_dur = probe(src)
        out_main = OUT / f"{sid}_{'Vorschau' if preview else 'Predigt'}_Langversion_16x9.mp4"

        intro_file = list(d.glob("intro.*"))
        outro_file = list(d.glob("outro.*"))
        has_intro, has_outro = len(intro_file) > 0, len(outro_file) > 0

        job["msg"] = "Starte Videoschnitt..."
        job["pct"] = 5

        items = p.get("items", [])
        # Nur Items berücksichtigen, bei denen auch tatsächlich eine Bilddatei zugewiesen wurde
        slides = []
        for i in items:
            if i.get("file"):
                fpath = d / i["file"]
                if fpath.exists():
                    slides.append((fpath, max(float(i["t"]), 0), min(float(i["t"]) + float(i["d"]), total_dur), i.get("side", "right")))

        full_width, full_height = (854, 480) if preview else (1920, 1080)
        half_width = full_width // 2
        fit_full = f"scale={full_width}:{full_height}:force_original_aspect_ratio=decrease,pad={full_width}:{full_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        fit_half = f"scale={half_width}:{full_height}:force_original_aspect_ratio=decrease,pad={half_width}:{full_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        quality = "34" if preview else "23"
        enc_fast = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", quality, "-c:a", "aac", "-b:a", "96k" if preview else "128k", "-movflags", "+faststart"]

        predigt_temp = d / ("temp_vorschau.mp4" if preview else "temp_predigt.mp4")

        if slides:
            cmd = [FF, "-y", "-hide_banner", "-i", str(src)]
            for f, _, _, _ in slides: cmd += ["-loop", "1", "-framerate", "25", "-t", f"{total_dur}", "-i", str(f)]
            
            parts = [f"[0:v]{fit_full},fps=25[bg]"]
            speaker_indices = [k for k, (_, _, _, side) in enumerate(slides) if side != "fullscreen"]
            speaker_labels = {slide_index: f"speaker_half_{stream_index}" for stream_index, slide_index in enumerate(speaker_indices)}
            if speaker_indices:
                parts.append(f"[0:v]{fit_half},fps=25[speaker_base]")
                parts.append(f"[speaker_base]split={len(speaker_indices)}" + "".join(f"[{speaker_labels[k]}]" for k in speaker_indices))
            for k, (_, _, _, side) in enumerate(slides):
                fit_slide = fit_full if side == "fullscreen" else fit_half
                size_label = "full" if side == "fullscreen" else "half"
                parts.append(f"[{k+1}:v]{fit_slide},fps=25[slide_{size_label}_{k}]")
            
            cur = "bg"
            for k, (_, a, b, side) in enumerate(slides):
                if side == "left":
                    parts.append(f"[{cur}][slide_half_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][{speaker_labels[k]}]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                elif side == "fullscreen":
                    parts.append(f"[{cur}][slide_full_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                else: # right
                    parts.append(f"[{cur}][{speaker_labels[k]}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][slide_half_{k}]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                cur = f"v{k}"
            parts.append(f"[{cur}]null[out]")

            cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-map", "0:a?"] + enc_fast + [str(predigt_temp)]
            run_ffmpeg_with_logging(cmd, job, f"Rendere Split-Screen Langversion ({len(slides)} Folien)...", 10, 55, total_duration=total_dur)
        elif preview:
            cmd = [FF, "-y", "-i", str(src), "-vf", f"{fit_full},fps=25", "-map", "0:v:0", "-map", "0:a?"] + enc_fast + [str(predigt_temp)]
            run_ffmpeg_with_logging(cmd, job, "Erstelle schnelle 16:9-Vorschau...", 10, 55, total_duration=total_dur)
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

        highlights = p.get("highlights", [])
        output_files = [out_main.name]
        crop_paths = []
        crop_sources = []
        for index, highlight in enumerate(highlights):
            clip_start = min(max(float(highlight.get("t", 0)), 0), max(0, total_dur - 1))
            clip_dur = min(max(float(highlight.get("d", 45)), 1), 180, total_dur - clip_start)
            centers = highlight.get("crop_centers") or []
            if preview or not centers:
                try:
                    face_model = ensure_face_model(MODEL_DIR, lambda message, done, total: job.update(msg=message))
                    centers = track_speaker_centers(src, FF, clip_start, clip_dur, face_model, d)
                except Exception as error:
                    print(f"Sprechererkennung nicht verfügbar, verwende Bildmitte: {error}")
                    centers = []
            crop_paths.append(centers)
            crop_sources.append("Gesicht verfolgt" if centers else "Bildmitte (kein Gesicht erkannt)")
            stage_name = "Vorschau" if preview else "Predigt"
            out_short = OUT / f"{sid}_{stage_name}_Highlight_{index + 1:02d}_9x16.mp4"
            output_width = 540 if preview else 1080
            cmd_short = [
                FF, "-y", "-ss", f"{clip_start}", "-t", f"{clip_dur}", "-i", str(src),
                "-vf", vertical_crop_filter(centers, output_width),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", quality, "-c:a", "aac",
                str(out_short)
            ]
            start_pct = 80 + int(19 * index / max(len(highlights), 1))
            end_pct = 80 + int(19 * (index + 1) / max(len(highlights), 1))
            title = highlight.get("title") or f"Highlight {index + 1}"
            run_ffmpeg_with_logging(
                cmd_short, job, f"{'Vorschau' if preview else 'Finalrender'} Hochkant {index + 1}/{len(highlights)}: {title}",
                start_pct, end_pct, total_duration=clip_dur
            )
            output_files.append(out_short.name)

        job.update(
            state="done", pct=100,
            msg="Vorschauen fertig." if preview else "Finalrender fertig!",
            files=output_files,
            crop_paths=crop_paths,
            crop_sources=crop_sources,
            preview_candidates=highlights if preview else [],
            highlight_titles=[item.get("title", "") for item in highlights]
        )
    except InterruptedError as e:
        if job.get("state") != "cancelled":
            job.update(state="interrupted", msg=str(e), files=[])
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, data, ctype="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send((BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            relative = Path(path[len("/static/"):])
            if ".." not in relative.parts:
                asset = BASE / "static" / relative
                if asset.is_file():
                    content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                    return self.send(asset.read_bytes(), content_type)
        if path == "/favicon.png":
            fav = BASE / "favicon.png"
            if fav.exists(): return self.send(fav.read_bytes(), "image/png")
        if path == "/jobs":
            with JOB_LOCK:
                jobs = [{
                    "jid": jid,
                    "sid": JOB_PAYLOADS.get(jid, {}).get("sid", ""),
                    "type": JOB_TYPES.get(jid, "process"),
                    "state": job.get("state"),
                    "msg": job.get("msg", ""),
                    "pct": job.get("pct", 0),
                    "files": job.get("files", []),
                    "updated": (JOBS_DIR / f"{jid}.json").stat().st_mtime if (JOBS_DIR / f"{jid}.json").exists() else 0
                } for jid, job in JOBS.items()]
                jobs.sort(key=lambda item: item["updated"], reverse=True)
            return self.send(json.dumps(jobs[:20], ensure_ascii=False).encode())
        if path.startswith("/cancel/"):
            jid = path[8:]
            with JOB_LOCK:
                job = JOBS.get(jid)
                if job and jid in ACTIVE_JOBS and job.get("state") == "run":
                    job.update(state="cancelled", msg="Abbruch angefordert.")
                    save_job(jid)
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
        if path.startswith("/vorschau/"):
            name = Path(path[len("/vorschau/"):]).name
            if re.fullmatch(r"session_[\w-]+_Vorschau_[\w.-]+\.mp4", name):
                preview_file = OUT / name
                if preview_file.is_file():
                    file_size = preview_file.stat().st_size
                    range_header = self.headers.get("Range")
                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header or "")
                    if range_header and not match:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.end_headers()
                        return
                    if match:
                        start = int(match.group(1))
                        end = int(match.group(2)) if match.group(2) else file_size - 1
                        if start >= file_size:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{file_size}")
                            self.end_headers()
                            return
                        end = min(end, file_size - 1)
                        self.send_response(206)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                        start_at, length = start, end - start + 1
                    else:
                        self.send_response(200)
                        start_at, length = 0, file_size
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    with open(preview_file, "rb") as video:
                        video.seek(start_at)
                        remaining = length
                        while remaining > 0:
                            chunk = video.read(min(remaining, 1 << 20))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
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
        parts = urlparse(self.path).path.split("/", 3)
        if len(parts) != 4 or parts[1] != "upload":
            return self.send(b'{"error":"Ungueltiger Uploadpfad."}', status=404)
        _, _, sid, name = parts
        clean = lambda x: re.sub(r"[^\w.\-]", "_", Path(x).name)
        d = WORK / clean(sid)
        d.mkdir(parents=True, exist_ok=True)
        if "Content-Length" not in self.headers:
            return self.send(b'{"error":"Uploadgroesse fehlt."}', status=411)
        expected = int(self.headers["Content-Length"])
        if expected <= 0:
            return self.send(b'{"error":"Die Datei ist leer."}', status=400)
        target = d / clean(name)
        content_range = self.headers.get("Content-Range")
        if content_range:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
            if not match:
                return self.send(b'{"error":"Ungueltiger Teil-Upload."}', status=400)
            start, end, total = map(int, match.groups())
            if start > end or end >= total or end - start + 1 != expected:
                return self.send(b'{"error":"Teil-Uploadgroesse stimmt nicht."}', status=400)
            if expected > MAX_UPLOAD_CHUNK_SIZE:
                return self.send(b'{"error":"Upload-Teil ist zu gross."}', status=413)
            temporary = d / f".{target.name}.upload"
            with UPLOAD_LOCK:
                current = temporary.stat().st_size if temporary.exists() else 0
                if current != start:
                    return self.send(json.dumps({"error": "Uploadposition stimmt nicht.", "received": current}).encode(), status=409)
                remaining = expected
                try:
                    with open(temporary, "ab" if start else "wb") as destination:
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 1 << 20))
                            if not chunk:
                                break
                            destination.write(chunk)
                            remaining -= len(chunk)
                    if remaining:
                        return self.send(b'{"error":"Upload-Teil unvollstaendig empfangen."}', status=400)
                    received = end + 1
                    complete = received == total
                    if complete:
                        temporary.replace(target)
                        for old in d.glob(f"{target.stem}.*"):
                            if old != target and old.is_file():
                                old.unlink()
                except OSError:
                    temporary.unlink(missing_ok=True)
                    return self.send(b'{"error":"Datei konnte nicht gespeichert werden."}', status=500)
            return self.send(json.dumps({"ok": True, "bytes": expected, "received": received, "complete": complete}).encode())

        temporary = d / f".{target.name}.{threading.get_ident()}.part"
        with UPLOAD_LOCK:
            remaining = expected
            try:
                with open(temporary, "wb") as destination:
                    while remaining > 0:
                        chunk = self.rfile.read(min(remaining, 1 << 20))
                        if not chunk:
                            break
                        destination.write(chunk)
                        remaining -= len(chunk)
                if remaining:
                    temporary.unlink(missing_ok=True)
                    return self.send(b'{"error":"Upload unvollstaendig empfangen."}', status=400)
                temporary.replace(target)
                for old in d.glob(f"{target.stem}.*"):
                    if old != target and old.is_file():
                        old.unlink()
            except OSError:
                temporary.unlink(missing_ok=True)
                return self.send(b'{"error":"Datei konnte nicht gespeichert werden."}', status=500)
        return self.send(json.dumps({"ok": True, "bytes": expected}).encode())

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/resume/"):
            jid = path[8:]
            with JOB_LOCK:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", jid) or jid not in JOBS or JOBS[jid].get("state") not in ("interrupted", "error"):
                    return self.send(json.dumps({"error": "Auftrag kann nicht gestartet werden."}).encode(), "application/json", 409)
                if jid in ACTIVE_JOBS:
                    return self.send(json.dumps({"error": "Dieser Auftrag läuft bereits."}).encode(), "application/json", 409)
                ACTIVE_JOBS.add(jid)
                payload = JOB_PAYLOADS[jid]
                JOBS[jid].update(state="run", pct=0, msg="Auftrag wird erneut gestartet.")
                save_job(jid)
            acquire_awake()
            job_type = JOB_TYPES.get(jid)
            target = analyze if job_type == "analyze" else process
            try:
                threading.Thread(target=run_job, args=(target, payload), daemon=True).start()
            except Exception:
                with JOB_LOCK:
                    ACTIVE_JOBS.discard(jid)
                    JOBS[jid].update(state="error", msg="Auftrag konnte nicht gestartet werden.")
                    save_job(jid)
                release_awake()
                raise
            return self.send(b'{"ok":true}')

        p = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p["sid"] = re.sub(r"[^\w\-]", "_", p["sid"])
        auto = path == "/analyze"
        preview = path == "/preview"
        jid = re.sub(r"[^\w\-]", "_", p.get("jid") or (p["sid"] + ("a" if auto else "")))
        p["jid"] = jid
        with JOB_LOCK:
            if jid in ACTIVE_JOBS:
                return self.send(json.dumps({"error": "Dieser Auftrag läuft bereits."}).encode(), "application/json", 409)
            JOBS[jid] = {"state": "run", "pct": 0, "msg": "Startet...", "files": [], "refs": []}
            JOB_PAYLOADS[jid] = p
            JOB_TYPES[jid] = "analyze" if auto else "preview" if preview else "final" if p.get("stage") == "final" else "process"
            ACTIVE_JOBS.add(jid)
            save_job(jid)
        acquire_awake()
        try:
            threading.Thread(target=run_job, args=(analyze if auto else process, p), daemon=True).start()
        except Exception:
            with JOB_LOCK:
                ACTIVE_JOBS.discard(jid)
                JOBS[jid].update(state="error", msg="Auftrag konnte nicht gestartet werden.")
                save_job(jid)
            release_awake()
            raise
        self.send(b'{"ok":true}')

def main():
    global FF
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    load_saved_jobs()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"Predigt-Cutter läuft: {url}\nDieses Fenster offen lassen.")
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    srv.serve_forever()

def bootstrap():
    py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.prefix).resolve() != VENV.resolve():
        marker = VENV / ".ok"
        if not marker.exists() or marker.read_text(encoding="utf-8").strip() != "3":
            print("Erster Start: Installiere Pakete...")
            if not py.exists(): venv.create(VENV, with_pip=True)
            wheels = BASE / "pakete"
            subprocess.check_call([str(py), "-m", "pip", "install", "-q"] + (["--no-index", "--find-links", str(wheels)] if wheels.exists() else []) + REQUIRED_PACKAGES)
            marker.write_text("3")
        sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *sys.argv[1:]]))

def prepare_offline():
    wheels = BASE / "pakete"
    wheels.mkdir(exist_ok=True)
    print("Lade Python-Pakete für dieses Betriebssystem herunter...")
    subprocess.check_call([sys.executable, "-m", "pip", "download", "--dest", str(wheels), *REQUIRED_PACKAGES])
    print("Lade lokale KI-Modelle herunter...")
    prepare_models(MODEL_DIR, lambda message, done, total: print(message))
    print("Vorbereitung abgeschlossen. Das Paket ist für dieses Betriebssystem und diese Python-Version vorbereitet.")

if __name__ == "__main__":
    if "--vorbereiten" in sys.argv:
        prepare_offline()
    else:
        bootstrap()
        main()