# Line-item category model (ACQUISITION / HARD / SOFT / OTHER) — model card

**Status:** trained on synthetic data only. Use it as a fallback behind the rules, with abstention, until it
has been measured on real labeled lines.

## What it is

- **Input:** a free-form budget-line label, the section heading above it (if any), and its share of the total budget.
- **Model:**
  - TF-IDF character 2–5-grams on the raw label (handles typos and abbreviations)
  - TF-IDF word 1–2-grams on the engine's normalized label
  - section-heading words
  - log budget share
  - all feeding a multinomial logistic regression with balanced class weights
- **Size and speed:** 568 KB; trains in about a minute on one CPU; predicts in well under a millisecond.
- **Where it is used:** only for lines whose category the deterministic path (cost-code dictionary, section heading, category words) left unknown. It never overrides a rule-based category.
- **When it abstains:**
  - the label has no word it learned ("Misc 1", "Item 7")
  - its confidence is below the threshold (default 0.9)

  Abstained lines go to review as `CATEGORY_UNKNOWN`.

## Training data (synthetic): `ml/synth.py`

- 600 synthetic developers, each with its own writing style: case, abbreviations, typo rate, notes, numbering, CSI division codes, combined lines, category prefixes, sections or none, and occasional wrong headings.
- 41,521 lines, 16,866 distinct labels, 77 underlying items:
  - HARD 18,036
  - SOFT 16,875
  - ACQUISITION 3,649
  - OTHER 2,961
- Deliberate hard cases:
  - bare ambiguous labels whose category comes only from context: Contingency, Closing costs, Title, Insurance, Fees
  - traps: "Interest reserve" is Soft (construction interest), not a reserve; "Environmental remediation" is Hard while a "Phase I environmental" report is Soft; "Performance bond" is Hard while "Bond issuance costs" are Soft

## Results

| Test | What it measures | Accuracy | Macro F1 | Ambiguous-word lines | At confidence ≥ 0.9: coverage / accuracy |
|---|---|---|---|---|---|
| Unseen developers, text only | New writing styles, known items | 98.7% | 0.988 | 96.2% | 97.3% / 99.99% |
| Unseen developers, with context | Same, plus section and amount | 99.8% | 0.998 | 99.3% | 99.0% / 99.99% |
| **Unseen items** | **Items never seen in any phrasing** | **94.0%** | 0.946 | 92.2% | **80.0% / 99.0%** |
| Sample files (94 lines) | This repo's borrower files and SOR exports | 98.9% | 0.994 | 100% | 97.9% / 98.9% |

**How to read this:**

- **The unseen-developer scores are optimistic.** Those developers write differently, but about the same items the model trained on.
- **The unseen-items test is the honest number for vocabulary the model hasn't met:** 94% raw, and 99% on the 80% of lines it is confident about. The abstention threshold does its job.
- **The sample-file check is not independent:** the same author wrote both the vocabulary and the samples. Its one error, "Misc 1", is now caught by the abstention guard.
- **Typical errors on unseen items:** contingency without a "soft" or "hard" word (the model leans Soft), "lease-up reserve" read as Soft, and lines whose section heading is wrong. Contingency is the class to watch.

**Behavior on tricky labels** (threshold 0.9):

| Label | Section | Result |
|---|---|---|
| Misc 1 / Item 7 | none | Abstains: no recognizable words |
| Closing costs | none | Abstains (0.57) |
| Closing costs | ACQUISITION | ACQUISITION (0.99) |
| Contingency | HARD COSTS / SOFT COSTS | HARD (0.997) / SOFT (0.973) |
| Interest reserve | none | SOFT (0.95) |
| Elevatr | none | HARD (0.98) |
| Third party reports, at 0.3% vs 4.3% of the budget | none | SOFT (0.98) vs abstains (0.66): an implausible amount lowers confidence |

## Limits (be explicit about these)

- The vocabulary and the noise are one author's model of how budgets are written. Real labels will contain items and habits that aren't covered. Accuracy on your data is **unknown** until it is measured.
- The budget-share feature reflects typical HFA development budgets. Unusual deals (acquisition-heavy rehabs, for example) may lower confidence, which means more abstentions rather than wrong answers.
- A category drives source eligibility and category tie-outs. Keep model-assigned categories behind review until real-data accuracy is known.

## Getting to production

1. **Harvest real labels at no cost:**
   ```bash
   python ml/harvest_real_labels.py --borrower-dir <draw files> --sor-dir <SOR exports>
   ```
   Lines under section headings become labels. Disagreements with SOR categories go to a file for adjudication; those are the most valuable examples.
2. **Hand-label a test set** of 300–500 real lines from loans and developers not used in training. Weight it toward contingency, fees, insurance and closing costs.
3. **Retrain on real plus synthetic data** and compare on that test set:
   ```bash
   python ml/train.py --extra ml/data/real/real_line_items.csv
   ```
   As real data grows, reduce the synthetic share.
4. **Set the threshold** from the real coverage and accuracy curve, then enable the model in `config/settings.json`:
   ```json
   "ml_category": {"model": "ml/model/category_model.joblib", "min_confidence": 0.9}
   ```
5. **Retrain** on reviewer corrections every cycle, and monitor accuracy and the abstention rate in Arize, like the extraction metrics.
