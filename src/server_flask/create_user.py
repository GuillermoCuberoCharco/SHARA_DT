#!/usr/bin/env python3
"""
create_user.py

CLI utility to add or update users in files/users.json.

Usage:
    python create_user.py <username> <password>

Example:
    python create_user.py admin shara2024
    python create_user.py alice mipassword
"""

import json
import os
import sys

import bcrypt

USERS_FILE = os.path.join(os.path.dirname(__file__), 'files', 'users.json')


def main():
    if len(sys.argv) != 3:
        print(f'Uso: python {sys.argv[0]} <usuario> <contraseña>')
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    password = sys.argv[2]

    if not username or not password:
        print('Error: usuario y contraseña no pueden estar vacíos')
        sys.exit(1)

    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        users = {}

    is_update = username in users
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    users[username] = {'password_hash': password_hash}

    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    action = 'Actualizado' if is_update else 'Creado'
    print(f'{action} usuario: {username}')


if __name__ == '__main__':
    main()
