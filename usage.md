The engine now takes a system record JSON and a borrower record JSON and returns a result JSON. The JSON route gives exactly the same results as the Excel/CSV route on both samples, and all 66 tests pass in a fresh install.

How to run it:

bash
pip install -e ".[test]"
python -m recon_engine resolve-json \
  --system samples/minimal/system_record.json \
  --borrower samples/minimal/borrower_record.json \
  --out result.json

From Python, e.g. in an ADK tool or a FastAPI route:

python
from recon_engine.json_io import resolve_records
result = resolve_records(system_record, borrower_record)  # dict, dict -> dict

The three JSON files:

system_record.json: the bank's lines exactly as LOB keyed them. Each line needs key, label and budget; paid_to_date and category are recommended.
borrower_record.json: the latest draw, with the same line fields plus this_draw. It can also carry the file's totals, which the lines must add up to.
result.json: has a status of COMPLETE, NEEDS_REVIEW or REJECTED, plus a list of decisions.
Each decision covers one matched group, so 3 borrower lines that add up to 1 system line is a single decision.
Each decision gives the rule, confidence, a plain-English reason, how each label was read, the next action, and the budget, paid-to-date and category checks with differences.
It also lists unmatched system lines, category totals and a fingerprint.

Rejected input: bad input is never guessed at. It comes back REJECTED, with the reason in input_checks: a missing budget, a non-numeric amount, lines that don't add up to the totals, or different loan IDs in the two records.

Demo run: the 9-line demo shows each kind of variance:

"Land Acq." resolved to Land Acquisition (abbreviation).
"Site Work - per CO #2" resolved to Sitework (note removed).
"Elecrtical" resolved to Electrical (typo).
"Drs & Windows" resolved to Doors & Windows (abbreviation).
"A&E + Survey" resolved to Architect + Engineering + Survey (summation).
Permits & Impact Fees matched, with the system budget flagged as a typo ($42,850 keyed for $48,250).
Solar PV System came back as NEW.

The result was identical across 20 runs with the lines shuffled into random order.

Also added:

JSON Schemas for all three files, in schemas/.
A to-json command that turns today's Excel/CSV files into the two input records.
A "Running it with JSON" section in the README and at the end of the doc.
