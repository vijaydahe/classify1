"""Rule-based information asset classification engine.

Rules are tenant-scoped and either keyword (case-insensitive substring,
comma-separated alternatives) or regex. The matching rule whose label has the
highest sensitivity level wins; ties are broken by rule priority (lower first).
"""
import re

from sqlalchemy.orm import Session

from .models import ClassificationLabel, ClassificationRule

# Default label set created for every new tenant.
DEFAULT_LABELS = [
    {"name": "Public", "level": 0, "color": "#22c55e",
     "description": "Information approved for public release"},
    {"name": "Internal", "level": 1, "color": "#3b82f6",
     "description": "Internal business information"},
    {"name": "Confidential", "level": 2, "color": "#f59e0b",
     "description": "Sensitive business or personal information"},
    {"name": "Restricted", "level": 3, "color": "#ef4444",
     "description": "Highly sensitive — regulated or secret data"},
]

# Default rules created for every new tenant: (name, type, pattern, label, priority)
DEFAULT_RULES = [
    ("US SSN", "regex", r"\b\d{3}-\d{2}-\d{4}\b", "Restricted", 10),
    ("Credit card number", "regex", r"\b(?:\d[ -]*?){13,16}\b", "Restricted", 10),
    ("Private key material", "keyword", "BEGIN PRIVATE KEY,BEGIN RSA PRIVATE KEY,BEGIN OPENSSH PRIVATE KEY", "Restricted", 10),
    ("API keys / secrets", "regex", r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token)\b\s*[:=]", "Restricted", 15),
    ("Password disclosure", "regex", r"(?i)\bpassword\s*[:=]\s*\S+", "Restricted", 15),
    ("Health / medical data", "keyword", "medical record,diagnosis,patient,phi,health insurance", "Restricted", 20),
    ("Personal data (PII)", "keyword", "date of birth,passport number,driver's license,national id,aadhaar,pan card", "Confidential", 30),
    ("Email addresses", "regex", r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "Confidential", 40),
    ("Phone numbers", "regex", r"\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]?\d{4}\b", "Confidential", 45),
    ("Financial data", "keyword", "salary,payroll,bank account,iban,swift,invoice,revenue forecast", "Confidential", 35),
    ("Marked confidential", "keyword", "confidential,nda,do not distribute,trade secret", "Confidential", 25),
    ("Internal documents", "keyword", "internal use only,meeting notes,project plan,roadmap,draft,policy", "Internal", 60),
    ("Source code files", "regex", r"\.(py|js|ts|java|go|rb|cs|cpp)$", "Internal", 65),
    ("Public marketing", "keyword", "press release,public,brochure,marketing,announcement", "Public", 80),
]


def seed_tenant_defaults(db: Session, tenant_id: int) -> None:
    labels = {}
    for spec in DEFAULT_LABELS:
        label = ClassificationLabel(tenant_id=tenant_id, **spec)
        db.add(label)
        db.flush()
        labels[label.name] = label
    for name, rule_type, pattern, label_name, priority in DEFAULT_RULES:
        db.add(ClassificationRule(
            tenant_id=tenant_id, name=name, rule_type=rule_type, pattern=pattern,
            label_id=labels[label_name].id, priority=priority,
        ))


def classify_text(db: Session, tenant_id: int, name: str, content: str) -> tuple[ClassificationLabel | None, list[str]]:
    """Returns (winning_label, matched_rule_names). Falls back to the lowest-level label."""
    text = f"{name}\n{content}"
    rules = (
        db.query(ClassificationRule)
        .filter(ClassificationRule.tenant_id == tenant_id, ClassificationRule.enabled.is_(True))
        .order_by(ClassificationRule.priority)
        .all()
    )
    matched: list[ClassificationRule] = []
    for rule in rules:
        if rule.rule_type == "regex":
            try:
                if re.search(rule.pattern, text):
                    matched.append(rule)
            except re.error:
                continue
        else:
            lowered = text.lower()
            if any(kw.strip().lower() in lowered for kw in rule.pattern.split(",") if kw.strip()):
                matched.append(rule)

    if matched:
        winner = max(matched, key=lambda r: (r.label.level, -r.priority))
        return winner.label, [r.name for r in matched]

    fallback = (
        db.query(ClassificationLabel)
        .filter(ClassificationLabel.tenant_id == tenant_id)
        .order_by(ClassificationLabel.level)
        .first()
    )
    return fallback, []


def load_matcher(db: Session, tenant_id: int):
    """Loads a tenant's rules + fallback label once, for classifying many items in memory."""
    rules = (
        db.query(ClassificationRule)
        .filter(ClassificationRule.tenant_id == tenant_id, ClassificationRule.enabled.is_(True))
        .order_by(ClassificationRule.priority)
        .all()
    )
    compiled = []
    for r in rules:
        compiled.append({
            "name": r.name, "type": r.rule_type, "pattern": r.pattern,
            "priority": r.priority, "label_id": r.label.id, "level": r.label.level,
        })
    fallback = (
        db.query(ClassificationLabel)
        .filter(ClassificationLabel.tenant_id == tenant_id)
        .order_by(ClassificationLabel.level)
        .first()
    )
    return compiled, (fallback.id if fallback else None)


def match_rules(compiled: list[dict], fallback_label_id, name: str, content: str):
    """In-memory classification — no DB. Returns (label_id, matched_rule_names)."""
    text = f"{name}\n{content}"
    lowered = text.lower()
    matched = []
    for rule in compiled:
        if rule["type"] == "regex":
            try:
                if re.search(rule["pattern"], text):
                    matched.append(rule)
            except re.error:
                continue
        elif any(kw.strip().lower() in lowered for kw in rule["pattern"].split(",") if kw.strip()):
            matched.append(rule)
    if matched:
        winner = max(matched, key=lambda r: (r["level"], -r["priority"]))
        return winner["label_id"], [r["name"] for r in matched]
    return fallback_label_id, []


def export_rules(db: Session, tenant_id: int) -> list[dict]:
    """Serializes rules + labels for endpoint agents to classify locally."""
    rules = (
        db.query(ClassificationRule)
        .filter(ClassificationRule.tenant_id == tenant_id, ClassificationRule.enabled.is_(True))
        .order_by(ClassificationRule.priority)
        .all()
    )
    return [
        {
            "name": r.name,
            "type": r.rule_type,
            "pattern": r.pattern,
            "label": r.label.name,
            "level": r.label.level,
            "priority": r.priority,
        }
        for r in rules
    ]
