#!/usr/bin/env bash
# 로컬 PostgreSQL 초기화 및 기동.
#
# 우선순위: 이미 설치된 conda/시스템 PostgreSQL → Docker(postgres:16) → 설치 안내.
# 새로 받은 사람은 Docker만 있으면 된다. SOLPLY_PG=docker 로 Docker를 강제할 수 있다.
# (이 저장소를 만든 맥은 Homebrew가 안 되는 macOS 13 Intel이라 conda 경로가 먼저 있다:
#   conda create -p ~/.local/pg-env -c conda-forge postgresql)
#
# 사용법: bash scripts/setup-postgres.sh
set -euo pipefail

PG_HOME="${PG_HOME:-$HOME/.local/pg-env}"
PGDATA="${PGDATA:-$HOME/.local/pgdata}"
PGPORT="${PGPORT:-5432}"
DB_NAME="${DB_NAME:-solply}"

docker_pg() {
  if ! docker info >/dev/null 2>&1; then
    echo "✗ Docker 데몬이 꺼져 있습니다. Docker Desktop을 켜고 다시 실행하세요."
    exit 1
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx solply-pg; then
    docker start solply-pg >/dev/null
  else
    echo "▶ postgres:16 컨테이너 생성 (solply-pg, :$PGPORT)"
    docker run -d --name solply-pg -p "$PGPORT:5432" \
      -e POSTGRES_USER="$USER" -e POSTGRES_DB="$DB_NAME" \
      -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16 >/dev/null
  fi
  for _ in $(seq 1 30); do
    docker exec solply-pg pg_isready -U "$USER" >/dev/null 2>&1 && break
    sleep 1
  done
  docker exec solply-pg pg_isready -U "$USER" >/dev/null
  echo "✓ Docker PostgreSQL 준비 (:$PGPORT)"
  cat <<EOF

✅ 준비 완료. backend/.env 에 아래를 넣으면 Postgres로 동작합니다:

  SOLPLY_STORE=postgres
  DATABASE_URL=postgresql://$USER@localhost:$PGPORT/$DB_NAME

  중지: docker stop solply-pg
EOF
  exit 0
}

if [ "${SOLPLY_PG:-auto}" = "docker" ]; then
  docker_pg
elif [ -d "$PG_HOME/bin" ]; then
  export PATH="$PG_HOME/bin:$PATH"
elif command -v pg_isready >/dev/null 2>&1; then
  # Homebrew 등 시스템 PostgreSQL 사용 (예: M칩 맥). 서버 관리는 brew services에 맡긴다
  echo "✓ 시스템 PostgreSQL 사용: $(command -v pg_isready)"
elif command -v docker >/dev/null 2>&1; then
  # 새로 받은 환경 — PostgreSQL이 없으면 Docker로 띄운다
  docker_pg
else
  echo "✗ PostgreSQL이 없습니다. Docker를 켜거나 다음 중 하나로 설치하세요:"
  echo "  brew install postgresql@17  (또는 conda create -y -p $PG_HOME -c conda-forge postgresql)"
  exit 1
fi

if ! pg_isready -p "$PGPORT" >/dev/null 2>&1 && [ ! -f "$PGDATA/PG_VERSION" ]; then
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
