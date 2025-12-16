import os
import sys
import psycopg2

DB_URL = os.getenv('DATABASE_URL')


def get_column_type(cur, table, column):
    cur.execute("""
    SELECT data_type FROM information_schema.columns
    WHERE table_name = %s AND column_name = %s
    """, (table, column))
    row = cur.fetchone()
    return row[0] if row else None


def ensure_bigint(cur, table, column):
    dtype = get_column_type(cur, table, column)
    if dtype != 'bigint':
        print(f"Changing {table}.{column} from {dtype} -> bigint")
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE bigint USING {column}::bigint;")
        return True
    else:
        print(f"{table}.{column} already bigint")
        return False


def main():
    if not DB_URL:
        print("DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # ensure table exists
            cur.execute("SELECT to_regclass('public.event')")
            if not cur.fetchone()[0]:
                print('Table public.event not found — nothing to do')
                return

            changed = False
            for col in ('chat_id', 'topic_thread_id', 'sent_message_id'):
                try:
                    if ensure_bigint(cur, 'event', col):
                        changed = True
                except Exception as e:
                    print(f'Error checking/changing {col}:', e)
            if not changed:
                print('No changes required — all target columns are bigint')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
