# GitHub Setup — One-Time Steps

These are the commands to bootstrap the repo. Run them in order.

## 1. Create the local repo

From an empty parent directory:

```bash
mkdir aiops-logguard
cd aiops-logguard
git init
git branch -M main

# Copy the provided context files into this directory:
# - CLAUDE.md
# - README.md
# - .gitignore
# - .github/workflows/ci.yml
# - docs/architecture/*.md and *.sql
```

## 2. Create the empty subdirectories with `.gitkeep` so git tracks them

```bash
mkdir -p backend/{api,ingestion,ml,rag,training,tools,artifacts,tests}
mkdir -p frontend/src
mkdir -p docs/{report,paper,diagrams,gantt}

# git won't track empty dirs — drop a placeholder
touch backend/api/.gitkeep
touch backend/ingestion/.gitkeep
touch backend/ml/.gitkeep
touch backend/rag/.gitkeep
touch backend/training/.gitkeep
touch backend/tools/.gitkeep
touch backend/artifacts/.gitkeep
touch backend/tests/.gitkeep
touch frontend/src/.gitkeep
touch docs/report/.gitkeep
touch docs/paper/.gitkeep
touch docs/diagrams/.gitkeep
touch docs/gantt/.gitkeep
```

## 3. Initial commit

```bash
git add .
git commit -m "Initial repo structure with CLAUDE.md and architecture docs"
```

## 4. Push to GitHub

Create the repo on github.com first (private is fine; you can switch later). Then:

```bash
git remote add origin git@github.com:<your-username>/aiops-logguard.git
git push -u origin main
```

## 5. Branch protection (do this on github.com)

**Settings → Branches → Add branch protection rule** for `main`:

- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging
  - Select: `backend` and `frontend` jobs from the CI workflow
- ✅ Require branches to be up to date before merging
- ✅ Do not allow bypassing the above settings

This stops anyone (including you, accidentally) from pushing broken code to main.

## 6. Add collaborators

**Settings → Collaborators → Add people** — add Person B and Person C with **Write** access (not Admin).

## 7. Enable Actions

If GitHub doesn't auto-enable: **Settings → Actions → General → Allow all actions and reusable workflows.**

The CI workflow at `.github/workflows/ci.yml` will now run on every PR and push to main.

## 8. Set up your local dev environment

```bash
# Backend
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
# (create requirements.txt as you add libs)

# In another shell, you'll do frontend setup later
```

## 9. Daily workflow for the team

```bash
# Always start from up-to-date main
git checkout main
git pull

# Create a feature branch
git checkout -b backend/api-skeleton  # or frontend/dashboard, docs/lit-review

# Work, commit
git add .
git commit -m "Add stub anomaly endpoints"
git push -u origin backend/api-skeleton

# Open a PR on github.com → wait for CI → merge
```

**Branch naming:**
- Person A: `backend/<feature>`
- Person B: `frontend/<feature>`
- Person C: `docs/<feature>`

**Never push directly to main.** Branch protection will reject it anyway, but build the habit.

## 10. Tell Person B and Person C

Once the repo is live and they're added as collaborators, send them:
- The clone URL
- The link to their respective brief (the docx you sent Person B, and Person C's plan from your earlier conversation)
- A reminder that branch names follow the convention above

That's it — you're set up.
