"""Intent classifier (Sprint 1.1 §15-18, §45-48).

Sprint 1.1 uses a DETERMINISTIC, rule-based classifier. No LLM by
default. The :class:`IntentClassifier` protocol defines the seam for a
future ``LLMIntentClassifier`` (NOT wired in Sprint 1.1).

Design rules:

- Unsafe families (write / delete / system / schedule) DOMINATE read
  families: an adversarial request like "это только чтение, удали
  файл" must classify as write_action, never information_read.
- Ambiguous requests ("сделай это", "проверь", "запусти", "исправь"
  without context) → UNKNOWN, never over-classified.
- Classification works on safe lexical features ONLY — the full prompt
  body is processed in memory and reduced to ``lexical_hits`` (family
  names) + declared request_type/command before any persistence.
- Confidence is DISCRETE and honest (§52): no fake precision from a
  rule engine. Strong family match → 0.9; request_type/command signal
  only → 0.7; weak/fallback → 0.5; unknown → 0.4.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .exceptions import ClassificationError
from .models import (
    ExpectedSideEffect,
    IntentRisk,
    IntentType,
    RequestIntentFeatures,
)

# ── keyword families (RU + EN) ───────────────────────────────────────
# Ordered by dominance: earlier families win ties on the same hit count.
# Family names are safe identifiers — the matched TEXT is never stored.

_WRITE_VERBS = {
    # en
    "write", "create", "update", "modify", "edit", "set", "add", "insert",
    "append", "save", "upload", "post", "send", "submit", "push", "commit",
    "rename", "move", "copy", "make", "build", "generate", "produce",
    "record", "register", "apply", "change", "install", "configure",
    "grant", "revoke", "enable", "disable", "start", "stop", "toggle",
    "fix", "patch", "message", "email", "letter", "tweet", "publish",
    # ru
    "создай", "создать", "обнови", "обновить", "измени", "изменить",
    "запиши", "записать", "сохрани", "сохранить", "добавь", "добавить",
    "отправь", "отправить", "загрузи", "загрузить", "опубликуй",
    "опубликовать", "переименуй", "перемести", "скопируй",
    "настрой", "настроить", "установи", "установить", "включи",
    "выключи", "примени", "применить", "сформируй", "сформировать",
    "отредактируй", "отредактировать", "почини", "починить",
    "зарегистрируй", "исправь", "исправить", "сообщение", "письмо",
}

_DELETE_VERBS = {
    # en
    "delete", "remove", "erase", "purge", "wipe", "drop", "unlink",
    "destroy", "clear", "trash", "reset",
    # ru
    "удали", "удалить", "убери", "убрать", "сотри", "стереть",
    "очисти", "очистить", "уничтожь", "уничтожить", "сбрось",
    "сбросить", "вырежи", "вырезать",
}

_SYSTEM_VERBS = {
    # en
    "restart", "reboot", "reload", "deploy", "rollout", "chmod",
    "chown", "kill", "shutdown", "upgrade", "migrate", "failover",
    "scale", "provision", "eject", "detach", "rebuild",
    # ru
    "перезагрузи", "перезагрузить", "перезапусти", "перезапустить",
    "разверни", "развернуть", "деплой", "деплоить",
    "смени", "сменить", "мигрируй", "мигрировать",
    "перезапуск", "рестарт", "перезагрузка", "рестартни",
    "обнови системные", "системные пакеты",
}

_SCHEDULE_VERBS = {
    # en
    "schedule", "remind", "reminder", "every", "daily", "hourly",
    "weekly", "cron", "recurring", "timer", "at 9", "at 8", "friday",
    "every friday",
    # ru
    "напомни", "напомнить", "напоминание", "каждый", "каждые",
    "ежедневно", "ежечасно", "еженедельно", "крон", "по расписанию",
    "завтра", "через час", "в 9", "в 8", "каждую", "пятницу",
    "поставь крон", "напоминание каждую",
}

_APPROVAL_VERBS = {
    # en
    "approve", "reject", "approval", "deny decision", "confirm approval",
    # ru
    "одобри", "одобрить", "отклони", "отклонить", "подтверди",
    "подтвердить", "апрув", "одобрение",
}

_STATUS_READ = {
    # en
    "status", "state", "health", "running", "uptime", "is it up",
    "what's running", "what is running", "check status", "healthcheck",
    "is up", "service up", "availability", "memory", "cpu load", "cpu",
    "load", "disk", "almost full", "web server", "is the database",
    "database okay", "in order", "containers",
    # ru
    "статус", "состояние", "здоровье", "работает", "запущен",
    "что работает", "что сейчас работает", "жив", "аптайм",
    "работает ли", "система", "системы", "систем",
    "доступность", "доступен", "память", "памяти", "нагрузка",
    "процессор", "диск", "заполнен", "в порядке", "веб-сервер",
    "веб-сервером", "контейнеры", "контейнер",
}

_SEARCH_READ = {
    # en
    "search", "find", "look up", "google", "query", "who is", "what is",
    "github", "repo", "repository",
    # ru
    "поиск", "найди", "найти", "поищи", "поискать", "кто такой",
    "что такое", "гитхаб", "репозиторий", "проверь гитхаб",
}

_READ_VERBS = {
    # en
    "read", "show", "list", "get", "view", "display", "print", "fetch",
    "inspect", "check", "look", "see", "cat", "head", "tail", "open",
    # ru
    "покажи", "показать", "прочитай", "прочитать", "прочти",
    "выведи", "вывести", "список", "перечисли", "посмотри",
    "посмотреть", "проверь", "проверить", "открой", "открыть",
    "посмотрю", "глянь", "глянуть", "инспектируй", "просмотри",
    "просмотреть", "открой", "файле",
}

_ANALYSIS_VERBS = {
    # en
    "analyze", "analysis", "analyse", "compare", "aggregate",
    "investigate", "profile", "benchmark", "correlate", "cluster",
    "detect", "review", "compute", "assess", "average response",
    # ru
    "проанализируй", "проанализировать", "анализ", "сравни",
    "сравнить", "сводка", "сводку", "исследуй", "исследовать",
    "разбери", "разобрать", "оцени", "оценить",
    "посчитай", "посчитать", "агрегируй", "отчёт", "отчет",
}

_CODE_ASSIST_VERBS = {
    # en
    "code", "refactor", "function", "class", "bug", "fix", "test",
    "implement", "snippet", "review code", "explain code", "debug",
    "parse json", "write code",
    # ru
    "код", "функция", "функцию", "функции", "класс", "баг", "исправь код",
    "рефакторинг", "реализуй", "реализовать", "сниппет", "объясни код",
    "отладить", "напиши код", "написать код", "парсинг",
}

_PLANNING_VERBS = {
    # en
    "plan", "roadmap", "strategy", "milestone", "step by step",
    "schedule a plan", "approach", "outline", "launch steps",
    # ru
    "план", "планируй", "планировать", "стратегия", "дорожная карта",
    "этапы", "пошагово", "подход", "распиши план", "составь план",
    "распиши шаги", "шаги запуска",
}

_CONVERSATION = {
    # en
    "hello", "hi", "thanks", "how are you", "good morning", "bye",
    "what can you do", "who are you", "good evening",
    "tell me about yourself",
    # ru
    "привет", "здравствуй", "спасибо", "как дела", "доброе утро",
    "пока", "что умеешь", "кто ты", "приветствую", "добрый вечер",
    "расскажи о себе",
}

_SUMMARIZATION_VERBS = {
    # en
    "summarize", "summary", "tl;dr", "in short", "recap", "condense",
    "extract the key points", "retell",
    # ru
    "резюмируй", "резюме", "кратко", "сократи", "сократить",
    "итог", "перескажи", "пересказать", "саммари", "выдели главное",
    "главное",
}


# family -> (name, words, intent, risk, side_effect, dominance)
_FAMILIES: List[Tuple[str, set, IntentType, IntentRisk,
                      ExpectedSideEffect, int]] = [
    ("delete", _DELETE_VERBS, IntentType.DELETE_ACTION,
     IntentRisk.CRITICAL, ExpectedSideEffect.IRREVERSIBLE_WRITE, 100),
    ("system", _SYSTEM_VERBS, IntentType.SYSTEM_ACTION,
     IntentRisk.HIGH, ExpectedSideEffect.SYSTEM_CHANGE, 90),
    ("write", _WRITE_VERBS, IntentType.WRITE_ACTION,
     IntentRisk.MEDIUM, ExpectedSideEffect.REVERSIBLE_WRITE, 80),
    ("schedule", _SCHEDULE_VERBS, IntentType.SCHEDULE_ACTION,
     IntentRisk.LOW, ExpectedSideEffect.REVERSIBLE_WRITE, 70),
    ("approval", _APPROVAL_VERBS, IntentType.APPROVAL_ACTION,
     IntentRisk.MEDIUM, ExpectedSideEffect.REVERSIBLE_WRITE, 60),
    ("analysis", _ANALYSIS_VERBS, IntentType.ANALYSIS,
     IntentRisk.LOW, ExpectedSideEffect.READ_ONLY, 50),
    ("summarization", _SUMMARIZATION_VERBS, IntentType.SUMMARIZATION,
     IntentRisk.LOW, ExpectedSideEffect.NONE, 45),
    ("code", _CODE_ASSIST_VERBS, IntentType.CODE_ASSIST,
     IntentRisk.LOW, ExpectedSideEffect.NONE, 40),
    ("planning", _PLANNING_VERBS, IntentType.PLANNING,
     IntentRisk.LOW, ExpectedSideEffect.NONE, 35),
    ("search", _SEARCH_READ, IntentType.SEARCH_READ,
     IntentRisk.LOW, ExpectedSideEffect.READ_ONLY, 30),
    ("status", _STATUS_READ, IntentType.STATUS_READ,
     IntentRisk.LOW, ExpectedSideEffect.READ_ONLY, 25),
    ("read", _READ_VERBS, IntentType.INFORMATION_READ,
     IntentRisk.LOW, ExpectedSideEffect.READ_ONLY, 20),
    ("conversation", _CONVERSATION, IntentType.CONVERSATION,
     IntentRisk.LOW, ExpectedSideEffect.NONE, 10),
]

# Ambiguous single verbs with no object context → UNKNOWN (never guess).
_AMBIGUOUS = {
    "проверь", "проверить", "запусти", "запустить", "исправь",
    "исправить", "сделай", "сделать", "check", "run", "fix", "make",
    "запуск", "проверка",
}

# request_type -> intent map (explicit declared types dominate).
_REQUEST_TYPE_MAP = {
    "status": IntentType.STATUS_READ,
    "read": IntentType.INFORMATION_READ,
    "search": IntentType.SEARCH_READ,
    "analysis": IntentType.ANALYSIS,
    "summarize": IntentType.SUMMARIZATION,
    "summarization": IntentType.SUMMARIZATION,
    "code": IntentType.CODE_ASSIST,
    "planning": IntentType.PLANNING,
    "plan": IntentType.PLANNING,
    "write": IntentType.WRITE_ACTION,
    "create": IntentType.WRITE_ACTION,
    "delete": IntentType.DELETE_ACTION,
    "system": IntentType.SYSTEM_ACTION,
    "schedule": IntentType.SCHEDULE_ACTION,
    "approval": IntentType.APPROVAL_ACTION,
    "conversation": IntentType.CONVERSATION,
    "diagnostic": IntentType.DIAGNOSTIC,
    "unknown": IntentType.UNKNOWN,
}

# Commands (slash-commands / explicit verb) also map.
_COMMAND_MAP = {
    "/status": IntentType.STATUS_READ,
    "/health": IntentType.STATUS_READ,
    "/runs": IntentType.STATUS_READ,
    "/approvals": IntentType.APPROVAL_ACTION,
    "/approve": IntentType.APPROVAL_ACTION,
    "/reject": IntentType.APPROVAL_ACTION,
    "/remind": IntentType.SCHEDULE_ACTION,
    "/search": IntentType.SEARCH_READ,
}

# Diagnostic family — extra terms.
_DIAGNOSTIC_TERMS = {
    # en
    "diagnose", "troubleshoot", "traceback", "crash", "error log",
    "what went wrong", "root cause", "why is it failing",
    "error in logs", "why is there an error",
    # ru
    "диагностируй", "диагностика", "почему падает", "ошибка",
    "разберись", "разобраться", "краш", "логи ошибок",
    "что не так", "в чем причина", "в чём причина",
}


@dataclass(frozen=True)
class Classification:
    """Deterministic classification output."""

    intent: IntentType
    risk: IntentRisk
    expected_side_effect: ExpectedSideEffect
    confidence: float
    reason_codes: List[str]
    lexical_hits: List[str]

    def to_dict(self) -> Dict[str, str]:
        return {
            "intent": self.intent.value,
            "risk": self.risk.value,
            "expected_side_effect": self.expected_side_effect.value,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "lexical_hits": list(self.lexical_hits),
        }


class IntentClassifier:
    """Protocol seam. Sprint 1.1: rule-based implementation only.

    A future LLMIntentClassifier may implement the same protocol; the
    router never cares which implementation produced the classification.
    """

    VERSION = "rule-v1"

    def classify(self, features: RequestIntentFeatures) -> Classification:
        raise NotImplementedError


class RuleBasedIntentClassifier(IntentClassifier):
    """Deterministic keyword + declared-type classifier (RU/EN)."""

    def __init__(self) -> None:
        self._families = _FAMILIES
        self._request_type_map = _REQUEST_TYPE_MAP
        self._command_map = _COMMAND_MAP
        self._ambiguous = _AMBIGUOUS
        self._diagnostic = _DIAGNOSTIC_TERMS

    def classify(self, features: RequestIntentFeatures) -> Classification:
        try:
            return self._classify(features)
        except Exception as exc:  # pragma: no cover - defensive
            raise ClassificationError(str(exc)) from exc

    # ── internals ────────────────────────────────────────────────────

    def _classify(self, features: RequestIntentFeatures) -> Classification:
        # lexical_hits carries FAMILY NAMES (safe identifiers), never raw
        # words. Count per family name.
        hits: Dict[str, int] = {}
        for name in features.lexical_hits:
            hits[name] = hits.get(name, 0) + 1
        diag_hits = hits.get("diagnostic", 0)

        # 1) explicit request_type / command dominate (declared intent).
        declared = self._declared(features)

        # 2) ambiguity guard: extraction tagged "ambiguous" (only
        #    ambiguous verbs, no object/context) and no declared type.
        if not declared and hits.get("ambiguous"):
            return self._unknown("ambiguous request — no object/context")

        # 3) unsafe dominance: delete > system > write > schedule wins
        #    even when read families also matched (adversarial).
        #    Compounds override: "deploy status" → status (system word is
        #    the OBJECT of the status read); "write code" → code assist.
        if hits.get("code_compound") and not (
                hits.get("delete") or hits.get("system")):
            return Classification(
                intent=IntentType.CODE_ASSIST, risk=IntentRisk.LOW,
                expected_side_effect=ExpectedSideEffect.NONE,
                confidence=0.9, reason_codes=["code_assist"],
                lexical_hits=["code"] + list(hits.keys()),
            )
        for name, words, intent, risk, side, _dom in self._families:
            if name in ("delete", "system", "write", "schedule") \
                    and hits.get(name):
                # status compound makes system/schedule words a status
                # OBJECT ("show deploy status") — not an action intent.
                if hits.get("status_compound") and name in (
                        "system", "schedule", "write"):
                    continue
                return Classification(
                    intent=intent, risk=risk, expected_side_effect=side,
                    confidence=0.9, reason_codes=[self._reason_code(intent)],
                    lexical_hits=[name] + list(hits.keys()),
                )

        if declared:
            intent, risk, side, code = declared
            return Classification(
                intent=intent, risk=risk, expected_side_effect=side,
                confidence=0.7, reason_codes=[code],
                lexical_hits=list(hits.keys()),
            )

        # 4) read/analysis families.
        if hits:
            # pick highest dominance among non-unsafe families
            best: Optional[Tuple[int, str, IntentType, IntentRisk,
                                 ExpectedSideEffect]] = None
            for name, words, intent, risk, side, dom in self._families:
                if hits.get(name) and not (
                        hits.get("status_compound")
                        and name in ("system", "schedule", "write")
                ) and (best is None or dom > best[0]):
                    best = (dom, name, intent, risk, side)
            if best is not None:
                _, name, intent, risk, side = best
                if name == "diagnostic" or diag_hits:
                    return Classification(
                        intent=IntentType.DIAGNOSTIC, risk=IntentRisk.MEDIUM,
                        expected_side_effect=ExpectedSideEffect.READ_ONLY,
                        confidence=0.7, reason_codes=["diagnostic"],
                        lexical_hits=["diagnostic"],
                    )
                return Classification(
                    intent=intent, risk=risk, expected_side_effect=side,
                    confidence=0.9, reason_codes=[self._reason_code(intent)],
                    lexical_hits=[name] + list(hits.keys()),
                )

        if diag_hits:
            return Classification(
                intent=IntentType.DIAGNOSTIC, risk=IntentRisk.MEDIUM,
                expected_side_effect=ExpectedSideEffect.READ_ONLY,
                confidence=0.7, reason_codes=["diagnostic"],
                lexical_hits=["diagnostic"],
            )

        return self._unknown("no lexical signal")

    def _declared(
        self, features: RequestIntentFeatures
    ) -> Optional[Tuple[IntentType, IntentRisk, ExpectedSideEffect, str]]:
        rt = (features.request_type or "").strip().lower()
        if rt in self._request_type_map:
            intent = self._request_type_map[rt]
            return (intent, *_risk_side(intent), "declared_request_type")
        cmd = (features.command or "").strip().lower()
        if cmd in self._command_map:
            intent = self._command_map[cmd]
            return (intent, *_risk_side(intent), "declared_command")
        return None

    @staticmethod
    def _reason_code(intent: IntentType) -> str:
        from .models import ReasonCode

        mapping = {
            IntentType.WRITE_ACTION: ReasonCode.WRITE_INTENT,
            IntentType.DELETE_ACTION: ReasonCode.WRITE_INTENT,
            IntentType.SYSTEM_ACTION: ReasonCode.WRITE_INTENT,
            IntentType.SCHEDULE_ACTION: ReasonCode.WRITE_INTENT,
            IntentType.UNKNOWN: ReasonCode.UNKNOWN_INTENT,
        }
        return mapping.get(intent, ReasonCode.READ_ONLY_INTENT).value

    @staticmethod
    def _unknown(reason: str) -> Classification:
        from .models import ReasonCode

        return Classification(
            intent=IntentType.UNKNOWN, risk=IntentRisk.UNKNOWN,
            expected_side_effect=ExpectedSideEffect.UNKNOWN,
            confidence=0.4, reason_codes=[ReasonCode.UNKNOWN_INTENT.value],
            lexical_hits=[],
        )


def _risk_side(intent: IntentType):
    mapping = {
        IntentType.CONVERSATION: (IntentRisk.LOW,
                                  ExpectedSideEffect.NONE),
        IntentType.SUMMARIZATION: (IntentRisk.LOW,
                                   ExpectedSideEffect.NONE),
        IntentType.INFORMATION_READ: (IntentRisk.LOW,
                                      ExpectedSideEffect.READ_ONLY),
        IntentType.STATUS_READ: (IntentRisk.LOW,
                                 ExpectedSideEffect.READ_ONLY),
        IntentType.SEARCH_READ: (IntentRisk.LOW,
                                 ExpectedSideEffect.READ_ONLY),
        IntentType.ANALYSIS: (IntentRisk.LOW,
                              ExpectedSideEffect.READ_ONLY),
        IntentType.PLANNING: (IntentRisk.LOW, ExpectedSideEffect.NONE),
        IntentType.CODE_ASSIST: (IntentRisk.LOW,
                                 ExpectedSideEffect.NONE),
        IntentType.DIAGNOSTIC: (IntentRisk.MEDIUM,
                                ExpectedSideEffect.READ_ONLY),
        IntentType.APPROVAL_ACTION: (IntentRisk.MEDIUM,
                                     ExpectedSideEffect.REVERSIBLE_WRITE),
        IntentType.WRITE_ACTION: (IntentRisk.MEDIUM,
                                  ExpectedSideEffect.REVERSIBLE_WRITE),
        IntentType.DELETE_ACTION: (IntentRisk.CRITICAL,
                                   ExpectedSideEffect.IRREVERSIBLE_WRITE),
        IntentType.SYSTEM_ACTION: (IntentRisk.HIGH,
                                   ExpectedSideEffect.SYSTEM_CHANGE),
        IntentType.SCHEDULE_ACTION: (IntentRisk.LOW,
                                     ExpectedSideEffect.REVERSIBLE_WRITE),
        IntentType.UNKNOWN: (IntentRisk.UNKNOWN,
                             ExpectedSideEffect.UNKNOWN),
    }
    return mapping[intent]


__all__ = [
    "Classification",
    "IntentClassifier",
    "RuleBasedIntentClassifier",
    "_FAMILIES",
    "_REQUEST_TYPE_MAP",
    "_COMMAND_MAP",
]
