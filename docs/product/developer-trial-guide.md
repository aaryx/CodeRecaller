# CodeRecaller: Developer Beta Trial Guide & Evaluation Protocol

## Purpose

This guide provides a reproducible evaluation protocol and lightweight feedback pack for developers participating in the small beta trial of **CodeRecaller**.

- **Estimated Time**: 10–15 minutes for the initial session; 2–3 minutes for an optional 7-day follow-up.
- **Privacy First**: 100% local-first. Zero accounts, zero API keys, zero network telemetry, and zero employer/proprietary code required.
- **Scope**: Evaluates first-session onboarding, active recall ergonomics, and review scheduling using harmless sample data. Docker is **not** required for this trial.

---

## Prerequisites

1. **Python**: Python `3.11`, `3.12`, `3.13`, or `3.14` installed and accessible on `PATH`.
2. **Git**: Installed and available on `PATH`.
3. **Operating System**: Linux (Bash), macOS (Zsh/Bash), or Windows (PowerShell / Command Prompt).
4. **Package Tool**: `pipx` (recommended) or a standard Python virtual environment.

---

## Step 1: Install the Pinned Release Candidate (2 minutes)

To ensure all testers evaluate the exact verified release candidate, install using the full candidate commit SHA (`133d3937a03efb085621ca9b3b2e0550293f4396`):

### Option A: Via `pipx` (Recommended)
```bash
pipx install "git+https://github.com/aaryx/CodeRecaller.git@133d3937a03efb085621ca9b3b2e0550293f4396"
```

### Option B: In an Isolated Virtual Environment
```bash
# Create and activate a temporary environment
python -m venv cr-test-venv

# On Linux/macOS:
source cr-test-venv/bin/activate

# On Windows PowerShell:
.\cr-test-venv\Scripts\Activate.ps1

# Install candidate directly from GitHub
pip install "git+https://github.com/aaryx/CodeRecaller.git@133d3937a03efb085621ca9b3b2e0550293f4396"
```

### Confirm Installation & Version
Run:
```bash
coderecall --version
```
Expected output:
```
0.3.0
```

Verify help output is functional:
```bash
coderecall --help
```

---

## Step 2: Initialize a Disposable Practice Directory (1 minute)

Create a clean, disposable practice folder **outside** any existing project repositories:

```bash
# Linux / macOS:
mkdir ~/cr-beta-practice && cd ~/cr-beta-practice

# Windows PowerShell:
New-Item -ItemType Directory -Path "$HOME\cr-beta-practice" -Force; Set-Location "$HOME\cr-beta-practice"
```

Initialize Git and the CodeRecaller workspace:
```bash
git init
coderecall init
```

> [!NOTE]
> `coderecall init` creates the local `.coderecall/` directory and automatically adds it to `.gitignore`. Your practice schedule and attempt history remain strictly offline and private.

Verify local workspace health:
```bash
coderecall doctor
```
Expected: All diagnostic checks pass (`Errors: 0`).

---

## Step 3: Record a Complete Sample Solution (2 minutes)

Generate a harmless sample solution file (`palindrome.py`) directly in your practice directory:

### On Linux / macOS (Bash / Zsh):
```bash
cat << 'EOF' > palindrome.py
def is_palindrome(s: str) -> bool:
    """Return True if the string is a palindrome, ignoring casing and non-alphanumeric chars."""
    clean = "".join(c.lower() for c in s if c.isalnum())
    return clean == clean[::-1]
EOF
```

### On Windows (PowerShell):
```powershell
Set-Content palindrome.py @"
def is_palindrome(s: str) -> bool:
    """Return True if the string is a palindrome, ignoring casing and non-alphanumeric chars."""
    clean = "".join(c.lower() for c in s if c.isalnum())
    return clean == clean[::-1]
"@
```

Capture the solution into your CodeRecaller catalog:
```bash
coderecall add --file palindrome.py --title "Valid Palindrome" --topics string,two-pointers
```

The CLI will display the captured problem details:
```
problem_id: <ID>
created: True
solutions: ['palindrome.py']
```

> [!IMPORTANT]
> **Dynamic Problem IDs**: CodeRecaller assigns an internal problem ID or slug. Note the exact ID returned in `problem_id` (you can also view all stored problems anytime by running `coderecall problems`). In subsequent commands, replace `<problem_id>` with this value.

---

## Step 4: Practice Active Recall (4 minutes)

Active recall is the core learning loop. When you revise, CodeRecaller **hides** your previous code and generates an empty workspace so you practice retrieving the logic from memory rather than passively rereading it.

Start the revision session using your assigned ID:
```bash
coderecall revise <problem_id>
```

You will see the session prompt:
```
recall_id: <recall_id>
workspace: .coderecall/workspaces/<recall_id>/solution.py
[e] Edit blank workspace [h] Hint [s] Submit [p] Pause [c] Continue [r] Reveal [q] Quit
```

1. **Open Workspace**:
   - Press `e` to open the blank workspace in your default editor (or open the file `.coderecall/workspaces/<recall_id>/solution.py` in your preferred editor).
2. **Re-implement**:
   - Write the function implementation from memory into the file and save it.
3. **Submit Self-Assessment**:
   - Return to your terminal and press `s`.
   - `Solved successfully? (self-assessment)`: Answer `y` (pass) or `n` (fail).
   - `Confidence (1-5)`: Rate how well you recalled the pattern (e.g. `4`).
   - `Attempts`: Press Enter for default `1`.

*(Note: CodeRecaller requires saved code in the workspace before accepting a passing grade to prevent accidental empty submissions).*

---

## Step 5: Inspect Next Review & Learning State (2 minutes)

Inspect how the Free Spaced Repetition Scheduler (FSRS) scheduled your next practice:

```bash
# View problem details and review schedule
coderecall problem <problem_id>

# Check your queue for reviews due today
coderecall today

# Check practice statistics
coderecall stats
```

Observe:
- `State`: Promoted from `NEW` to `REVIEW`.
- `Stability` & `Interval`: The calculated memory stability and future due date.
- `today`: If you passed today, the problem is not due today and will appear in future queues.

### Optional Post-Submission Comparison
To inspect a line-by-line diff between your recall attempt and the canonical solution:
```bash
coderecall recall compare <recall_id>
```
*(Notice that `recall compare` was blocked before submission to protect recall memory integrity, but is fully accessible now).*

---

## Step 6: Multi-Format Export (1 minute)

Test data ownership and reporting:
```bash
coderecall export --format html --output practice-report.html
```
Open `practice-report.html` in your web browser to review your local learning report.

---

## Seven-Day Follow-Up Protocol

Spaced repetition functions over real elapsed time. **Do not modify your system clock.**

Approximately 7 days after your initial session (or whenever convenient):
1. Navigate back to your practice folder (`cd ~/cr-beta-practice`).
2. Run `coderecall today` to inspect whether any problems have become due.
3. If due, run `coderecall revise <problem_id>` to complete a follow-up review.
4. Complete Part 2 of the feedback form below.

---

## Beta Tester Feedback Pack

Please copy the questionnaire below, fill in your observations, and share it with the project owner (or open an issue labeled `feedback` on the [CodeRecaller GitHub Issue Tracker](https://github.com/aaryx/CodeRecaller/issues)).

> [!CAUTION]
> **Privacy Notice**: Do **NOT** include any proprietary source code, employer materials, credentials, API keys, or personal identifying data.

```markdown
### CodeRecaller Beta Trial Feedback

#### 1. Environment & Setup
- **Operating System**: [e.g., Ubuntu 24.04, macOS Sonoma, Windows 11]
- **Shell**: [e.g., Bash, Zsh, PowerShell 7, CMD]
- **Python Version**: [e.g., 3.12.3]
- **Installed Version**: [Output of `coderecall --version`]
- **Installation Method**: [pipx / venv]

#### 2. First-Session Observed Facts (Factual Completion)
- Did installation succeed on the first attempt without manual workarounds? [Yes / No]
- Did `coderecall init` and `coderecall doctor` pass? [Yes / No]
- Did you successfully record the sample solution (`coderecall add`)? [Yes / No]
- Did you complete the active recall loop (`revise` -> edit workspace -> `submit`)? [Yes / No]
- Were scheduled review dates updated in `coderecall problem <id>`? [Yes / No]
- Did any command crash, raise an unhandled exception, or exit unexpectedly? [Yes / No]
  *(If yes, please paste the exact command and terminal error output)*

#### 3. First-Session Ergonomics & Usability (Opinions)
- Where did you encounter confusion or need to re-read instructions?
- How did the blank workspace compare to traditional flashcards (Anki) or static notes?
- Did the interactive revision prompt (`[e] Edit [s] Submit...`) feel intuitive?
- Which CLI command felt most natural? Which felt awkward?

#### 4. Seven-Day Follow-Up (After ~7 Days)
- Did you return to the practice directory after Day 1? [Yes / No]
- How many additional revision sessions did you complete? [Number]
- When revising, did you recall the implementation before checking the original solution? [Yes / Partially / No]
- If you did not return or continue using it, what was the primary friction or blocker?
- What single change would make CodeRecaller indispensable to your ongoing practice?

#### 5. Product Relevance
- Would you use CodeRecaller for your actual interview prep or coding practice? [Yes / Maybe / No]
- Why or why not?
```

---

## Owner Instructions: How to Run the Trial

### 1. Copyable Invitation Message
Copy and send this message to 2–3 volunteer software engineers or interview candidates:

```text
Hi [Name]!

I’m running a small, private developer beta for CodeRecaller—a local-first Python CLI designed for coding practice using active recall and spaced repetition (FSRS). It’s completely offline, zero-telemetry, and keeps all solution history in your own local Git repo.

Could you spare 10–15 minutes to run through a quick test scenario on your machine?

Here is the step-by-step guide:
https://github.com/aaryx/CodeRecaller/blob/main/docs/product/developer-trial-guide.md

To install the exact tested candidate:
pipx install "git+https://github.com/aaryx/CodeRecaller.git@133d3937a03efb085621ca9b3b2e0550293f4396"

The trial uses a harmless palindrome sample function in a disposable folder—no cloud accounts, no API keys, and no real work code required.

Whenever you finish, just reply with the quick feedback template at the bottom of the guide. Thank you so much for your feedback!
```

### 2. Decision Framework for Incoming Feedback

When feedback arrives from the 2–3 testers, classify each finding objectively:

| Category | Indicator | Immediate Maintainer Action |
| :--- | :--- | :--- |
| **P0: Defect / Data Loss** | Crashes, unhandled exceptions, corrupted workspaces, state write failures. | Stop new trials; diagnose reproduction; write failing regression test; ship patch immediately. |
| **P1: Onboarding Friction** | Multiple testers confused by the same prompt, editor launch failure, or path confusion. | Simplify the specific CLI UX or prompt text without altering core architecture. |
| **P2: Feature Requests** | Requests for automated test runners, multi-file support, or IDE extensions. | Log in `docs/product/roadmap.md`; investigate the underlying root workflow need before implementing. |
| **P3: Low Retention / Drop-off** | Testers do not return for due reviews after Day 1. | Investigate workflow habit friction and terminal reminder mechanisms rather than building speculative features. |
