# Hermes Runtime Architecture Audit

## Repository

nilsnavi/hermes-agent


# Mission

Analyze current Hermes runtime architecture before refactoring.

This phase is analysis only.

DO NOT modify source code.


---

# Analyze Components


Primary modules:


gateway/

gateway/run.py


hermes_cli/

cli.py

web_server.py

web_routers/


tui_gateway/


hermes_state.py

hermes_state_common.py

hermes_state_dbfile.py



---

# Analyze


## Runtime lifecycle


Document:


- startup flow
- shutdown flow
- process ownership
- background workers


---

## Session lifecycle


Document:


- creation
- storage
- restoration
- mutation points


---

## Tool execution


Document:


- where tools are registered
- where tools are executed
- permission checks


---

## Provider routing


Document:


- model selection
- fallback logic
- provider abstraction


---

## Dependencies


Find:


- circular imports
- large modules
- duplicated logic
- mixed responsibilities


---

# Create Report


Create:


docs/architecture/runtime-audit.md


Report must contain:


## 1. Current architecture diagram


## 2. Runtime flow


## 3. Module responsibilities


## 4. Main architectural risks


## 5. Recommended migration order


## 6. Estimated refactoring complexity


---

# Rules


Do not:

- rename files
- move modules
- change APIs
- modify behavior


Only documentation.


---

# Acceptance Criteria


✓ No source code changes

✓ Audit document created

✓ Existing tests unchanged

✓ Migration plan prepared
