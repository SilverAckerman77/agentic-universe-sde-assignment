# AI Usage Disclosure

## Tools used

- ChatGPT

## What I used them for

- Understanding the assignment requirements and breaking the work into implementation modules.
- Discussing the SQLite schema and data model.
- Drafting Python implementations for normalization, CSV ingestion, event processing, encryption and reporting.
- Generating unit and integration test cases.
- Understanding errors and debugging implementation issues.
- Reviewing report calculations and preparing documentation.

## What I wrote or decided myself

I chose Assignment A and integrated the proposed implementation into my local repository.

I executed the commands, generated the synthetic datasets, ran the test suite, inspected the report outputs and checked that the lead and event totals reconciled.

I adopted the SQLite, Fernet encryption and HMAC-SHA256 matching approach after considering the trade-offs discussed during development.

I am responsible for understanding and explaining the final implementation and its limitations.

## Where the AI was wrong or unhelpful

At one point, ChatGPT estimated an incorrect expected test count. The actual pytest output showed 38 tests at that stage, rather than the estimated 39. I relied on the test runner's collected count and corrected the validation plan.

I treated actual execution results as the source of truth rather than assuming generated code was correct.

## How I verified AI-generated code

- Ran the pytest suite locally.
- Tested the implementation on the seed 42 synthetic dataset.
- Generated and processed a separate seed 73 dataset.
- Checked lead-count and event-count reconciliation.
- Verified duplicate-drop handling.
- Inspected report files and their output structure.

The current implementation has passed 40 tests before the additional lead-bucket tests were added. All final test counts and results will be updated after the last validation run.

I have not independently compared every generated report row against a separate evaluator-provided golden output.