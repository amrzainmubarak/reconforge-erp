"""SQLite repositories for local users and RBAC."""

from __future__ import annotations

import sqlite3

from reconforge.auth.models import LocalPermission, LocalRole, LocalUser
from reconforge.auth.passwords import PasswordHash
from reconforge.db.connection import DatabaseError
from reconforge.domain.models import new_domain_id, utc_now_text


class AuthRepositoryError(ValueError):
    """Raised for safe, user-facing auth repository errors."""


def ensure_auth_schema(connection: sqlite3.Connection) -> None:
    """Ensure the local database has the auth/RBAC migration applied."""

    try:
        user_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        role_permissions = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'role_permissions'",
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise DatabaseError("Unable to read ReconForge database. Run 'reconforge db init' first.") from exc
    if "password_hash" not in user_columns or role_permissions is None:
        raise DatabaseError("ReconForge auth schema is not initialized. Run 'reconforge db migrate' first.")


class UserRepository:
    """Local user repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_auth_schema(connection)
        self.connection = connection

    def create(
        self,
        *,
        username: str,
        password_hash: PasswordHash,
        display_name: str | None = None,
        email: str | None = None,
    ) -> LocalUser:
        user = LocalUser(
            id=new_domain_id("USR"),
            username=username,
            display_name=display_name or username,
            email=email,
            password_changed_at=utc_now_text(),
        )
        try:
            self.connection.execute(
                """
                INSERT INTO users (
                    id, username, display_name, email, disabled, created_at,
                    password_hash, password_salt, password_iterations, password_algorithm, password_changed_at,
                    failed_login_count, locked_until
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.display_name,
                    user.email,
                    int(user.disabled),
                    user.created_at,
                    password_hash.hash_hex,
                    password_hash.salt_hex,
                    password_hash.iterations,
                    password_hash.algorithm,
                    user.password_changed_at,
                    user.failed_login_count,
                    user.locked_until,
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise AuthRepositoryError("User already exists.") from exc
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to create local user.") from exc
        return user

    def get_by_username(self, username: str) -> LocalUser | None:
        try:
            row = self.connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to read local user.") from exc
        return self._row_to_user(row) if row is not None else None

    def get_password_hash(self, username: str) -> PasswordHash | None:
        try:
            row = self.connection.execute(
                """
                SELECT password_hash, password_salt, password_iterations, password_algorithm
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to read local user credentials.") from exc
        if row is None or row["password_hash"] is None or row["password_salt"] is None:
            return None
        return PasswordHash(
            algorithm=str(row["password_algorithm"]),
            iterations=int(row["password_iterations"]),
            salt_hex=str(row["password_salt"]),
            hash_hex=str(row["password_hash"]),
        )

    def list(self) -> list[LocalUser]:
        try:
            rows = self.connection.execute("SELECT * FROM users ORDER BY username").fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local users.") from exc
        return [self._row_to_user(row) for row in rows]

    def disable(self, username: str) -> LocalUser:
        user = self.get_by_username(username)
        if user is None:
            raise AuthRepositoryError("User not found.")
        try:
            self.connection.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to disable local user.") from exc
        disabled = self.get_by_username(username)
        if disabled is None:
            raise AuthRepositoryError("User not found.")
        return disabled

    def update_profile(
        self,
        username: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        disabled: bool | None = None,
    ) -> LocalUser:
        user = self.get_by_username(username)
        if user is None:
            raise AuthRepositoryError("User not found.")
        next_display_name = display_name if display_name is not None else user.display_name
        next_email = email if email is not None else user.email
        next_disabled = disabled if disabled is not None else user.disabled
        try:
            self.connection.execute(
                """
                UPDATE users
                SET display_name = ?, email = ?, disabled = ?
                WHERE username = ?
                """,
                (next_display_name, next_email, int(next_disabled), username),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to update local user.") from exc
        updated = self.get_by_username(username)
        if updated is None:
            raise AuthRepositoryError("User not found.")
        return updated

    def change_password(self, username: str, password_hash: PasswordHash) -> LocalUser:
        user = self.get_by_username(username)
        if user is None:
            raise AuthRepositoryError("User not found.")
        changed_at = utc_now_text()
        try:
            self.connection.execute(
                """
                UPDATE users
                SET password_hash = ?, password_salt = ?, password_iterations = ?,
                    password_algorithm = ?, password_changed_at = ?
                WHERE username = ?
                """,
                (
                    password_hash.hash_hex,
                    password_hash.salt_hex,
                    password_hash.iterations,
                    password_hash.algorithm,
                    changed_at,
                    username,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to change local user password.") from exc
        changed = self.get_by_username(username)
        if changed is None:
            raise AuthRepositoryError("User not found.")
        return changed

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> LocalUser:
        return LocalUser(
            id=str(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            email=str(row["email"]) if row["email"] is not None else None,
            disabled=bool(row["disabled"]),
            created_at=str(row["created_at"]),
            password_changed_at=str(row["password_changed_at"]) if row["password_changed_at"] is not None else None,
            failed_login_count=int(row["failed_login_count"]),
            locked_until=str(row["locked_until"]) if row["locked_until"] is not None else None,
        )


class RoleRepository:
    """Local role and permission repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_auth_schema(connection)
        self.connection = connection

    def get_role(self, role_name: str) -> LocalRole | None:
        try:
            row = self.connection.execute("SELECT * FROM roles WHERE name = ?", (role_name,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to read local role.") from exc
        return LocalRole(id=str(row["id"]), name=str(row["name"])) if row is not None else None

    def list_roles(self) -> list[LocalRole]:
        try:
            rows = self.connection.execute("SELECT * FROM roles ORDER BY name").fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local roles.") from exc
        return [LocalRole(id=str(row["id"]), name=str(row["name"])) for row in rows]

    def list_permissions(self) -> list[LocalPermission]:
        try:
            rows = self.connection.execute("SELECT * FROM permissions ORDER BY name").fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local permissions.") from exc
        return [LocalPermission(name=str(row["name"]), description=str(row["description"])) for row in rows]

    def assign_role(self, *, username: str, role_name: str) -> None:
        user_id = self._user_id(username)
        role_id = self._role_id(role_name)
        try:
            self.connection.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_id),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to assign local role.") from exc

    def set_single_role(self, *, username: str, role_name: str) -> None:
        user_id = self._user_id(username)
        role_id = self._role_id(role_name)
        try:
            self.connection.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
            self.connection.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to update local user role.") from exc

    def remove_role(self, *, username: str, role_name: str) -> None:
        user_id = self._user_id(username)
        role_id = self._role_id(role_name)
        try:
            self.connection.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to remove local role.") from exc

    def user_roles(self, username: str) -> list[str]:
        user_id = self._user_id(username)
        try:
            rows = self.connection.execute(
                """
                SELECT roles.name
                FROM user_roles
                JOIN roles ON roles.id = user_roles.role_id
                WHERE user_roles.user_id = ?
                ORDER BY roles.name
                """,
                (user_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local user roles.") from exc
        return [str(row["name"]) for row in rows]

    def role_permissions(self, role_name: str) -> list[str]:
        role_id = self._role_id(role_name)
        try:
            rows = self.connection.execute(
                """
                SELECT permissions.name
                FROM role_permissions
                JOIN permissions ON permissions.name = role_permissions.permission_name
                WHERE role_permissions.role_id = ?
                ORDER BY permissions.name
                """,
                (role_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local role permissions.") from exc
        return [str(row["name"]) for row in rows]

    def user_permissions(self, username: str) -> set[str]:
        user_id = self._user_id(username)
        try:
            rows = self.connection.execute(
                """
                SELECT DISTINCT permissions.name
                FROM user_roles
                JOIN role_permissions ON role_permissions.role_id = user_roles.role_id
                JOIN permissions ON permissions.name = role_permissions.permission_name
                WHERE user_roles.user_id = ?
                """,
                (user_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise AuthRepositoryError("Unable to list local user permissions.") from exc
        return {str(row["name"]) for row in rows}

    def _user_id(self, username: str) -> str:
        row = self.connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise AuthRepositoryError("User not found.")
        return str(row["id"])

    def _role_id(self, role_name: str) -> str:
        row = self.connection.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
        if row is None:
            raise AuthRepositoryError("Role not found.")
        return str(row["id"])
