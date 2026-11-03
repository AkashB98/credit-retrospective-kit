# credit-retrospective-kit

**Credit portfolio retrospectives — vintage analysis, a production-model performance review, and a cash-flow signal deep-dive — as one deterministic, runnable artifact.**

This repo is built directly against a real job description. The **Plaid Data Scientist, Credit (Retrospectives)** posting asks for exactly three things: **vintage + model-performance retrospectives** (looking back at past lending cohorts and asking how they actually performed), **production-model monitoring dashboards** (watching a live credit model for drift and decay), and **cash-flow signal deep-dives** (testing whether deposit-behaviour signals like income stability actually predict default). This project is that workflow, end to end, in code a reviewer can run: a seeded synthetic loan book for a fictional lender (**Northstar Lending**), per-vintage default curves, the origination score's discrimination and calibration measured from scratch, score-drift monitoring, and a grouped deep-dive on two cash-flow signals — all pinned by golden evals and gated by a CI-style `check` command.

> **Synthetic data only.** Every loan is fabricated by a seeded generator. No real borrower, account, or portfolio data is used anywhere in this project.

**Not to be confused with `collections-risk-scorer`:** that repo builds a score; this one audits a score after the fact.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies.

## Quickstart

```bash
# 1. Generate the synthetic Northstar Lending book (2,400 loans, seed 42)
python3 cli.py generate --count 2400 --seed 42 --out book.jsonl

# 2. Vintage retrospective: default curves + ranking at month-on-book 6
python3 cli.py vintages --input book.jsonl

# 3. Model retrospective: AUC, calibration by band, PSI drift
python3 cli.py model --input book.jsonl

# 4. Cash-flow signal deep-dive
python3 cli.py signals --input book.jsonl

# 5. Full retrospective report (JSON, or --text for the readable document)
python3 cli.py report --input book.jsonl --text

# 6. CI gate: exit 0 = pass, 1 = drift / calibration threshold breach,
#    2 = data-quality / IO error
python3 cli.py check --input book.jsonl; echo $?

# 7. One-command end-to-end demo (generate -> analyse -> report -> serve)
python3 demo.py

# 8. Tiny localhost API: POST /report, GET /health on 127.0.0.1
python3 cli.py serve --port 8765
curl -s -X POST localhost:8765/report -d '{}'   # seeded book report
```

Every command except `generate` also works with no `--input`, using the seeded book.

## The seeded book at a glance (seed 42, 2,400 loans, 499 defaults = 20.79%)

**Vintage** — the set of loans originated in one quarter. A **cumulative default curve** — for each **month-on-book (MOB)** — how many months a loan has been alive — the share of the vintage that had defaulted by then. Comparing vintages at one *fixed* MOB is the fair comparison: a young vintage has simply had less time to go bad.

| Vintage | Defaults | Overall default rate | Cumulative defaults at MOB 6 |
|---|---|---|---|
| 2024-Q1 | 64 | 21.33% | 16.67% |
| 2024-Q2 | 64 | 21.33% | 13.67% |
| **2024-Q3** | **96** | **32.00%** | **21.00%** |
| 2024-Q4 | 67 | 22.33% | 17.00% |
| 2025-Q1 | 51 | 17.00% | 12.00% |
| 2025-Q2 | 48 | 16.00% | 13.00% |
| 2025-Q3 | 68 | 22.67% | 19.00% |
| 2025-Q4 | 41 | 13.67% | 11.67% |

**Worst vintage: 2024-Q3** — 21.00% cumulative defaults at MOB 6, nearly double the best vintage (2025-Q4, 11.67%), and a 32.00% lifetime rate. The generator plants it as a loose-underwriting quarter, and the retrospective finds it without being told where to look (pinned by eval E3; its full curve, ending at 32.00% by MOB 12, is pinned by E4).

## The model retrospective

The book carries the **risk score** — the model's predicted probability that a loan defaults within 12 months of origination — assigned before outcomes were known. The retrospective judges it three ways:

**Discrimination** — whether the score rank-orders risk: riskier loans should default more. Measured by **AUC** — area under the ROC curve; in plain terms, the probability that a randomly chosen defaulter was scored riskier than a randomly chosen non-defaulter (0.5 = coin flip, 1.0 = perfect ranking). Computed from scratch with the Mann–Whitney rank formula, ties taking average ranks. **Seeded AUC: 0.735782** — a working score, honestly short of excellent, which is what a real retrospective usually finds.

**Calibration** — whether the predicted numbers mean what they say: in each score band, the average prediction vs the share that actually defaulted. Calibration is judged only on **seasoned** loans (observed for the score's full 12-month horizon, n = 1,436) — a loan seen for 6 months cannot yet prove a 12-month prediction wrong.

| Band | Loans (seasoned) | Predicted | Observed | Abs. error |
|---|---|---|---|---|
| S1 (< 0.15) | 519 | 6.97% | 7.90% | 0.009296 |
| S2 (0.15–0.30) | 476 | 21.91% | 19.54% | 0.023727 |
| S3 (0.30–0.45) | 274 | 37.04% | 35.04% | 0.020036 |
| S4 (0.45–0.60) | 124 | 51.04% | 54.03% | 0.029924 |
| S5 (≥ 0.60) | 43 | 70.68% | 67.44% | 0.032428 |

Observed rates rise strictly with band (the score **rank-orders** — worst band defaults at 8.5× the best band's rate), and the worst calibration miss is 3.2 points — the score is not just ranked right, its numbers are close to honest.

**Drift** — whether the score distribution itself has moved, measured by **PSI** — population stability index, a standard drift statistic: `PSI = Σ (late% − early%) × ln(late% / early%)` over decile-width score bands, comparing the first two vintages (early window) with the last two (late window). Convention: < 0.10 stable, 0.10–0.25 moderate shift, > 0.25 material. **Seeded PSI: 0.009436 — stable.** That is a finding, not a gap: the late window *did* originate a poorer credit mix, but tighter score cut-offs offset it in the distribution — which is exactly why a retrospective runs vintage analysis *and* drift monitoring instead of trusting either alone.

**The `check` gate** fails (exit 1) if PSI > 0.25 or any band's calibration error > 0.20, and exits 2 on data-quality or IO errors. On the seeded book it passes with room to spare on both thresholds.

## The cash-flow signal deep-dive

Two synthetic deposit-behaviour signals ride along on every loan: **income volatility** — how uneven monthly deposit income is, as a **coefficient of variation** — standard deviation ÷ mean, so 0 is perfectly steady pay and higher is lumpier income — and **balance trend** — the average monthly % change in the deposit balance (negative = balances bleeding down). Grouped default rates, with **lift** — the group's default rate ÷ the book's rate, so 2.0 means "defaults at twice the book rate":

| Signal group | Loans | Default rate | Lift |
|---|---|---|---|
| Income volatility < 0.15 (steady) | 614 | 14.50% | 0.697 |
| Income volatility 0.15–0.30 | 1,245 | 20.56% | 0.989 |
| Income volatility ≥ 0.30 (lumpy) | 541 | 28.47% | 1.369 |
| Balance trend falling (< −1%/mo) | 816 | 27.45% | 1.320 |
| Balance trend stable | 629 | 21.30% | 1.025 |
| Balance trend rising (> +1%/mo) | 955 | 14.76% | 0.710 |

Both signals separate in the direction a credit analyst would predict, monotonically for volatility: lumpy-income borrowers default at ~2× the rate of steady-income ones, and falling balances carry a 1.32 lift against 0.71 for rising balances (lift gap 0.610177, pinned by E9). Defaulters' average volatility is 0.248 vs 0.213 for non-defaulters; their average balance trend is −0.61%/mo vs +0.46%/mo. The honest read: these signals carry real, independent-looking signal worth a model's attention — on synthetic data built to contain it (see limits).

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic Northstar Lending book: exactly 300 loans in each of 8 quarterly vintages, credit/income mix (the last two vintages originate a poorer mix), a latent default propensity driven by credit, affordability and the cash-flow signals, a fixed 12-month default-timing horizon, and the noisy origination score; CSV / JSONL serialisers |
| `vintage.py` | Vintage analysis: cumulative default curves by MOB, per-vintage summaries, worst-first ranking at a fixed MOB with a deterministic tie-break |
| `model_perf.py` | Model retrospective: AUC from scratch (Mann–Whitney with tie-averaged ranks), calibration by score band on the seasoned population, PSI over decile-width bands between early and late windows, verdict bands and the stated gate thresholds |
| `signals.py` | Cash-flow deep-dive: volatility and balance-trend groups, default rates, lift, defaulter vs non-defaulter signal means |
| `report.py` | Full report assembly (JSON dict + readable text rendering) and the breach list behind the `check` gate — a pure function of the book |
| `validation.py` | Data-quality gate: required fields, band vocabularies, numeric ranges, bool traps, and cross-field rules (a defaulted loan needs a default month inside its window and must have been delinquent) — reports issues, never raises on bad data |
| `cli.py` | `generate` / `vintages` / `model` / `signals` / `report` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /report` with `{"loans": [...]}` or an empty body for the seeded book, `GET /health`); CSV, JSONL, and JSON-array inputs |
| `demo.py` | End-to-end narrative with asserts: determinism, curve monotonicity, model and signal headlines, check exit codes, live localhost serve round-trip |
| `fixtures/` | 40-loan sample book (`sample_book.jsonl` + `.csv`, seed 42, 5 loans per vintage) |

## Evals

`python3 evals/run_evals.py` → **16/16 golden evals**, report committed at `evals/eval_report.json` (md5 `ee5ca382faa896eefa09ad2b32dde597`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 JSONL bytes pinned by md5
- **E2** headline counts pinned (2,400 loans, 300 per vintage, 499 defaults, book validates clean)
- **E3** vintage ranking at MOB 6 pinned (worst 2024-Q3 at 21.00%, best 2025-Q4 at 11.67%)
- **E4** vintage curves pinned (2024-Q3's full curve to 32.00%; every curve monotonic)
- **E5** AUC pinned (0.735782) plus a hand-computed 0.75 case
- **E6** calibration pinned (band counts, observed rates, max error 0.032428, seasoned n = 1,436, rank-ordered)
- **E7** PSI pinned (0.009436, stable) plus the PSI formula verified on a hand-computed case and PSI(x, x) = 0
- **E8** calibration hand case, including the seasoned-population filter
- **E9** signal groups pinned (volatility 14.50% → 28.47% monotonic; trend lift gap 0.610177)
- **E10** signal means pinned (defaulters' volatility 0.248063 vs 0.213141; trend −0.006076 vs +0.004619)
- **E11** validation flags a planted defect; the generated book validates clean
- **E12** CLI `check` exit codes 0 / 1 / 2
- **E13** serve round-trip matches the local report exactly (seeded and explicit loans)
- **E14** bundled fixture pinned (40 loans, 8 vintages, validates clean) and text-report headlines
- **E15** known-answer planted drift — a synthetic late window shifted ~+0.40 in score must be flagged by PSI (planted PSI 18.418839, verdict `material_shift`)
- **E16** known-answer planted miscalibration — a synthetic S3 band claiming ~37% risk with an 85% realised default rate must be caught by calibration (abs. error 0.48) and breach the report verdict

Unit tests: `python3 -m unittest discover -s tests` → **114 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-computed AUC cases (perfect / reversed / tied / partial credit), the Mann–Whitney AUC verified against a brute-force pairwise count on fixtures with and without ties (and on a seeded slice), the PSI formula and its symmetry, planted-drift and planted-miscalibration known-answer tests, calibration arithmetic and the seasoned filter, vintage curves and fixed-MOB ranking on hand-built books, data-quality defects (including bool traps), CLI exit codes, and serve round-trips.

## Development loop — what prototyping and the checks actually caught

Three real design errors surfaced while building this, each caught by looking at the numbers the prototype produced — the honest version of a retrospective, applied to the artifact itself:

1. **Default timing squeezed into each loan's own window made young vintages look worst.** The first prototype drew a defaulter's default month uniformly inside its observation window, so a vintage observed for only 6–9 months had all its defaults land by MOB 6 and topped the fixed-MOB ranking for purely arithmetic reasons. The fix is structural: default timing is drawn over the score's fixed 12-month horizon, independent of observation length, and a loan only *shows* as defaulted if that month falls inside its window. After the fix the planted loose quarter (2024-Q3) tops the ranking on its merits.
2. **Calibration over the whole book "failed" a well-built score.** Judged on all 2,400 loans, predicted 12-month rates ran far ahead of observed defaults — because young loans have not finished their 12 months yet (right-censoring: outcomes not yet observable, not predictions proven wrong). Calibration is now judged on the seasoned population only (MOB ≥ 12, n = 1,436), where the max band error falls to 0.032428. The unseasoned version is kept as a documented trap: the evals pin the seasoned numbers, so a future "simplify back to all loans" edit fails loudly.
3. **PSI on the broad calibration bands read ~0.006 and hid the mix shift.** Five 0.15-wide bands are too coarse for a stability index — movement inside a band is invisible to it. PSI now uses decile-width (0.10) bands, the conventional choice; even so it reads 0.009436 (stable), because the late window's poorer credit mix is genuinely offset by its tighter multipliers in the score distribution. Reported as-is: the drift monitor and the vintage analysis telling different halves of the story is the point of running both.

## Scope and honest limits

- **The generator's world is built from the same intuitions the analysis tests.** The latent propensity is driven by credit band, affordability, and the two cash-flow signals — so "the score discriminates" and "the signals separate" are partly by construction. The honest claim is that the *measurement machinery* (curves, AUC, calibration, PSI, lift) is correct, hand-verified, and pinned — not that these effect sizes would survive contact with a real loan book.
- **The score is a noisy propensity, not a fitted model.** No training, no features learned from data; its AUC of 0.736 is a property of the planted noise level. A production retrospective would also slice performance by segment, channel, and score version; this one slices by vintage and band.
- **PSI windows are the first vs last two vintages** — a sensible default for a book this size, not a monitoring policy. A live dashboard would roll the late window monthly and alert on crossings; here the thresholds live in the `check` gate instead.
- **Balance and amount fields are decorative.** Balances do not enter the retrospective math (no loss-given-default or exposure analysis); the report is a default-performance retrospective, not a loss retrospective.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its book in memory, and resets on restart.

## Why this project

It takes a real job description's three asks — vintage and model-performance retrospectives, production-model monitoring, cash-flow signal deep-dives — and rebuilds each as inspectable code with hand-verified math, pinned golden numbers, and failure modes expressed as exit codes. The same discipline a data scientist or forward-deployed engineer brings to a lending partner's problem: define the comparison fairly (fixed MOB, seasoned calibration), show the formula, pin the numbers, and let the gate — not a vibe — say whether the model is still healthy.

## License

MIT — see LICENSE.
