# DATA.md: what we found, what we decided, how we test

## 1. What is in the provided export (measured)
| File | Rows | Findings |

| people.csv | 400 | clean: unique ids, every org exists |
| org_units.csv | 37 | one root (ORG01), 4 levels, no cycles |
| seats.csv | 680 | one seat per person+tool, 75 revoked, all dates ISO, no reversed intervals |
| price_list.csv | 7 | **Tool E has a blank price** (78 seats) so it is unpriced |
| activity_events.csv | 39,971 | see below |

Events: 40 rows belong to 5 ids not in people.csv (U9001 to U9005, outsiders: not counted); 250 exact duplicate rows
(harmless, we count people not events); 160 rows are for a person+tool with no seat at all (never count);
more rows fall outside the seat's held days (before grant / on or after revoked_on, never count).
All times are 09:00 to 19:59 in every tool and for every location, so no timezone shift is visible: the written (local) date is used.
Files use CRLF line endings.

## 2. Rules (applied by rule, never by row; every hit is counted and printed at start-up)
# Data sources, cleaning rules, and test design

## Data sources

The application reads these five CSV exports from the repository's root `data/` directory:

- `people.csv`: company people and their org assignments
- `org_units.csv`: organization hierarchy
- `seats.csv`: tool seats, tiers, and grant/revocation dates
- `price_list.csv`: monthly prices by tool and tier
- `activity_events.csv`: tool usage events

The application makes no external data or API calls. It loads and normalizes the CSVs at startup. The calculations use Python's standard-library CSV, date, and decimal handling; pandas is not required.

## Findings in the supplied export

These are observations about the supplied files only. They are not constants in the application.

| File | Rows | Observed finding |
|---|---:|---|
| `people.csv` | 400 | People used for company-wide and org-scoped reporting |
| `org_units.csv` | 37 | Four levels, L3 through L6 |
| `seats.csv` | 680 | Seat history for tools A–E |
| `price_list.csv` | 7 | Tool E / standard has a blank price; seats at this tier are unpriced |
| `activity_events.csv` | 39,971 | Includes events for user IDs not present in `people.csv` and repeated events |

The replacement export can have different rows and additional data-quality issues. The application discovers and handles issues by rule; it does not rely on these row counts or IDs.

## Normalization and validation rules

### Files and columns

- All five files and their required columns must be present. A missing file or required column stops startup because the application cannot calculate the requested metrics without them.
- Header names are trimmed and treated case-insensitively.
- Blank rows are skipped. Field values are trimmed.
- Identifiers and tool names are normalized to uppercase; price tiers are normalized to lowercase.
- Extra columns are ignored.

### People and organization units

- The report includes people represented in `people.csv`.
- A person with a blank ID is skipped because the row cannot be identified.
- Repeated rows for the same person and org are treated as one person.
- If the same person ID has conflicting org assignments, the person remains in company-wide totals but is assigned to no org subtree.
- An org ID with conflicting parent assignments is treated as a root. This avoids choosing a parent based on CSV row order.
- An org with a missing parent is treated as a root.
- Self-parent links are ignored. Org traversal tracks visited IDs so cycles cannot cause an infinite loop.
- A person with a blank or unknown org remains in company-wide reporting but is not included in an org-scoped result.

### Prices

- A blank, negative, nonnumeric, or otherwise unparseable price is treated as unpriced.
- Identical duplicate `(tool, tier)` price rows collapse to one entry.
- If duplicate rows for the same `(tool, tier)` disagree, that price key is treated as unpriced. The loader does not choose a row based on file order.
- Unknown tools in the price list are ignored.
- A seat with a missing or unpriced tier remains eligible for license and activity counts, but contributes no spend.
- A tool's API spend fields are `null` when none of its tiers has a usable price. If at least one tier is priced, spend includes only seats whose own tier has a usable price.

### Seats

- Seat grant and revocation dates are parsed as year-first dates. Invalid dates are skipped and reported.
- `revoked_on` is the first day without the seat. A seat is held when `granted_on <= day < revoked_on`.
- If `revoked_on` equals `granted_on`, the seat has zero held days. If revocation is earlier than grant, the row is skipped and reported.
- Seats for unknown people or unknown tools are skipped and reported.
- Identical duplicate `(user_id, tool)` rows collapse to one seat.
- If rows for the same `(user_id, tool)` disagree, that seat key is quarantined: none of its rows contribute to license, activity, or spend metrics. The brief says a person has at most one seat per tool, but does not specify how to resolve contradictory rows. Quarantine avoids inventing a seat history by merging or selecting a row.
- Other seat/tool records for that person are unaffected.

### Activity events

- The event timestamp is treated as local time, as specified in the brief. Its written calendar date is used.
- Supported timestamps include year-first dates with optional time components and common separators. Ambiguous day-first/month-first dates and invalid dates are skipped and reported.
- Events for unknown people or unknown tools are skipped and reported.
- Every event type counts as usage because the brief defines no event-type exclusions. Usage counts only if the person held a seat for that same tool on the event's date.
- Events without a matching held seat may remain in the loaded event index, but they do not count as active usage.
- Multiple events for the same person/tool/day are reduced to one usage day. Active users are distinct people, not event counts.

## Metric and error behavior

- The request window includes both `from` and `to`.
- Licensed users are distinct people who held any seat for at least one day in the window.
- Active users are distinct licensed people with at least one qualifying event in the window.
- Spend and idle spend are calculated per priced seat for the number of days held, using monthly price divided by 30. Unpriced seats are excluded from spend.
- Idle spend is the spend of a priced seat with no qualifying usage during the window.
- Money is accumulated with decimal arithmetic and rounded half-up to two decimal places; engagement is rounded half-up to one decimal place.
- An unknown org returns 404. Missing, malformed, or reversed date windows return 4xx responses.

## Test design

The offline pytest suite covers:

- The Appendix P worked example and seat grant/revocation boundaries
- Usage before a grant, on a revocation date, and for a different tool
- Blank/unpriced tiers, duplicate and conflicting rows, and unknown users
- Org roll-ups, invalid org IDs, and cyclic or incomplete org hierarchies
- Invalid request dates and expected HTTP error codes
- Additional timestamp and price formats
- Randomized date windows compared with a straightforward day-by-day calculation
- Noisy copies of generated data to check that harmless duplicates and formatting noise do not change results

Tests use generated fixtures and do not depend on the supplied user IDs or row counts. Run them with `python -m pytest -q` after installing `requirements.txt`. This document describes the test coverage; it does not claim that the suite has passed on every machine.

## 3. Test design
* `tests/test_worked_example.py`: Appendix P example reproduced exactly (2 / 1 / 50.0 / 38.5 / 19.5); `revoked_on` boundary; usage before grant; unpriced tool null; five tool rows A to E; ghosts ignored; org roll-up.
* `tests/test_errors.py`: every error path, extreme valid dates (0001 to 9999), single-day window, org case.
* `tests/test_messy_data.py`: tolerant parsing (timestamps, ids, junk rows, prices, org cycles) with the service still starting.
* `tests/test_policies.py`: the duplicate/ambiguity policies (price, seat, person, org), every event type counting, the seat-day rule on both edges, and a **noise-invariance** test: random data plus duplicates, ghosts, junk rows, case/space damage and `T` timestamps must give identical numbers to the clean copy. All ids and counts are generated; nothing depends on the shipped data.
* `tests/test_bruteforce.py`: 60 random windows on random data vs a naive loop over every calendar day.
* Out of band: the shipped data was checked against an independent pandas implementation (180 window/org combinations, 0 mismatches) and against the first version of this service (150 random queries, identical output).
