"""Read per-query statistics from pg_stat_statements and compare snapshots over time.

pg_stat_statements counters only ever grow (since the last reset), so a single
reading tells you "average since forever". To know how a query behaves *now*,
we take two snapshots and look at the difference between them.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from dbagent.core.db import Database

SNAPSHOT_SQL = """
SELECT min(queryid)                AS queryid,
       query,
       sum(calls)::bigint            AS calls,
       sum(total_exec_time)          AS total_exec_time,
       sum(rows)::bigint             AS rows,
       sum(shared_blks_hit)::bigint  AS shared_blks_hit,
       sum(shared_blks_read)::bigint AS shared_blks_read
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND query NOT LIKE '%pg_stat_statements%'
  AND query NOT IN ('BEGIN', 'COMMIT', 'ROLLBACK')
GROUP BY query
"""


@dataclass(frozen=True)
class QueryStat:
    """Cumulative counters for one query pattern at one moment."""

    queryid: int
    query: str
    calls: int
    total_exec_time_ms: float
    rows: int
    shared_blks_hit: int
    shared_blks_read: int


@dataclass(frozen=True)
class Snapshot:
    """All query counters captured at one point in time."""

    taken_at: datetime
    stats: dict[int, QueryStat]


@dataclass(frozen=True)
class QueryWindow:
    """How one query pattern behaved between two snapshots."""

    queryid: int
    query: str
    calls: int
    total_time_ms: float
    mean_time_ms: float
    blocks_read_from_disk: int


def take_snapshot(db: Database) -> Snapshot:
    """Capture the current pg_stat_statements counters."""
    rows = db.fetch_all(SNAPSHOT_SQL)
    stats = {
        row["queryid"]: QueryStat(
            queryid=row["queryid"],
            query=row["query"],
            calls=row["calls"],
            total_exec_time_ms=row["total_exec_time"],
            rows=row["rows"],
            shared_blks_hit=row["shared_blks_hit"],
            shared_blks_read=row["shared_blks_read"],
        )
        for row in rows
    }
    return Snapshot(taken_at=datetime.now(timezone.utc), stats=stats)


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[QueryWindow]:
    """Activity per query between two snapshots, busiest (most total time) first.

    Queries with no new calls in the window are left out.
    """
    windows = []
    for queryid, now in after.stats.items():
        prev = before.stats.get(queryid)

        # New query, or statistics were reset: everything counted so far is new.
        if prev is None or now.calls < prev.calls:
            prev_calls, prev_time, prev_read = 0, 0.0, 0
        else:
            prev_calls = prev.calls
            prev_time = prev.total_exec_time_ms
            prev_read = prev.shared_blks_read

        calls = now.calls - prev_calls
        if calls <= 0:
            continue

        total_time = now.total_exec_time_ms - prev_time
        windows.append(
            QueryWindow(
                queryid=queryid,
                query=now.query,
                calls=calls,
                total_time_ms=total_time,
                mean_time_ms=total_time / calls,
                blocks_read_from_disk=now.shared_blks_read - prev_read,
            )
        )

    windows.sort(key=lambda w: w.total_time_ms, reverse=True)
    return windows