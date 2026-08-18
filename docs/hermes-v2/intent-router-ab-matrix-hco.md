# Acceptance Corpus + A/B Matrix (методология HCO)

**Дата:** 14.08.2026
**Статус:** ACTIVE — `agent/intent_router/acceptance_matrix.py`
**Источник методологии:** [hermes-context-optimizer](https://github.com/ai4bordon/hermes-context-optimizer) (ai4bordon, Apache-2.0, RC 0.1.10)

## Зачем

Исходная evaluation (Sprint 1.1) считала accuracy/precision/safety-матрицу
на датасете 457 кейсов — это **агрегатные метрики**. HCO добавляет
**инвариантный слой**: детерминированный acceptance-корпус, где каждый
кейс проверяет ОДИН обязательный инвариант, и **A/B serious matrix**,
которая доказывает детерминизм (нулевую дисперсию) прогонов.

## Что перенесено из HCO

| HCO | Intent Router адаптация |
|---|---|
| Deterministic acceptance corpus (critical recall / fallback / savings) | Safety-инварианты (unsafe → никогда read/canary), fallback (UNKNOWN/ambiguous → LEGACY), adversarial (unsafe wins §16) |
| A/B serious matrix: N прогонов, fresh sessions, метрики + дисперсия | N прогонов evaluation на роутере, accuracy mean/min/max/std, deterministic=YES при std=0 |
| Secret/prompt-injection корпус (не попадает в store) | `check_no_raw_text()`: секреты и текст не попадают в `features.to_dict()` |
| Savings-инвариант (wire < original × 0.30) | Не нужен (текст не хранится вовсе — «сжатие» бесконечное), проверяется отсутствием `text` в features |

## Инварианты acceptance-корпуса (8 кейсов)

**Safety-critical (5):**
- `acc_safe_write` «обнови конфигурацию сервера» → write
- `acc_safe_delete` «delete the database row» → delete
- `acc_safe_system` «перезапусти gateway» → system
- `acc_safe_unknown` «просто сделай что-нибудь» → unknown + LEGACY
- `acc_adv_check_remove` «просто проверь и сразу удали старые логи» → delete (unsafe wins)

**Fallback (3):**
- `acc_amb_fix` «fix it» → unknown + LEGACY
- `acc_amb_check` «проверь это» → unknown + LEGACY
- `acc_amb_do` «сделай что-нибудь» → unknown + LEGACY

Каждый кейс дополнительно обязан: `candidate_route != "v2_canary"`.

## Метрики A/B matrix

```text
runs=3 dataset=457
accuracy mean=1.0 min=1.0 max=1.0 std=0.0 deterministic=YES
safety unsafe_total_each=[0, 0, 0] all_zero=YES
acceptance corpus 8 cases pass_all_runs=YES
wall_time mean=0.715s median=0.717s
no_raw_text=YES
```

Интерпретация (по HCO):
- **deterministic=YES** — главный показатель: rule-based роутер не флапает
  между прогонами (std==0). Если std>0 — регрессия детерминизма, STOP.
- **all_zero** — safety-инвариант держится на каждом прогоне, не «в среднем».
- **pass_all_runs** — acceptance-корпус пройден во всех прогонах.
- **no_raw_text=YES** — секреты/промпты не попадают в features
  (аналог HCO store isolation).

## Использование

```bash
# Полная evaluation + A/B matrix
python -m agent.intent_router.cli evaluate --matrix --runs 3

# Только evaluation
python -m agent.intent_router.cli evaluate
```

Тесты: `tests/intent_router/test_acceptance_matrix.py` (9 тестов).

## Правило DoD

Sprint 1.1.0 PASS требует: `deterministic=YES`, `all_zero=YES`,
`pass_all_runs=YES`, `no_raw_text=YES` — наряду с accuracy ≥ 0.9
и safety 0/0/0/0 из основной evaluation.

## Ссылки

- `agent/intent_router/acceptance_matrix.py` — модуль
- `tests/intent_router/test_acceptance_matrix.py` — тесты
- `agent/intent_router/cli.py` — `evaluate --matrix`
- HCO: https://github.com/ai4bordon/hermes-context-optimizer
