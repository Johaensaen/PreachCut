# PreachCut

A local, AI-assisted tool for editing sermon recordings. Speech recognition, Bible reference detection, and video rendering run completely locally on your computer.

> **Note on Language & Modularity:** PreachCut uses a modular language system. Out of the box, it supports **German** (`languages/de.json`) and **English**, but the community can easily add support for other languages by placing new JSON files into the `languages/` folder.

---

## Features

- **Local Speech Recognition & Verse Detection:** Automatically transcribes audio and recognizes Bible references based on the selected language profile.
- **Dynamic Language Selection & Persistence:** Select the sermon's audio recognition language (e.g., German, English) directly in the UI. UI language preferences (DE/EN) are automatically saved across browser sessions.
- **Interactive Multi-View Editing:** Choose between left/right split-screen or full-screen overlays for slides and verses.
- **Dual-Format Output:** Generates a 16:9 long-form video with embedded slides (`output/Sermon_Longversion_16x9.mp4`) and a cropped 9:16 portrait video optimized for social media (`output/Sermon_Highlight_Short_9x16.mp4`).
- **Smart Caching:** Fast re-rendering using local transcription caches (`work/`) without re-running heavy AI analysis.

---

## First-Time Setup & Installation

### Prerequisites
- **Python 3.9 or higher** installed on your system.
- **FFmpeg** (automatically managed via `imageio-ffmpeg` or installed on system PATH).
- An active internet connection for the **very first launch** (to download required Python packages and local AI models).

### Step-by-Step Guide

1. **Get the Code**
   Clone this repository or download and extract the ZIP archive:
   ```bash
   git clone https://github.com/YOUR-USERNAME/PreachCut.git
   cd PreachCut
   ```

2. **Launch the Application**
   Run the appropriate startup script for your operating system:
   - **Windows:** Double-click `Start.bat`
   - **macOS:** Double-click `Start.command` *(If prompted with permission warnings, run `chmod +x Start.command` in Terminal once)*
   - **Linux:** Run `python3 start.py` in your terminal

3. **Automatic Dependency Setup**
   On the first launch, the script automatically creates an isolated virtual environment (`.venv`), installs all required dependencies, and generates a default configuration (`config.json`).

4. **First AI Model Download**
   When you run your first video analysis, the local Whisper model (speech-to-text) and text model (~940 MB) will download automatically into the project directory.

5. **Open in Browser**
   Once started, your default web browser will automatically open:
   ```text
   http://localhost:8766
   ```
   *Keep the terminal window open while using the application.*

---

## Adding New Languages (Community Contributions)

PreachCut is fully modular regarding language support. All recognition keywords, numbers, and hints are stored externally in JSON files inside the `languages/` directory.

To easily generate a new language profile (e.g., English or Spanish):

1. **Run the Language Generator:**
   ```bash
   python3 create_language.py
   ```

2. **Follow the Prompts:** Enter the 2-letter language code (e.g., `en`, `es`) and a default prompt hint. A new pre-filled JSON template will be saved to `languages/<code >.json`.

3. **Customize Keywords:** Edit the created JSON file to refine Bible book names, abbreviations, and number words.

4. **Select in UI:** Your new language file will be automatically recognized and available in the UI dropdown selector upon restart or refresh.

---

## Workflow

1. **Upload Media & Select Language:** Select your sermon video and choose the speaker's language profile from the dropdown menu (e.g., German or English).
2. **Analyze Video:** Click **"High-Speed Analyse starten" / "Start AI Analysis"**. The app transcribes the audio, detects Bible references using the selected language rules, and prepares timestamps.
3. **Edit Verses & Slides:** Adjust verse timings, set slide layouts (*Left*, *Right*, or *Fullscreen*), or add custom memory points directly while playing the video preview.
4. **Quick Re-previews:** Use **"Schnelle Vorschauen erstellen"** to quickly update slide alignment and timings using cached transcription data without re-running the full AI model.
5. **Render & Export:** Render the final 16:9 long-form video and 9:16 highlight short.

---

## System Requirements & Notes

- **Hardware & RAM:** Around 3 GB of free RAM is recommended. Total rendering and transcription time depends heavily on your CPU/GPU hardware and video length.
- **Face Detection:** Automatically centers the largest detected face for 9:16 portrait crops. If multiple people are in the frame, tracking may follow the wrong person; unchecking face tracking defaults to a centered crop.
- **Power Management:** During analysis and rendering, the app temporarily prevents system sleep mode on supported OSs.
- **Offline Packages (Optional):** If you need to deploy PreachCut on an air-gapped machine without internet access, you can run `createOfflinePackages.bat` (Windows) or `createOfflinePackages.command` (macOS/Linux) *once* with internet access to bundle dependencies and models into `pakete/` and `modelle/`. For normal online setups, this is **not** required.
- **UI Customization:** Tailwind CSS styles are pre-compiled and bundled. Node.js/npm is only required if you plan to modify and recompile the frontend styles (`npm run build:css`).

---

## License & Third-Party Notices

This project is licensed under the **MIT License** – see the `LICENSE` file for details.

### Third-Party Software
PreachCut integrates several open-source libraries (such as FFmpeg via `imageio-ffmpeg`, `faster-whisper`, and OpenCV). Users are responsible for complying with the respective licenses of these third-party tools when using or building offline packages. See `THIRD_PARTY_NOTICES.md` for third-party component licenses.