#!/usr/bin/env python3
import json
from pathlib import Path

def main():
    print("========================================")
    print("   PreachCut Language File Generator   ")
    print("========================================")
    
    lang_code = input("Enter language code (e.g., 'en', 'es', 'fr'): ").strip().lower()
    if not lang_code:
        print("Error: Language code cannot be empty.")
        return

    whisper_lang = input(f"Enter Whisper language code (default '{lang_code}'): ").strip().lower() or lang_code
    
    default_hint = f"Sermon with Bible references: Genesis 1, Psalm 23, Isaiah 53, Matthew 5, John 3:16, Romans 8:28, Revelation."
    hint = input(f"Enter default AI hint/prompt [{default_hint}]: ").strip()
    if not hint:
        hint = default_hint

    # Template structure based on the modular schema
    template = {
        "language_code": lang_code,
        "whisper_language": whisper_lang,
        "hint": hint,
        "single_books": {
            "genesis": "Genesis",
            "exodus": "Exodus",
            "matthew": "Matthew",
            "mark": "Mark",
            "luke": "Luke",
            "john": "John",
            "revelation": "Revelation"
        },
        "numbered_books": {
            "samuel": "Samuel",
            "kings": "Kings",
            "chronicles": "Chronicles",
            "corinthians": "Corinthians",
            "timothy": "Timothy",
            "peter": "Peter"
        },
        "ordinals": {
            "first": 1,
            "second": 2,
            "third": 3,
            "fourth": 4,
            "fifth": 5
        },
        "units": {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19
        },
        "tens": {
            "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
            "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
        }
    }

    # Ensure languages directory exists
    lang_dir = Path(__file__).resolve().parent / "languages"
    lang_dir.mkdir(exist_ok=True)
    
    output_file = lang_dir / f"{lang_code}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    print(f"\n[Success] Language file created at: {output_file}")
    print(f"You can now test it by running: python3 start.py --lang {lang_code}")

if __name__ == "__main__":
    main()