"""The people let in, what an admin changed in each role, and the record of changes: the SQL (stage 3 of the rebuild).

The tables are in db/003_users_and_roles.sql. Nothing here decides anything: rules/access.py does, and calls these inside
one transaction of the database store (store.get().tx), so a check and the change it allows happen together. On the
files store there is no database to hold people; rules/access.py refuses before reaching this file.
"""
import json

PERSON = ["email", "name", "role", "active", "added_at", "added_by", "changed_at", "changed_by"]


def _person(row):
    p = dict(zip(PERSON, row))
    p["active"] = bool(p["active"])
    return p


def find(c, emails):
    """The people with any of these addresses (lower case), as they are in the list."""
    emails = sorted({e for e in emails if e})
    if not emails:
        return []
    marks = ", ".join(["%s"] * len(emails))
    return [_person(r) for r in c.all(f"SELECT {', '.join(PERSON)} FROM app_user WHERE email IN ({marks})", emails)]


def people(c):
    return [_person(r) for r in c.all(f"SELECT {', '.join(PERSON)} FROM app_user ORDER BY email")]


def overrides(c):
    """What admins changed from the defaults: {(role, permission): True or False}."""
    return {(r[0], r[1]): bool(r[2]) for r in c.all("SELECT role, permission, allowed FROM role_permission")}


def override_rows(c):
    return [{"role": r[0], "permission": r[1], "allowed": bool(r[2]), "changed_at": r[3], "changed_by": r[4]}
            for r in c.all("SELECT role, permission, allowed, changed_at, changed_by FROM role_permission ORDER BY role, permission")]


def active_admins(c):
    return [r[0] for r in c.all("SELECT email FROM app_user WHERE role = 'Admin' AND active = 1 ORDER BY email")]


def add(c, email, name, role, at, who):
    c.run("INSERT INTO app_user (email, name, role, active, added_at, added_by) VALUES (%s, %s, %s, 1, %s, %s)",
          (email, name, role, at, who))


def update(c, email, at, who, **fields):
    """Change a person's name, role or active (only those given)."""
    cols = [k for k in ("name", "role", "active") if k in fields]
    vals = [int(fields[k]) if k == "active" else fields[k] for k in cols]
    c.run(f"UPDATE app_user SET {', '.join(k + ' = %s' for k in cols + ['changed_at', 'changed_by'])} WHERE email = %s",
          vals + [at, who, email])


def set_override(c, role, permission, allowed, at, who):
    """Record a role's permission as given or taken away; None puts it back to the default (no row)."""
    c.run("DELETE FROM role_permission WHERE role = %s AND permission = %s", (role, permission))
    if allowed is not None:
        c.run("INSERT INTO role_permission (role, permission, allowed, changed_at, changed_by) VALUES (%s, %s, %s, %s, %s)",
              (role, permission, int(bool(allowed)), at, who))


def log(c, at, who, action, subject, detail):
    c.run("INSERT INTO audit_log (at, who, action, subject, detail) VALUES (%s, %s, %s, %s, %s)",
          (at, who, action, subject, json.dumps(detail, default=str)))


def audit(c, limit=300):
    rows = c.all("SELECT id, at, who, action, subject, detail FROM audit_log ORDER BY id DESC LIMIT %s", (int(limit),))
    return [{"id": r[0], "at": r[1], "who": r[2], "action": r[3], "subject": r[4], "detail": json.loads(r[5] or "{}")} for r in rows]
