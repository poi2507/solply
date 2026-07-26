#!/usr/bin/env bash
# 로컬 PostgreSQL 초기화 및 기동 (conda-forge 배포판 사용).
#
# macOS 13 Intel에서는 Homebrew가 동작하지 않아 conda로 설치했다:
#   conda create -p ~/.local/pg-env -c conda-forge postgresql
#
# 사용법: bash scripts/setup-postgres.sh
set -euo pipefail

PG_HOME="${PG_HOME:-$HOME/.local/pg-env}"
PGDATA="${PGDATA:-$HOME/.local/pgdata}"
PGPORT="${PGPORT:-5432}"
DB_NAME="${DB_NAME:-solply}"
export PATH="$PG_HOME/bin:$PATH"

if [ ! -d "$PG_HOME/bin" ]; then
  echo "✗ PostgreSQL이 없습니다. 먼저 설치하세요:"
  echo "  conda create -y -p $PG_HOME -c conda-forge postgresql"
  exit 1
fi

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "▶ 데이터 디렉터리 초기화: $PGDATA"
  initdb -D "$PGDATA" -U "$USER" --encoding=UTF8 --locale=C >/dev/null
  # conda 배포판에는 zoneinfo가 없어 시스템 타임존(KST-9)을 못 읽는다
  printf "\ntimezone = 'UTC'\nlog_timezone = 'UTC'\n" >> "$PGDATA/postgresql.conf"
fi

if pg_isready -p "$PGPORT" >/dev/null 2>&1; then
  echo "✓ 서버 이미 실행 중 (:$PGPORT)"
else
  echo "▶ 서버 기동 (:$PGPORT)"
  pg_ctl -D "$PGDATA" -o "-p $PGPORT" -l "$PGDATA/server.log" start >/dev/null
  for _ in $(seq 1 20); do
    pg_isready -p "$PGPORT" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

if psql -p "$PGPORT" -lqt | cut -d'|' -f1 | grep -qw "$DB_NAME"; then
  echo "✓ 데이터베이스 '$DB_NAME' 존재"
else
  createdb -p "$PGPORT" "$DB_NAME"
  echo "✓ 데이터베이스 '$DB_NAME' 생성"
fi

cat <<EOF

✅ 준비 완료. backend/.env 에 아래를 넣으면 Postgres로 동작합니다:

  SOLPLY_STORE=postgres
  DATABASE_URL=postgresql://$USER@localhost:$PGPORT/$DB_NAME

  중지: PATH=$PG_HOME/bin:\$PATH pg_ctl -D $PGDATA stop
EOF
