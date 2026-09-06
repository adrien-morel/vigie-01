"""Manual annotation of pairs: do these two items deal with the same story? (§7, §10 V3)

Usage (interactive terminal): python -m backend.eval.annotate_pairs
Saves after every pair — interruptible and resumable.

The judgement rule, to be held constant across the whole sample: "same story" means same parties and
same operation (the acceptance criterion of §10 V3 slice 1), not same theme. Two distinct strikes in
the same war, two distinct contracts with the same manufacturer, two distinct exercises by the same
navy: shared theme, different stories — so "no". That is the boundary the threshold has to learn to
place; widening it to the theme would make the measurement useless, since almost the whole corpus
shares a theme.
"""

import json
import sys
from pathlib import Path

PAIRS_FILE = Path(__file__).parent / "pairs.json"

# Same fix as in score.py: the Windows console runs cp1252 and cannot write accented titles or box
# characters, which used to interrupt the display part-way through a pair.
sys.stdout.reconfigure(encoding="utf-8")


def _show_side(label: str, side: dict) -> None:
    print(f"  {label} ({side['source']}, {side['date']}, {side['category']})")
    print(f"     {side['title_en']}")
    summary = side.get("summary", "")
    if summary:
        print(f"     {summary[:300]}")


def main() -> None:
    rows = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
    todo = [r for r in rows if r["same_dossier"] is None]

    if not todo:
        print("Everything is already annotated. Run: python -m backend.eval.score_pairs")
        return

    print(f"{len(todo)} pairs to annotate out of {len(rows)}. Ctrl+C to stop, resumes automatically after.\n")
    print("Question: are the two items about the SAME STORY (same parties, same operation)?")
    print("  y = yes   n = no   ? = unsure (counted separately, never as a success)")
    print("  link = show both URLs\n")

    for row in todo:
        print("=" * 88)
        if row["kind"] == "thread":
            origin = f"thread {row['thread_id'][:8]} (size {row['thread_size']})"
        else:
            origin = f"IDF band {row['band']}"
        weight = "—" if row["idf_weight"] is None else f"{row['idf_weight']:.1f}"
        print(f"[{row['id']}] {origin} — IDF score {weight}")
        if row["shared_tokens"]:
            print(f"  shared tokens: {', '.join(row['shared_tokens'])}")
        print()
        _show_side("A", row["a"])
        print()
        _show_side("B", row["b"])
        print()
        while True:
            choice = input("Same story? (y/n/?/link): ").strip().lower()
            if choice == "link":
                print(f"  A: {row['a']['link']}")
                print(f"  B: {row['b']['link']}")
                continue
            if choice in ("y", "n", "?"):
                row["same_dossier"] = {"y": True, "n": False, "?": "unsure"}[choice]
                break
            print("Invalid entry.")

        PAIRS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nAnnotation finished. Run: python -m backend.eval.score_pairs")


if __name__ == "__main__":
    main()
