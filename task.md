# Take-Home Engineering Challenge: Reliable Data Pipeline

## Overview

Build a small data aggregation service that collects product information from multiple supplied mock e-commerce APIs, normalizes the data, and produces a consolidated result.

The exercise evaluates engineering judgment, system design, testing, verification, communication, and effective use of AI-assisted development.

We do **not** expect a production-ready system. Prefer a focused, well-reasoned solution over unnecessary scope.

## Expected Effort

Please spend **no more than 4 hours** on the exercise.

We intentionally do not expect every candidate to implement every possible improvement. Prioritize the areas you believe matter most, make sensible tradeoffs, and document anything important that you would do with more time.

A smaller solution with strong reasoning and verification is better than a larger solution with unjustified complexity.

You are **not** expected to add infrastructure that is unrelated to demonstrating the core engineering decisions. For example, a database, deployment configuration, CI pipeline, containerization of your own application, or production monitoring stack are not required unless you believe they materially improve your solution.

---

## Why We Use This Exercise

This challenge is intended to give you room to work in a realistic development environment rather than solve algorithmic problems under observation.

If you progress to the next stage, your submission will become a shared technical artifact for an in-person discussion. You should be prepared to explain your decisions, discuss tradeoffs, debug behavior, and make a small change to your solution.

---

# Provided Starter Environment

You will receive a small mock API environment together with this challenge.

The environment exposes three local HTTP API sources with intentionally different behavior, including differences in:

- Pagination
- Response schemas
- Latency
- Reliability
- Rate limiting
- Data quality

You are **not** expected to implement or modify the mock APIs.

The provided mock service is language-independent from the candidate's perspective: your solution communicates with it over HTTP, so you may implement your application in Python or another mainstream backend language.

---

# The Challenge

Build a service that collects product data from all three supplied mock API sources.

Your solution should:

- Fetch data from all sources
- Normalize records into a consistent product representation
- Handle partial upstream failure without losing successful results
- Respect source constraints such as rate limits
- Produce useful run-level summary information
- Provide enough observability to understand failures and performance
- Remain reasonably efficient in resource usage

Do not assume all sources behave identically.

You are responsible for deciding how the aggregation system should behave in ambiguous or failure scenarios and documenting those decisions.

Examples of decisions you may need to make include:

- What constitutes a successful or partially successful run?
- Which failures should be retried, if any?
- How should malformed individual records be handled?
- What should happen when one source fails completely?
- How should duplicate or conflicting records be treated?
- How should timeouts or overall run limits be handled?

There is no single expected architecture or resilience strategy. We care about whether your choices are appropriate and well justified.

---

## Normalized Product

At minimum, a normalized product should contain:

```json
{
  "id": "source-or-unified-id",
  "title": "Product Name",
  "source": "endpoint_a",
  "price": 29.99,
  "category": "electronics"
}
```

You may extend this model where useful.

The final output format is your choice as long as it is easy to inspect and the normalized records are clearly represented.

---

# Engineering Expectations

Python is the recommended language for this exercise because it allows candidates to get started quickly, but **Python is not required**.

You may use another mainstream backend language if it better represents how you would approach the problem professionally. If you do, briefly explain the choice in the README.

We are evaluating your engineering decisions, not your familiarity with a particular language or framework.

We deliberately do not prescribe:

- A concurrency model
- An application framework
- A retry strategy
- A resilience pattern
- A specific architecture
- A logging or observability library

Choose the approach you believe best fits the workload.

We will evaluate whether the complexity you introduce is justified.

---

# Spec-Guided Development

Use a lightweight spec-guided workflow.

The goal is to make your assumptions and decisions visible, not to produce extensive documentation.

Bullet points are encouraged. **One or two pages total across `SPEC.md` and `PLAN.md` is usually enough.**

Before substantial implementation, create the following.

## `SPEC.md`

Define the intended behavior of the system, including:

- Goals and non-goals
- Important requirements
- Failure behavior
- Assumptions or ambiguities
- Testable acceptance criteria

If your understanding or design changes during implementation, update the specification where useful.

## `PLAN.md`

Briefly describe:

- Your implementation approach
- Major technical decisions
- Important tradeoffs
- Testing and verification strategy

This should be a working artifact rather than a polished design document.

---

# AI-Assisted Development

AI use is expected.

You may use any AI development tools and may delegate substantial implementation work.

We are **not** evaluating how much code you personally type. We are evaluating whether you remain responsible for the engineering outcome.

You should understand the code you submit and be prepared to explain, debug, and modify it.

## `AI_USAGE.md`

Keep this concise.

Document:

- Tools used and how you used them
- What you delegated to AI
- Important feedback from the specification review and how you responded
- How you verified AI-generated work
- At least one AI suggestion, assumption, or output that you challenged, rejected, or independently validated
- Important findings from the final AI review and how you responded
- What you would improve with more time

Do not include full AI conversation transcripts.

We care more about your verification process and judgment than the specific tools you used.

---

# Testing and Verification

Include automated tests that give you confidence in the important behavior of the system.

We care more about the quality of verification than raw coverage numbers.

Tests should focus on behavior that materially affects correctness or resilience. Depending on your design, useful areas may include:

- Normalization
- Pagination
- Partial source failure
- Malformed records
- Retry behavior
- Rate limiting
- Duplicate handling
- Run summaries
- Timeouts or cancellation

You do not need to test every library or framework behavior.

---

# Required Deliverables

Submit a Git repository containing:

- Application source code
- Automated tests
- `SPEC.md`
- `PLAN.md`
- `AI_USAGE.md`
- `README.md`

The README should contain:

- Setup instructions
- Run instructions
- Test instructions
- Language/framework choice if not using Python
- Important assumptions
- Known limitations
- Anything you intentionally did not implement because of the time limit

---

# Evaluation

We evaluate the submission using the following areas.

| Area | Weight |
|---|---:|
| Correctness and failure behavior | 20% |
| Testing and verification | 20% |
| Engineering judgment and tradeoffs | 20% |
| System design | 15% |
| Code quality and maintainability | 10% |
| AI supervision and verification | 10% |
| Communication | 5% |

## What Strong Submissions Usually Demonstrate

Strong submissions generally show:

- Clear behavior under both success and failure
- Sensible handling of heterogeneous upstream systems
- Appropriate complexity for the problem
- Tests aimed at important risks rather than superficial coverage
- Explicit assumptions where the requirements are ambiguous
- Code that is easy to understand and modify
- Evidence that AI-generated work was reviewed rather than accepted blindly
- Good prioritization within the time limit

A smaller solution with strong reasoning is better than a larger solution with unjustified complexity.

Partial implementations are acceptable when the tradeoffs and remaining work are clear.

---