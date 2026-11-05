# CodeRecaller: Strategic Product Roadmap

## Roadmap Principles & Decision Framework

All proposed enhancements to CodeRecaller are evaluated against four non-negotiable principles:

1. **Local-First & Zero Telemetry**: We never introduce mandatory cloud accounts, background daemons, or tracking beacons.
2. **Lean Dependency Profile**: Keep runtime dependencies minimal (`typer`, `click`, `rich`) and avoid sprawling transitive dependency graphs.
3. **Data Integrity & Durability**: State schema changes must include deterministic migrations, atomic writes, and transaction recovery.
4. **Active Recall over Passive Memorization**: Features must encourage deliberate coding practice and typing solutions, not passive answer flipping.

---

## Roadmap Priority Tiers

Work items are organized into four prioritized categories:
- **P0**: Correctness, security, and release blockers.
- **P1**: High-value usability and developer experience improvements.
- **P2**: Validated product enhancements backed by real developer workflows.
- **P3**: Speculative and long-term architectural explorations.

---

## P0: Correctness, Security & Release Blockers (Completed in v0.3.0)

| Item | Problem Addressed | Status |
| :--- | :--- | :--- |
| **Unified Release Gate** | Lack of a single automated command to verify git cleanliness, lint, format, types, tests, builds, and clean installs. | **Delivered** in `scripts/release_gate.py`. |
| **Windows CP1252 Terminal Normalization** | Unicode en-dashes (`–`) and em-dashes (`—`) in CLI docstrings rendered as replacement characters (``) on default Windows consoles. | **Delivered** in `coderecall.cli`. |
| **Docker Runner Input Boundary Validation** | Embedded null bytes (`\x00`) in scripts triggered raw `ValueError` in `subprocess.Popen` rather than early rejection. | **Delivered** in `coderecall.execution.docker`. |
| **Clean Packaging & Entry Point Verification** | Wheel installation needed automated validation outside the repository in an isolated environment. | **Delivered** in `scripts/validate_install.py`. |

---

## P1: High-Value Usability & Adoption Improvements

### 1. Multi-Language Solution Templates (C++, Java, Rust, Go)
- **Problem**: CodeRecaller currently assumes Python solutions by default. Developers practicing in C++, Java, Rust, or Go must manually structure their file extensions and starter boilerplate.
- **Expected Benefit**: Broadens CodeRecaller's adoption to competitive programmers and systems engineers who practice in compiled languages.
- **Estimated Effort**: **Medium** (2–3 engineering days).
- **Architectural Risk**: Low. Requires mapping language identifiers to standard starter boilerplate templates in `catalog.py`.
- **Validation Method**: Unit tests verifying starter template generation for `.cpp`, `.java`, `.rs`, `.go`, and `.py`.

### 2. Interactive First-Run Onboarding (`coderecall quickstart`)
- **Problem**: First-time users currently must manually create a practice directory, run `git init`, and write a sample solution file before testing active recall.
- **Expected Benefit**: Reduces time-to-first-review to under 60 seconds with an optional guided sample problem (e.g. Two Sum).
- **Estimated Effort**: **Small** (1 engineering day).
- **Architectural Risk**: Low. Wraps existing `init` and `add` commands with a safe demonstration flag.
- **Validation Method**: CLI acceptance tests verifying non-destructive temporary workspace creation.

### 3. Rich Inline Side-by-Side Diff Viewer (`recall compare`)
- **Problem**: `coderecall recall compare` currently displays unified diff text, which can be hard to parse on wide terminal windows when comparing complex algorithmic attempts.
- **Expected Benefit**: Side-by-side terminal syntax-highlighted diffing using Rich's Columns and Syntax components.
- **Estimated Effort**: **Medium** (2 engineering days).
- **Architectural Risk**: Low. Presentation layer change in `cli/output.py`; no domain logic or state changes.
- **Validation Method**: Snapshot tests and terminal encoding fallback checks on legacy CP1252 consoles.

---

## P2: Validated Product Enhancements

### 4. Review Queue Calendar Export (`.ics`)
- **Problem**: Developers who plan their daily schedules around Google Calendar, Apple Calendar, or Outlook have to remember to run `coderecall today`.
- **Expected Benefit**: `coderecall export --format calendar --output reviews.ics` generates an iCalendar feed of upcoming review dates based on FSRS intervals.
- **Estimated Effort**: **Medium** (2 engineering days).
- **Architectural Risk**: Low. Standard RFC 5545 `.ics` formatting requires no external dependencies.
- **Validation Method**: Standard `.ics` schema compliance tests and import tests in calendar clients.

### 5. Adaptive FSRS Parameter Optimization
- **Problem**: FSRS v4 uses global default parameters ($w_0 \dots w_{16}$). As an individual user accumulates hundreds of reviews, their personalized memory decay rate may diverge from standard averages.
- **Expected Benefit**: A local training routine (`coderecall schedule optimize`) that runs offline gradient descent on the user's local `reviews` history to calculate optimal weights.
- **Estimated Effort**: **Large** (5 engineering days).
- **Architectural Risk**: Medium. Numerical stability requires careful bounds to prevent degenerate scheduling intervals.
- **Validation Method**: Simulation on historical review logs comparing predicted retrievability vs actual pass rates.

### 6. Local Test Vector Runner Adapter
- **Problem**: When practicing in active recall workspaces, users must mentally trace their code or write manual print statements to verify correctness.
- **Expected Benefit**: Support an optional `tests.json` or `assert` block that automatically runs the user's attempt against test cases upon `recall submit`.
- **Estimated Effort**: **Large** (4–5 engineering days).
- **Architectural Risk**: Medium. Requires strict timeout bounds and subprocess resource management to prevent infinite loops from hanging the CLI.
- **Validation Method**: Adversarial tests with timeout enforcement, memory capping, and syntax error resilience.

---

## P3: Speculative / Long-Term Explorations

### 7. Interactive Terminal Dashboard (TUI) with Textual
- **Problem**: Rich terminal tables and ASCII bars are static. An interactive full-screen dashboard would allow navigating problems, viewing forgetting curves, and starting recall sessions with arrow keys.
- **Expected Benefit**: Immersive developer experience on modern terminals.
- **Estimated Effort**: **Large** (2–3 engineering weeks).
- **Architectural Risk**: High. Adds a significant runtime dependency (`textual`), potential terminal compatibility issues, and maintenance overhead. Deferred until core CLI adoption is firmly established.
- **Validation Method**: User opt-in feedback and cross-platform terminal matrix verification.

### 8. WebAssembly / In-Browser Interactive Demo
- **Problem**: Potential users browsing GitHub may want to test the active recall workflow before installing Python or cloning the repository.
- **Expected Benefit**: A static GitHub Pages demo running CodeRecaller compiled to WebAssembly via Pyodide.
- **Estimated Effort**: **Medium-Large** (1–2 weeks).
- **Architectural Risk**: Low to repository (lives on separate gh-pages branch), but non-trivial build maintenance.
- **Validation Method**: Browser smoke tests verifying offline in-browser execution.

---

## Roadmap Review Schedule

This roadmap is reviewed quarterly by maintainers against user feedback, issue trends, and performance telemetry (collected via explicit user bug reports and surveys, never automated tracking).
