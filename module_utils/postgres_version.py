"""Central PostgreSQL major selection. No implicit upgrade or binary fallback."""
import re

MINIMUM_MAJOR = 14
RELEASED_BASELINE = 18  # Informational, not an upper bound on selection.


def validate_major(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value) or int(value) < MINIMUM_MAJOR:
        raise ValueError('PostgreSQL major must be a quoted integer of 14 or above (no minor, latest, or prerelease tag)')
    return value


def resolve_major(model=None, packages=None):
    """Model is authoritative; legacy inventories derive their one pinned major."""
    selected = (model or {}).get('major')
    pinned = {match[1] for name in (packages or {})
              if (match := re.fullmatch(r'postgresql-(?:client-)?([0-9]+)', name))}
    if selected is not None:
        validate_major(selected)
        if pinned and pinned != {selected}:
            raise ValueError('PostgreSQL model major and pinned server/client package majors disagree; no upgrade is performed')
        return selected
    if len(pinned) != 1:
        raise ValueError('Select postgresql_deployment.major or exactly one matching pinned PostgreSQL server/client major')
    return validate_major(pinned.pop())


def check_data_major(major, existing):
    validate_major(major)
    if existing is not None and existing.strip() != major:
        raise ValueError('Existing PG_VERSION differs from selected major; preserve data and plan a separate major upgrade')
