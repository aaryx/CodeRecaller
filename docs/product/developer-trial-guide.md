# CodeRecaller: Developer Trial Guide & Evaluation Scenario

## Purpose

This guide provides an evaluation protocol and lightweight questionnaire for developers testing CodeRecaller for the first time.

The scenario uses harmless, generic sample data and takes approximately **10 to 15 minutes** to complete. It requires zero cloud accounts, zero API keys, and zero confidential code.

---

## Prerequisites

- **Python**: 3.11, 3.12, 3.13, or 3.14 installed.
- **Git**: Installed and available on your PATH.
- **OS**: Windows (PowerShell/CMD), macOS (Terminal/Zsh), or Linux (Bash).

---

## Step-by-Step Trial Scenario

### Step 1: Install CodeRecaller (Estimated time: 2 minutes)

In an isolated virtual environment or using `pipx`:

```bash
# Option A: Clone and install locally
git clone https://github.com/aaryx/CodeRecaller.git
cd CodeRecaller
pip install .

# Verify the CLI launcher is available
coderecall --version
coderecall --help
```

### Step 2: Initialize a Practice Directory (Estimated time: 1 minute)

Create a dedicated practice folder (outside the CodeRecaller repository) to store your solutions:

```bash
mkdir ~/coding-practice  # Or C:\coding-practice on Windows
cd ~/coding-practice
git init
coderecall init
```

*Note: CodeRecaller creates `.coderecall/` and automatically adds it to your `.gitignore` to keep your learning schedules and attempt histories strictly local and private.*

### Step 3: Capture Your First Solution (Estimated time: 3 minutes)

Create a simple sample solution (e.g. `palindrome.py`):

```python
# palindrome.py
def isPalindrome(s: str) -> bool:
    clean = "".join(c.lower() for c in s if c.isalnum())
    return clean == clean[::-1]
```

Capture the solution into the catalog:

```bash
coderecall add --file palindrome.py --title "Valid Palindrome" --platform leetcode --external-id 125 --topics string,two-pointers
```

Verify it was captured:

```bash
coderecall problems
coderecall search "Palindrome"
coderecall problem 125
```

### Step 4: Practice Active Recall (Estimated time: 4 minutes)

Test CodeRecaller's active recall workspace:

```bash
coderecall revise 125
```

1. Notice that CodeRecaller conceals your original solution and creates a blank workspace.
2. In interactive mode, select `[e]` to open the workspace in your editor or edit the file directly in `.coderecall/workspaces/...`.
3. Re-implement the solution from memory.
4. Select `[s]` to submit your self-assessment:
   - Self-assessed outcome: pass or fail
   - Confidence rating: 1 to 4 (or 1 to 5)
5. Review the resulting interval calculated by the Free Spaced Repetition Scheduler (FSRS).
6. Post-submission, compare your attempt with the original solution:
   ```bash
   coderecall recall compare <recall_id>
   ```

### Step 5: Check Analytics & Export (Estimated time: 2 minutes)

Review your local learning metrics and verify data ownership:

```bash
coderecall status
coderecall today
coderecall stats
coderecall dashboard
coderecall export --format html --output practice-report.html
```

Open `practice-report.html` in your browser to inspect your local progress report.

### Step 6: Backup & Verification (Estimated time: 1 minute)

```bash
coderecall backup
```

---

## Feedback Questionnaire

After completing the scenario above, please share your thoughts using the template below.

> [!IMPORTANT]
> **Privacy First**: Do **NOT** include private source code, employer proprietary code, API tokens, passwords, or personal credentials in your feedback.

```markdown
### CodeRecaller Developer Feedback

**Environment:**
- Operating System: [e.g., Ubuntu 22.04, macOS 14, Windows 11]
- Shell: [e.g., Bash, Zsh, PowerShell 7]
- Python Version: [e.g., 3.12.2]

**1. Onboarding & Installation:**
- Did the installation succeed on your first attempt? [Yes / No]
- If no, what error message or friction did you encounter?
- Did the README quickstart instructions match what happened on your machine?

**2. Active Recall & Workspace Experience:**
- How did the blank attempt workspace feel compared to traditional flashcards or notes?
- Was it clear where your attempt code was saved?
- Did you find the self-assessment rating scale intuitive?

**3. Workflow & CLI Ergonomics:**
- Which command(s) felt most intuitive?
- Which command(s) felt confusing or had unexpected behavior?
- Was any error message unhelpful or lacking clear remediation instructions?

**4. Product Value:**
- Would you use CodeRecaller for ongoing coding interview preparation or daily learning? [Yes / Maybe / No]
- What is the single most important missing feature that would make this indispensable to your workflow?

**5. Additional Comments:**
[Any other observations, edge cases, or ideas]
```

Submit completed feedback as an issue labeled `feedback` on the [CodeRecaller GitHub Issue Tracker](https://github.com/aaryx/CodeRecaller/issues).
