from datetime import UTC, datetime, timedelta, timezone

import pytest

from inspire_flow_backend.data.types import UTCDateTime


def test_utc_datetime_normalizes_to_naive_utc_for_sqlite() -> None:
    column_type = UTCDateTime()
    source = datetime(2026, 7, 23, 18, 30, tzinfo=timezone(timedelta(hours=8)))

    stored = column_type.process_bind_param(source, None)

    assert stored == datetime(2026, 7, 23, 10, 30)
    assert stored.tzinfo is None


def test_utc_datetime_restores_aware_utc() -> None:
    column_type = UTCDateTime()

    restored = column_type.process_result_value(datetime(2026, 7, 23, 10, 30), None)

    assert restored == datetime(2026, 7, 23, 10, 30, tzinfo=UTC)


def test_utc_datetime_rejects_naive_input() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        UTCDateTime().process_bind_param(datetime(2026, 7, 23, 10, 30), None)
