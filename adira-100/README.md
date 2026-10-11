# Adira 100-point agent and Bid Desk demo

Added 2026-10-11 from Leonie's machine. Times are UTC.

## What is here

| Path | What it is |
|---|---|
| `Adira-sub_0b56513a87415065.tar.gz` | The exact package of the team's ranked submission `sub_0b56513a87415065` (quality 100, review passed, 549 s), downloaded with `atira package`. Do not edit. |
| `agent/` | The same code as a working copy, with two differences listed below. |
| `demo/adira-bid-desk.html` | Product demo page: paste tender, specification, mail and ERP text, check the extracted facts, see the bid with each pricing rule drawn as a picture. |

## Where the code comes from

- Base: the package of test run `run_cc7eef952fc218b1` (91.8), uploaded by a teammate.
- Fix: in `pricing.py`, a price condition in EUR is no longer multiplied by an exchange rate. In the 91.8 run, position 01.01 was EUR but carried a USD rate, which cost the base price, the unit price and the total.
- That fixed package scored 100 twice as a test run (`run_febff0987e5c68bb`, `run_1ca22839b65a69a0`). The first was promoted to the ranked submission.

## How `agent/` differs from the submitted package

1. The number-format examples in the prompts (`agent.py`, `pricing.py`) were replaced with made-up values (`100.000`, `1,234.56`). The submitted package uses an example that equals a real price of the public scenario.
2. `tests/test_kit.py` has two more tests for the EUR fix. Three older entry-point tests fail in the original package as well.

Test runs of `agent/` as it is here: 100, 91.1, 73.8.

## Scores vary from run to run

The same code does not score the same every time. The arithmetic is deterministic; the variation comes from what the investigators manage to read.

| Package | Test runs |
|---|---|
| Submitted package (91.8 + EUR fix) | 100, 100 |
| `agent/` (examples replaced) | 100, 91.1, 73.8 |
| Teammate's package `run_7ce1970d50d8e31e` | 100, 93.7, 77, 71.6 |
| Same, examples replaced | 100, 93.7, 92.4 |

## Before submitting anything

The final private evaluation uses the latest submission that passed review, not the best one. A new submission or promotion replaces the current 100-point candidate.

## Demo page

Open `demo/adira-bid-desk.html` in a browser. The example data in it is invented. The "Extract facts with Claude" button only works in the hosted version on claude.ai; opened as a local file, the facts are entered by hand and the pricing engine still runs. The engine in the page gives the same result as `agent/pricing.py` on the example (total 83,178.08 EUR).
