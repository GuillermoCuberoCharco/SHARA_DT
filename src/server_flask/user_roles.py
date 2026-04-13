"""
Utilities for normalized user roles.
"""

STUDENT_USER_ROLE = "student"
TEACHER_USER_ROLE = "teacher"
VALID_USER_ROLES = {
    STUDENT_USER_ROLE,
    TEACHER_USER_ROLE,
}


def normalize_user_role(role: str | None) -> str:
    if role in VALID_USER_ROLES:
        return role
    return STUDENT_USER_ROLE


def is_teacher_role(role: str | None) -> bool:
    return normalize_user_role(role) == TEACHER_USER_ROLE
