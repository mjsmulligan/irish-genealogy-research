# GitHub Repository Structure

This document outlines the organization of the repository to maintain a clean separation between data schemas, conceptual design, and source code.

## Directory Layout

```text
├── .github/                  # GitHub workflow definitions (CI/CD, validations)
├── docs/                     # Modular documentation
│   ├── conceptual_model.md   # Domain rules and core entities
│   ├── github_project.md     # Repo organization and workflows (this file)
│   ├── database_mapping.md   # PostgreSQL schema specifications
│   ├── ingestion_rules.md    # CSV format specifications and pipeline logic
│   └── vocabularies.md       # Controlled vocabularies and validation lists
├── schema/                   # SQL DDL files and database migrations
│   └── structural_schema.sql # Current PostgreSQL table definitions
├── src/                      # Source scripts (Python data extraction/automation)
└── data/                     # Local temporary storage for source CSV structures
