# DECISION-001 Explainable Theme-Opportunity Policy

Status: Phase A implemented locally on the
`feature/decision-001-explainable-policy` branch. The policy and pure
calculation layer are implemented; persistence, CLI, Parquet, Feishu, and
automation are not implemented by this phase.

## 1. Product boundary

DECISION-001 answers whether a raw Sensor Tower Game Theme deserves
exploration or controlled product validation. It is a theme-opportunity
decision system, not Product Greenlight. A recommendation never means that a
specific game should be published.

Product Greenlight remains a separate decision requiring product quality,
marketability, creative performance, CPI / IPM, retention, monetization, LTV /
ROAS, production cost, and team capability. DECISION-001 does not provide
those inputs and does not replace that process.

The policy is deterministic, versioned, and explainable through component
states, normalized risk codes, primary reason codes, and next-action codes. It
does not calculate an opaque weighted investment score, machine-learning
forecast, predicted observable Revenue (USD), success probability, or
AI-generated narrative.

MONETIZATION-001 is completed and real-environment accepted. DECISION-001 is
the current issue. Phase A freezes the policy and implements only immutable
typed outputs and pure calculation over existing normalized models.

## 2. Accepted evidence and policy version

The fixed policy identifier is:

```text
DECISION001_V1
```

The accepted BACKTEST-001 interpretation is conservative:

1. Current Downloads Share, observable Revenue (USD) share, and Product Share are
   the strongest evidence of future T+1 to T+3 market scale.
2. The legacy 6M Momentum Score has some historical support for future
   observable Revenue (USD) share growth, but is secondary evidence only.
3. MODEL-002 6M and 12M trend slopes have weak predictive value for future
   Downloads growth. They remain visible evidence but cannot provide primary
   positive recommendation uplift.
4. MODEL-002 36M predictive evidence is unavailable for the accepted first
   36-month history and cannot strengthen a recommendation.
5. Stability, low product HHI, and low Top-10 positive-growth concentration are
   durability or risk evidence. They do not prove high growth and cannot
   independently increase an opportunity recommendation.
6. New Entry, Top-500 Turnover, and Seasonality cannot be primary positive
   opportunity signals.
7. Lifecycle is interpreted as follows:

   | MODEL-002 lifecycle | DECISION-001 Growth Quality |
   | --- | --- |
   | `growing` | `balanced_growth` |
   | `accelerating` | `observable_revenue_growth_support` |
   | `mature` | `durable_established` |
   | `emerging` | `experimental_emerging` |
   | `recovering` | `cautious_recovery` |
   | `declining` | `declining` |
   | `mixed` | `mixed_or_uncertain` |
   | `insufficient_history` | `insufficient_evidence` |

8. A `volatile` stability band is a risk signal.

The source policy references carried by summary rows identify the accepted
AGG-002, MODEL-002, and BACKTEST-001 evidence boundaries. When observable
Revenue (USD) evidence is used, the MONETIZATION-001 policy reference is also
carried.

## 3. Stable enums

Market Size:

```text
strong
moderate
limited
insufficient_evidence
```

Growth Quality:

```text
balanced_growth
observable_revenue_growth_support
durable_established
experimental_emerging
cautious_recovery
declining
mixed_or_uncertain
insufficient_evidence
```

Competitive Structure Risk:

```text
lower_structural_risk
mixed_structural_risk
higher_structural_risk
insufficient_evidence
```

Category Fit:

```text
validated_fit
observed_fit
insufficient_evidence
```

Recommendation:

```text
prioritize_validation
selective_validation
small_experiment
monitor
deprioritize
```

Confidence:

```text
high
medium
low
```

Launch-window evidence state:

```text
supported_validation_window
selective_validation_window
experimental_window
caution_or_monitor
```

The implementation also defines stable enums for normalized `RiskCode`, risk
severity, evidence availability, primary reason code, next validation action,
category evidence limitations, and migration-hypothesis status. Risk rows do
not contain generated prose.

## 4. Pure input boundary

The pure operation accepts only existing normalized, typed project models:

- one target-month `MonthlyMarketTotal`;
- target-month `ThemeMarketStructureMetric` rows;
- optional target-month `ThemeGrowthSourceMetric` rows;
- target-month `ThemeModelSummary` rows;
- optional target-month legacy `ThemeTrendScore` rows;
- optional target-month `ThemeMonetizationObservabilityMetric` rows;
- trailing dimension rows and representative-game rows from AGG-002; and
- one injected timezone-aware `calculated_at` timestamp.

The operation does not accept Sensor Tower DTOs, raw JSON, dictionaries,
DuckDB tuples, Pandas rows, Feishu rows, or raw transport payloads. It does not
consume raw future outcome rows. Any supplied row after the target period is
rejected.

The target population is exactly one decision summary for every raw non-NULL
Game Theme in the target-month MODEL-002 summary and corresponding AGG-002
market-structure populations. Empty strings, `Unknown`, and `N/A` remain
literal labels. A SQL/source NULL Game Theme creates no decision row. Duplicate
identities, mixed scope or cadence, incompatible periods, and population
reconciliation failures are validation errors.

Dimension evidence is limited to the target month and the preceding completed
months within the trailing 12-month window, inclusive of the target month.
Representative rows are accepted only inside that same evidence window and
are used only when their row-level association is explicit. Product Model, Art
Style, and Setting are context only; they cannot prove Game Sub-genre fit or
monetization type.

## 5. Percentile semantics

Cross-theme current-month comparisons use average-rank percentiles:

- the highest numeric value receives `1`;
- ties receive their average rank;
- a one-row numeric cohort receives `0.5`;
- NULL values do not participate; and
- observed zero remains numeric zero.

Percentiles are calculated separately for each compatible target-month
population and never cross scope, cadence, or target period boundaries.

## 6. Market Size

Only current target-month Product Share, Downloads Share, and observable
Revenue (USD) share are used. For each available metric, the pure layer calculates a
cross-theme percentile.

| Rule | Market Size |
| --- | --- |
| At least two of three percentiles are `>= 0.80` | `strong` |
| Not strong and at least two are `>= 0.50` | `moderate` |
| At least two metrics are numeric but neither prior rule applies | `limited` |
| Fewer than two metrics are numeric | `insufficient_evidence` |

Unavailable values are never replaced with zero.

## 7. Growth Quality

Growth Quality is the exact lifecycle mapping in Section 2. A positive 6M or
12M Downloads trend slope cannot upgrade the mapped state. 36M evidence is not
used to strengthen a recommendation. The legacy 6M Momentum Score may remain
visible as secondary evidence, but cannot independently produce
`prioritize_validation`.

## 8. Competitive Structure Risk

The current-month concentration measures are:

- Downloads product HHI;
- observable Revenue (USD) product HHI;
- Downloads Top-10 positive-contribution share; and
- observable Revenue (USD) Top-10 positive-contribution share.

Each available measure is compared cross-sectionally, with higher percentiles
meaning higher concentration risk.

| Rule | Competitive Structure Risk |
| --- | --- |
| At least two available risk percentiles are `>= 0.80` | `higher_structural_risk` |
| At least three are available, none is `>= 0.80`, and at least two are `<= 0.50` | `lower_structural_risk` |
| At least two are available and neither prior rule applies | `mixed_structural_risk` |
| Fewer than two are available | `insufficient_evidence` |

The band is risk context only. A lower-risk band never independently upgrades
Market Size, Growth Quality, Launch Window, or Recommendation. New Entry,
Top-500 Turnover, and Seasonality remain visible summary context where
available; they cannot improve this band or the recommendation.

Seasonality risk is transparent and cross-sectional: if either available
seasonality amplitude is at or above the `0.80` percentile in the target-month
theme population, `seasonality_timing_dependence` is emitted. This is timing
risk context, not a business forecast.

## 9. Risk codes and observable Revenue limitations

The normalized risk-code registry includes:

```text
volatile_evidence
mixed_lifecycle
declining_lifecycle
high_product_concentration
top10_growth_concentration
seasonality_timing_dependence
insufficient_market_evidence
insufficient_model_history
non_actionable_theme_label
observable_revenue_only
observable_revenue_coverage_gap
monetization_type_unverified
migration_not_validated
```

When observable Revenue (USD) or monetization-proxy evidence is used,
`observable_revenue_only` and `monetization_type_unverified` are retained even
when field coverage is 100%. `observable_revenue_coverage_gap` is emitted when
coverage is incomplete.

Business-facing terminology is always **observable Revenue (USD)**. It means
third-party-platform observable Revenue (USD) only, not complete actual commercial
revenue. It does not include complete IAA advertising revenue. Observable Revenue
(USD) equal to zero does not prove actual total revenue equals zero.
`iaa_candidate` is not verified or pure IAA, and
`iap_or_hybrid_candidate` does not distinguish IAP from Hybrid. The observable
Revenue (USD) amount does not prove a monetization model, and Game Product Model is product-form
context only.

## 10. Category Fit

The output contains one row for each raw Game Sub-genre observed for the theme
inside the inclusive trailing 12-month evidence window. SQL NULL values do not
create category rows. Each row reports observation-month count, target-month
product and Downloads evidence, target-month observable Revenue (USD) evidence when
available, representative-product support when available, and stable evidence
limitations.

A Game Sub-genre is `validated_fit` only when every condition holds:

- it is observed in the target month;
- target-month product count is at least 2;
- it is observed in at least 3 months in the window;
- target-month Downloads coverage is positive; and
- target-month Downloads sum is positive.

If it has observed product evidence but does not meet every condition, it is
`observed_fit`. Observable Revenue (USD) is supporting evidence and is not required
for validated fit. A category with no usable product evidence is
`insufficient_evidence`.

No cross-dimension combination is inferred from separate aggregates. A row-level
representative association is required before representative evidence is
attached.

## 11. Migration Hypothesis

A migration hypothesis is emitted only when the same theme has:

1. at least one `validated_fit` source Game Sub-genre;
2. a different target Game Sub-genre with real observed evidence; and
3. a target that is `observed_fit`, not `validated_fit`.

The output retains the source and target raw values, supporting evidence codes,
`migration_not_validated`, `is_validated_fit=false`, and
`requires_product_validation=true`. It never labels a target proven,
compatible, validated, or successful; it never invents adjacency mappings; and
it never creates an unobserved target. Zero migration rows is valid.

## 12. Recommendation rule order

Rules are evaluated in this order so later positive cases cannot override
negative or risk gates:

1. `deprioritize` when lifecycle is `declining` and Market Size is `limited`,
   or lifecycle is `declining` and competitive risk is
   `higher_structural_risk`.
2. `monitor` when Market Size or Growth Quality is
   `insufficient_evidence`, lifecycle is `mixed`, stability is `volatile`, or
   a non-actionable theme-label rule applies. Mixed or volatile evidence cannot
   receive a stronger recommendation.
3. `small_experiment` when Growth Quality is `experimental_emerging`, Market
   Size is not insufficient, and no earlier gate applies. Its next action is a
   small controlled validation, never full production or publishing approval.
4. `prioritize_validation` only when Market Size is `strong`, Growth Quality is
   `balanced_growth` or `observable_revenue_growth_support`, competitive risk
   is not higher, confidence is not low, and no earlier gate applies.
5. `selective_validation` when no earlier rule applies and either Market Size
   is strong with `durable_established` or `cautious_recovery`, or Market Size
   is moderate with positive Growth Quality.
6. All other cases are `monitor`.

Primary reason and next-action values are enums. They include
`strong_current_market_scale`, `balanced_growing_evidence`,
`observable_revenue_growth_evidence`, `durable_established_market`,
`emerging_requires_experiment`, `recovery_requires_validation`,
`mixed_or_volatile_evidence`, `declining_evidence`, and
`insufficient_evidence`, plus `prioritize_theme_validation`,
`run_selective_concept_validation`, `run_small_controlled_experiment`,
`monitor_next_completed_month`, `deprioritize_current_theme`,
`validate_category_fit`, and `validate_migration_hypothesis`.

## 13. Confidence

Confidence describes evidence completeness and compatibility inside the
selected market sample. It does not describe certainty about the complete
global market or actual total commercial revenue.

- `high` requires all three current Market Size measures, sufficient 12M
  lifecycle evidence, at least three competition-risk measures, at least one
  validated Game Sub-genre fit, and exact input-identity reconciliation.
- `medium` requires at least two current Market Size measures, lifecycle other
  than `insufficient_history`, and at least two competition-risk measures.
- Otherwise confidence is `low`.

The observable Revenue (USD)-only and monetization-type limitations remain present
at high confidence.

## 14. Launch Window

Every decision summary emits exactly three immutable rows for T+1, T+2, and
T+3 (horizon months 1, 2, and 3). Each row carries `is_forecast=false`. It has
an evidence state,
confidence, and reason code, but no predicted Downloads, predicted observable
Revenue, target value, or success probability.

The current Market Size is the primary scale evidence:

- strong scale plus positive Growth Quality and no high-risk gate produces
  `supported_validation_window`;
- moderate scale or mature/recovering evidence produces
  `selective_validation_window`;
- emerging produces `experimental_window`; and
- declining, mixed, volatile, insufficient, or high-risk evidence produces
  `caution_or_monitor`.

The rows record that current shares are the primary historically supported
evidence, legacy momentum is secondary observable Revenue (USD) growth evidence,
New Entry, Turnover, Seasonality, and 6M/12M Downloads trend are not primary
positive evidence, and 36M predictive evidence is unavailable. This is not a
forecast and does not claim that the theme will grow.

## 15. Output contract and determinism

The pure result contains immutable typed rows:

- `ThemeDecisionSummary`: one target-theme row with component states,
  recommendation, reason/action codes, policy references, visible context, and
  injected `calculated_at`;
- `ThemeLaunchWindowAssessment`: exactly three non-forecast horizon rows;
- `ThemeDecisionRisk`: zero or more normalized risk rows with code, severity,
  evidence availability, and optional source metric;
- `ThemeCategoryFitAssessment`: one row per observed target-theme raw
  Game Sub-genre value in the approved window; and
- `ThemeMigrationHypothesis`: zero or more explicitly unvalidated migration
  rows.

Every row carries `DECISION001_V1`. Output identities reject duplicates, all
outputs share the injected timezone-aware timestamp, and explicit primitive
identity tuples define deterministic ordering. Domain objects are never sorted
directly.

## 16. Known limitations and phase boundary

The policy is calibrated only to the accepted evidence interpretation and the
selected WW Puzzle/Tabletop Top-N sample. The sample is not the complete global
mobile-games market. Observable Revenue (USD) is incomplete commercial-revenue
coverage, and the monetization labels remain unverified candidates.

Phase A includes only this policy document, immutable enums/models, pure
calculation, and focused synthetic unit/contract tests. It deliberately does
not implement DuckDB tables or schema migration, repository readers/writers,
CLI, workflow orchestration, Parquet export, Feishu output, automation, live
Sensor Tower requests, or real-environment execution. Those activities belong
to later DECISION-001 phases and require separate acceptance.
