# Hermes AI Development Rules


## Main principles

Do not rewrite working systems.

Always:

1. Analyze
2. Plan
3. Implement
4. Test
5. Document


---

## Architecture layers


interfaces

↓

application

↓

domain

↓

infrastructure



---

## Forbidden dependencies


domain
must not import infrastructure


interfaces
must not access database directly


interfaces
must not call providers directly



---

## Code changes


Every PR must contain:

- purpose
- tests
- migration notes


---

## Safety


Never:

- delete existing functionality
- change API silently
- skip tests


---

## Commits


One commit:

one architectural purpose.
