-- RightPrice database, stage 3 of the rebuild (27 Nov 2026): who may use RightPrice, what each role may do, and a record
-- of every change made to either.
--
-- Applied once, at start, by store.py (see 001_files_moved_in.sql for the @...@ words). Read and written by data_users.py;
-- the rules (the four roles, their default permissions, which address needs which permission) are in rules/access.py.
-- Nothing here is used until the app setting RIGHTPRICE_ADMINS is added: until then everyone signed in may use everything.
-- Times are kept as text in ISO form (2026-11-27T15:02:11), as in the other tables.

-- the version counter for the people and roles (store.KINDS 'users'): writers of it wait for each other
INSERT INTO store_state (kind, version) VALUES ('users', 0);

-- the people let in. Nobody is let in until an admin adds them here; the admins named in RIGHTPRICE_ADMINS are let in
-- as Admin whether or not they are here. A person is never deleted, only switched off, so the record of changes keeps
-- meaning something.
CREATE TABLE app_user (
    email       TEXT PRIMARY KEY,                 -- the address Microsoft sign-in gives, lower case
    name        TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL,                    -- Admin | Rates editor | Buyer | Viewer
    active      INTEGER NOT NULL DEFAULT 1,       -- 0: switched off by an admin
    added_at    TEXT NOT NULL,
    added_by    TEXT NOT NULL DEFAULT '',
    changed_at  TEXT,
    changed_by  TEXT
);

-- what an admin changed from a role's defaults. A permission with no row here is as the defaults in rules/access.py say,
-- so a page added by a later stage reaches each role as its default says, without a row for it.
CREATE TABLE role_permission (
    role        TEXT NOT NULL,                    -- Rates editor | Buyer | Viewer (Admin always has everything)
    permission  TEXT NOT NULL,                    -- 'page:rightcost', 'do:edit_rates' ...
    allowed     INTEGER NOT NULL,                 -- 1 given, 0 taken away
    changed_at  TEXT NOT NULL,
    changed_by  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (role, permission)
);

-- every change to the people or the roles: who did it, when, and what it was before and after. Only added to.
CREATE TABLE audit_log (
    id       @ID@,
    at       TEXT NOT NULL,
    who      TEXT NOT NULL DEFAULT '',            -- the admin's sign-in address
    action   TEXT NOT NULL,                       -- 'person added', 'role changed', 'name changed', 'switched off', 'switched on',
                                                  -- 'permission given', 'permission taken away'
    subject  TEXT NOT NULL DEFAULT '',            -- the person's address, or the role
    detail   TEXT NOT NULL DEFAULT '{}'           -- JSON: what it was and what it became
);
CREATE INDEX audit_log_at ON audit_log (at);
