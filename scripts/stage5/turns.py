"""Strict, bounded turn-chain inspection; no inferred truck permission."""
from scripts.stage5.temporal import parse_conditional

VALUES = {'no_left_turn', 'no_right_turn', 'no_straight_on', 'no_u_turn',
          'only_left_turn', 'only_right_turn', 'only_straight_on', 'only_u_turn'}
EXCEPT = {'hgv', 'motor_vehicle', 'vehicle', 'bus', 'bicycle', 'motorcar', 'taxi', 'psv', 'emergency', 'motorcycle'}

def analyze_turn(tags, members, ways, source=None, vehicle='hgv'):
    out = {'raw': {'tags': tags, 'members': members}, 'source': source,
           'status': 'QUARANTINE', 'navigation_eligible': False,
           'parse_status': 'UNKNOWN', 'reasons': [], 'vehicle': vehicle}
    reasons = out['reasons']
    if vehicle != 'hgv': reasons.append('unsupported_vehicle_context')
    keys = ['restriction:hgv', 'restriction:motor_vehicle', 'restriction:vehicle', 'restriction']
    key = next((k for k in keys if k in tags or k+':conditional' in tags), None)
    if key is None: reasons.append('missing_restriction'); return out
    supported_keys = set(keys) | {k+':conditional' for k in keys}
    if any(k.startswith('restriction:') and k not in supported_keys and k not in {'restriction:motorcar','restriction:bus','restriction:bicycle','restriction:taxi','restriction:psv','restriction:motorcycle','restriction:foot','restriction:emergency'} for k in tags):
        reasons.append('unsupported_restriction_qualifier')
    if any(k+':conditional' in tags for k in keys if k != key):
        reasons.append('multiple_vehicle_conditional_scopes')
    out['selected_key'] = key
    val = tags.get(key)
    if key+':conditional' in tags:
        conditional = parse_conditional(tags[key+':conditional'], source)
        out['conditional'] = conditional
        if conditional['parse_status'] != 'SUPPORTED': reasons.append('unsupported_conditional')
        elif conditional['value'] not in VALUES: reasons.append('unsupported_conditional_turn')
        if val is not None and conditional.get('value') != val:
            reasons.append('base_conditional_value_conflict')
        if val is None: val = conditional.get('value')
    if val not in VALUES: reasons.append('unsupported_turn_value')
    out['restriction'] = val
    out['semantics'] = 'ONLY_SEQUENCE' if val and val.startswith('only_') else 'NO_SEQUENCE'
    exceptions = tags.get('except', '').split(';') if tags.get('except') else []
    if any(e not in EXCEPT for e in exceptions): reasons.append('unsupported_except')
    out['except'] = exceptions
    out['applies_to_hgv'] = not bool(set(exceptions) & {'hgv', 'motor_vehicle', 'vehicle'})
    if not out['applies_to_hgv'] and key != 'restriction': reasons.append('specific_rule_except_conflict')
    roles = {role: [m for m in members if m.get('role') == role] for role in ('from', 'via', 'to')}
    if any(m.get('role') not in roles for m in members): reasons.append('unknown_member_role')
    if len(roles['from']) != 1 or len(roles['to']) != 1 or not roles['via']:
        reasons.append('incomplete_or_multiple_from_to'); return out
    fr, to = roles['from'][0], roles['to'][0]
    if fr.get('type') not in ('w', 'way') or to.get('type') not in ('w','way'):
        reasons.append('from_to_not_way'); return out
    via = roles['via']
    node_via = len(via) == 1 and via[0].get('type') in ('n', 'node')
    if not node_via and any(m.get('type') not in ('w', 'way') for m in via):
        reasons.append('mixed_or_multiple_via_nodes'); return out
    chain = [fr['id']] + ([] if node_via else [m['id'] for m in via]) + [to['id']]
    if len(chain) > 64: reasons.append('chain_limit_exceeded'); return out
    if len(set(chain)) != len(chain): reasons.append('repeated_way_ambiguous'); return out
    if any(w not in ways for w in chain): reasons.append('missing_way'); return out
    nodes = [ways[w]['nodes'] for w in chain]
    if any(len(n) < 2 or len(n) != len(set(n)) for n in nodes):
        reasons.append('short_or_repeated_nodes_ambiguous'); return out
    joins = []
    for a, b in zip(nodes, nodes[1:]):
        shared = set(a) & set(b)
        if node_via: shared &= {via[0]['id']}
        if len(shared) != 1: reasons.append('missing_or_ambiguous_connection'); return out
        joins.append(next(iter(shared)))
    def direction(w):
        way_tags = ways[w].get('tags', {})
        if any(k.startswith('oneway:') for k in way_tags):
            reasons.append('unsupported_oneway_modifier')
            return None
        tag = way_tags.get('oneway')
        return {'yes':1,'1':1,'true':1,'-1':-1,'no':0,'0':0,'false':0}.get(tag)
    for i, w in enumerate(chain):
        d = direction(w)
        if d is None: reasons.append('unknown_direction'); continue
        n = nodes[i]
        if i == 0:
            j = n.index(joins[0]); valid = (j > 0 and d in (0,1)) or (j < len(n)-1 and d in (0,-1))
        elif i == len(chain)-1:
            j = n.index(joins[-1]); valid = (j < len(n)-1 and d in (0,1)) or (j > 0 and d in (0,-1))
        else:
            entry, leave = n.index(joins[i-1]), n.index(joins[i])
            valid = entry != leave and (d == 0 or (leave-entry)*d > 0)
        if not valid: reasons.append('directed_chain_conflict')
    out.update(chain_way_ids=chain, connection_node_ids=joins)
    if not reasons: out['parse_status'] = 'SUPPORTED'
    return out

def iter_turn_records(db, source):
    """Bounded per-relation lookup against indexed source ways; no graph mutation."""
    import json
    for rid, tags, members, missing in db.execute('SELECT id,tags,members,missing_refs FROM relations ORDER BY id'):
        members = json.loads(members)
        ways = {}
        for member in members:
            if member.get('type') not in ('w','way'): continue
            row = db.execute('SELECT nodes,tags FROM ways WHERE id=?', (member['id'],)).fetchone()
            if row: ways[member['id']] = {'nodes': json.loads(row[0]), 'tags': json.loads(row[1])}
        record = analyze_turn(json.loads(tags), members, ways, source)
        record.update(object_type='relation', object_id=rid, missing_refs=json.loads(missing))
        if record['missing_refs']:
            record['parse_status'] = 'UNKNOWN'; record['reasons'].append('source_missing_reference')
        yield record
