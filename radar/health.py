"""Evaluate statewide/federal and local government coverage independently."""


def health_groups(sources, health):
    groups = {name: {'failed': 0, 'total': 0} for name in ('state_federal', 'local')}
    for source in sources:
        if source['category'] == 'Industry':
            continue
        group = 'local' if source['category'] in ('Local funding', 'Project-based vouchers') else 'state_federal'
        groups[group]['total'] += 1
        groups[group]['failed'] += not health.get(source['id'], {}).get('ok')
    return groups


def threshold_failed(groups):
    return any(not g['total'] or g['failed'] * 10 > g['total'] * 3 for g in groups.values())
