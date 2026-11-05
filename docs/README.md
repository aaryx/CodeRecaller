# CodeRecaller Documentation Index

This directory contains in-depth documentation, technical specifications, operational procedures, and evaluation guides for CodeRecaller.

---

## 1. System Architecture & Technical Specifications

- **[Architecture Specification](../architecture.md)**: Clean layered architecture, storage boundaries, concurrency model, and write-ahead journaling.
- **[FSRS Mathematical Specification](revision.md)**: Mathematical formulation of the Free Spaced Repetition Scheduler (FSRS v4), memory stability decay curves, and retrievability targets.
- **[Docker Sandbox Threat Model](docker-execution-threat-model.md)**: Security boundaries, Linux capability drops, resource limits, and multi-tenant isolation limits for the optional Docker runner.
- **[Git Synchronization Semantics](git.md)**: Owned-file staging model, pre-push secret scanner regexes, and non-destructive fast-forward sync.
- **[Configuration Reference](configuration.md)**: Configuration schema, keys, default values, and environment variable overrides for `.coderecall/config.toml`.
- **[Validation & Benchmark Measurements](validation.md)**: Performance benchmarks and storage latency measurements up to 10,000 problem snapshots.

---

## 2. User & Developer Guides

- **[CLI Command Reference](cli.md)**: Detailed reference covering all commands, options, and global flags.
- **[Optional Adapters Guide](optional.md)**: Configuration instructions for the optional container runner and experimental AI adapter.
- **[Troubleshooting & Platform Notes](troubleshooting.md)**: Common questions, Windows terminal codepage setup, and platform-specific behavior.
- **[Contributing Guide](../CONTRIBUTING.md)**: Environment setup, coding conventions, testing workflow, and pull request guidelines.
- **[Security Policy & Disclosures](../SECURITY.md)**: Responsible vulnerability disclosure procedure and private reporting channel.

---

## 3. Product Strategy & Evaluation

- **[Strategic Product Roadmap](product/roadmap.md)**: Prioritized roadmap tiers (P0–P3) and quarterly decision criteria.
- **[Competitive Positioning](product/competitive-positioning.md)**: Comparison of CodeRecaller against Anki, LeetCode, Notion, and manual spreadsheets.
- **[Developer Beta Trial Guide](product/developer-trial-guide.md)**: 10–15 minute evaluation protocol for volunteer developers testing the pinned release candidate.
- **[Beta Feedback Template](product/trial-feedback-template.md)**: Reusable feedback questionnaire for beta trial participants.
- **[First-Time User Onboarding Review](product/first-time-user-review.md)**: Qualitative evaluation across three target developer personas.

---

## 4. Release Engineering & Operations

- **[Maintainer Releasing Guide](../RELEASING.md)**: Step-by-step maintainer release checklist, package building, and publication procedures.
- **[Pre-Release Verification Checklist](release-checklist.md)**: Mandatory verification checklist to be passed prior to tagging any release.
