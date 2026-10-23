# Decision review question bank

Use selectively according to impact. Do not turn every small change into a ceremony.

## Context
- How does the system work now? Which files, services and data flows are involved?
- Which constraints are confirmed? Which are assumptions?
- Is there an earlier decision or incident related to this?
- What evidence supports the current understanding?

## Problem
- Is this the root cause or only a symptom?
- What happens if we do nothing?
- Who or what is affected, and how is impact measured?
- What acceptance criteria make the fix complete?
- What is explicitly outside scope?

## Options
- What is the simplest viable option?
- Is doing nothing or delaying the decision viable?
- What are the implementation, maintenance and operating costs?
- Which failure modes or dependencies does each option introduce?
- Why were alternatives rejected? Is a small proof of concept needed?

## Decision and rationale
- What exactly is being chosen, and what is not being chosen?
- Why does this fit the constraints better than the alternatives?
- Which reasons are evidence-backed versus assumed?
- Who owns the contract or responsibility at each boundary?

## Trade-offs and risk
- Does this add abstraction, dependency or operational burden?
- What can fail under load, concurrency, retries, partial outage or invalid input?
- Could it weaken authorization, privacy, data integrity or auditability?
- How can the change be rolled back or disabled?
- What mitigation is practical now?

## Verification
- Which normal, edge, failure and permission-denied paths matter?
- Which tests were written and which were actually run?
- What exact command and result provide evidence?
- Were load, latency or resource claims measured or estimated?
- What remains unverified?

## Review and supersession
- What metric, incident, scale or requirement would invalidate this decision?
- Does a newer decision replace it? Why?
- What migration, cleanup or documentation update is required?
- Which old assumptions no longer hold?
