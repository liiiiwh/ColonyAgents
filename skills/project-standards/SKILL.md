---
name: project-standards
description: Use when initializing a project or before implementation to detect user-defined coding rules and existing lint, format, build, type-check, and test conventions from the repository, then summarize them into the SPEC.md standards section.
---

# Project Standards

Use this skill during initialization or before coding when you need to identify the project's real conventions instead of guessing them from language defaults.

## Priority order

Always resolve standards in this order:

1. user-defined standards files
2. project configuration files already present in the repo
3. conservative language/framework inference

Do not present inferred defaults as established project rules.

## Read first

Start with the smallest useful set:

- `docs/coding-standards.md`
- `docs/project-rules.md`
- `docs/engineering.md`
- `.editorconfig`
- `package.json`
- `pyproject.toml`
- `go.mod`
- `pom.xml`
- `build.gradle` / `build.gradle.kts`
- relevant lint, format, type-check, build, and test config files

Also read `Makefile`, `Taskfile.yml`, `justfile`, or CI workflow files when they define the actual commands the project uses.

## Detection checklist

### JavaScript / TypeScript

Look for:

- `eslint.config.*`
- `.eslintrc*`
- `.prettierrc*`
- `biome.json`
- `stylelint.config.*`
- `tsconfig.json`
- `package.json` scripts and devDependencies

### Python

Look for:

- `pyproject.toml`
- `ruff.toml`
- `.ruff.toml`
- `mypy.ini`
- `setup.cfg`
- `pytest.ini`

### Go

Look for:

- `go.mod`
- `.golangci.yml`
- `.golangci.yaml`
- `Makefile` commands using `gofmt`, `goimports`, or lint tools

### Java

Look for:

- `pom.xml`
- `build.gradle`
- `build.gradle.kts`
- `checkstyle.xml`
- `spotbugs` / `pmd` / `spotless` config

### Generic

Also detect:

- formatting rules
- lint rules
- test command conventions
- build command conventions
- type-check or static-analysis commands
- import ordering or file naming conventions

## Output format

Use this structure:

### 规范来源
- source file and why it is authoritative

### 检测结果
- formatting
- lint
- build
- test
- type-check / static analysis
- user-defined project rules

### 建议回填到 SPEC
- concise bullets suitable for `SPEC.md` -> `全局约束与编码约定`

### 待确认项
- unresolved conflicts
- inferred-only rules
- missing standards

## Decision rules

- Prefer explicit project config over language defaults.
- Prefer user-authored local docs over tool defaults.
- If multiple configs conflict, report the conflict instead of picking silently.
- If no standard is found, use conservative inference and label it `待确认`.
- Keep the summary at project-rule level; do not turn `SPEC.md` into a full lint config dump.
