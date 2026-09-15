"""Pure component selection and availability reporting; no side effects."""
def component_plan(model):
    value = model.get('components', {})
    if not isinstance(value, dict) or set(value) - {'backup', 'haproxy'}:
        raise ValueError('components accepts only backup and haproxy Boolean switches')
    result = {'backup': False, 'haproxy': model.get('mode') == 'cluster'}
    for key, selected in value.items():
        if type(selected) is not bool:
            raise ValueError('components.' + key + ' must be a YAML Boolean')
        result[key] = selected
    if model.get('mode') == 'standalone' and result['haproxy']:
        raise ValueError('Standalone uses its PostgreSQL endpoint; select cluster mode for HAProxy')
    return result


def cluster_components(cluster, model):
    if model.get('architecture') != 'modular':
        return cluster
    from copy import deepcopy
    result = deepcopy(cluster)
    switches = component_plan(model)
    result['architecture'] = 'modular'
    result['components'] = {'haproxy': switches['haproxy'], 'wal_archive': False}
    if not switches['haproxy'] and isinstance(result.get('packages'), dict):
        result['packages'] = {name: pin for name, pin in result['packages'].items() if name not in ('haproxy', 'keepalived')}
    return result
