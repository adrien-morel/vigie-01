"""Manual annotation of the sample, to measure classification precision (§7).

Usage (interactive terminal): python -m backend.eval.annotate
Saves after every item — interruptible and resumable.

**Annotation is blind by default**: the system's classification is not shown before the human
judgement is entered. It was shown until 2026-08-22, and that was an anchoring bias on the very
measurement this script underpins — seeing a verdict before judging pushes towards agreement, and so
inflates the measured precision in the convenient direction. The §7 KPI being the product's quality
claim, it must be measured against a judgement formed independently. `--show-system` restores the old
behaviour, to replay an annotation under the conditions of an earlier measurement — but a figure
produced that way is not comparable to a figure produced blind, and must not be presented alongside it
without saying so.
"""

import argparse
import json
from pathlib import Path

SAMPLE_FILE = Path(__file__).parent / "sample.json"

CATEGORIES = [
    "export_control",
    "arms_contract",
    "military_movement",
    "defense_diplomacy",
    "industrial_program",
    "out_of_scope",
]

# A digest of the "Boundary clarifications" of docs/scoping.md §4 — the normative part of that
# document, not its log. Recalled here on demand because those rules were written *after* disagreements
# observed during annotation: having them to hand at the moment of deciding is what makes two
# annotation sessions comparable. In case of doubt, the text of §4 governs.
BORDER_RULES = """
Boundary clarifications (docs/scoping.md §4 — digest; the full text governs)

  Merger, acquisition or equity stake in defence
    - the transaction itself (parties, amount, sovereignty stake) ....... industrial_program
    - explicit licence, sanction or embargo procedure ................... export_control
    - centred on the share price or the market reaction ................. out_of_scope

  Opinion, op-ed, forward-looking analysis
    - reports no dated, verifiable fact ................................. out_of_scope
    - reports a dated fact and adds analysis to it ...................... included (category of the fact)

  defense_diplomacy vs military_movement — the most frequent confusion
    The split is about the CONTENT of what is declared, not the form of the act.
    - accomplished operational fact or established state of affairs
      (force deployed, strait closed or under control, strike carried
      out) .............................................................. military_movement
      -> including when reported through an official communique: the
         statement is then the source that establishes the fact, not the subject
    - intention, threat, claimed capability, posture, defence
      cooperation between states ........................................ defense_diplomacy
    - joint exercise ALREADY UNDER WAY (troops deployed, manoeuvres in
      progress), even in the vocabulary of cooperation/interoperability .. military_movement
    - agreement or intention to cooperate, no exercise yet under way .... defense_diplomacy
    "Declaring that a strait is controlled" and "threatening to close it" are not the same act.

  defense_diplomacy vs out_of_scope
    - statement or communique by a named official on cooperation,
      alliances or defence/security posture .............................. defense_diplomacy
      -> that is a dated fact; do not discard it on the ground that no
         contract or movement is described
    - state visit, protocol message, general diplomatic pressure with no
      explicit defence/security content ................................. out_of_scope
"""


def main(show_system: bool) -> None:
    rows = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    todo = [r for r in rows if r["category_gold"] is None]

    if not todo:
        print("Everything is already annotated. Run: python -m backend.eval.score")
        return

    done = len(rows) - len(todo)
    print(f"{len(todo)} items to annotate out of {len(rows)}. Ctrl+C to stop, resumes automatically after.")
    if show_system:
        print("/!\\ --show-system: the system's classification is displayed. Anchored measurement, so not")
        print("    comparable to a blind annotation — say so when quoting the figure.")
    else:
        print("Blind annotation: the system's classification is not shown (see the docstring).")
    print()
    print("Categories:")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"  {i}. {cat}")
    print("\nType 'rules' for the §4 boundary clarifications, 'link' for the article URL.\n")

    for offset, row in enumerate(todo, 1):
        print("=" * 80)
        print(f"[{done + offset}/{len(rows)}] [{row['id']}] {row['source']} — {row['title']}")
        print(f"\n{row['text_excerpt']}\n")
        if show_system:
            print(f"(the system classified this as: {row['category_system']})")
        while True:
            choice = input("Actual category (1-6, 'rules', 'link'): ").strip()
            if choice.lower() == "link":
                print(row["link"])
                continue
            if choice.lower() == "rules":
                print(BORDER_RULES)
                continue
            if choice.isdigit() and 1 <= int(choice) <= len(CATEGORIES):
                row["category_gold"] = CATEGORIES[int(choice) - 1]
                break
            print("Invalid entry.")

        SAMPLE_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nAnnotation finished. Run: python -m backend.eval.score")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--show-system",
        action="store_true",
        help="show the system's classification before the judgement (old behaviour, anchored measurement)",
    )
    args = parser.parse_args()
    main(args.show_system)
