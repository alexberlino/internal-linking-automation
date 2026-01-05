# Internal Linking Automation

Python-based pipeline for internal linking analysis and reporting.

The repository contains processing logic only.  
All client-specific input and output data is intentionally excluded from version control.

---

## Repository Scope

This codebase covers:
- internal linking analysis
- opportunity detection
- report generation

It does not contain:
- client data
- credentials
- production outputs

---

## Directory Structure

.
├── phases/              # Processing steps (Python scripts)
├── data/
│   ├── input/           # Client input data (ignored by Git)
│   └── output/          # Generated reports (ignored by Git)
├── .gitignore
└── README.md

---

## Data Handling

- data/input/ and data/output/ are ignored via .gitignore
- These directories are used only for local execution
- No client files are committed or pushed

This setup is intentional to avoid accidental data exposure.

---

## Execution

1. Create and activate a virtual environment
2. Install dependencies
3. Place input files in:
   data/input/
4. Run the relevant phase scripts from phases/

Outputs are written to:
data/output/

---

## Version Control Rules

Tracked:
- Python source files
- Documentation
- Configuration files (non-sensitive)

Ignored:
- Client input data
- Generated outputs
- Virtual environments
- Cache / OS files


This repository is intended for internal technical use only.  
Client-specific logic and data handling are managed outside of version control.
