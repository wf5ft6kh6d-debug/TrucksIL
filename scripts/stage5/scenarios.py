"""Research connectivity diagnostics; no navigation permissions or synthetic source claims."""
import argparse
from array import array
from collections import Counter, deque
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3

# Support direct CLI as well as import / python -m.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.stage4.automotive_graph import classify


def _hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dimension_decision(vehicle, evidence):
    """Exact decimal metres; historical/structure height never authorizes passage.

    All supplied evidence is retained. Conflicting comparable values quarantine
    even if both exceed the vehicle height; equality has no safety margin.
    """
    result = dict(decision='UNKNOWN', navigation_eligible=False, evidence=evidence)
    try:
        v = Decimal(str(vehicle))
        if not v.is_finite() or v <= 0:
            raise ValueError('invalid vehicle height')
    except (InvalidOperation, ValueError):
        return dict(result, reason='invalid_vehicle_height')
    values = []
    for item in evidence:
        if (item.get('quantity') != 'permitted_clearance' or item.get('unit') != 'm'
                or item.get('current') is not True or not item.get('source')):
            return dict(result, reason='incomplete_historical_or_non_clearance_evidence')
        try:
            x = Decimal(str(item['value']))
            if not x.is_finite() or x <= 0:
                raise ValueError('invalid height')
            values.append(x)
        except (KeyError, InvalidOperation, ValueError):
            return dict(result, reason='invalid_clearance_value')
    if not values:
        return dict(result, reason='missing_clearance')
    if len(set(values)) != 1:
        return dict(result, reason='conflicting_clearance_sources')
    if v > values[0]:
        return dict(result, decision='TAGGED_DENIED', reason='height_exceeds_stated_limit')
    if v == values[0]:
        return dict(result, reason='equal_height_no_margin')
    return dict(result, decision='TAGGED_ALLOWED', reason='numeric_fit_only_not_navigation_permission')


def combine_decisions(decisions):
    """Conjunction of research evaluations; missing/unknown never becomes allowed."""
    decisions = list(decisions)
    if 'TAGGED_DENIED' in decisions and any(x != 'TAGGED_DENIED' for x in decisions):
        return 'UNKNOWN'
    if decisions and all(x == 'TAGGED_DENIED' for x in decisions):
        return 'TAGGED_DENIED'
    if not decisions or any(x != 'TAGGED_ALLOWED' for x in decisions):
        return 'UNKNOWN'
    return 'TAGGED_ALLOWED'


def synthetic_scenarios():
    e = dict(quantity='permitted_clearance', unit='m', current=True,
             source='SYNTHETIC-fixture-only', value='4.20')
    cases = [('height_below', '4.19', [e]), ('height_equal', '4.20', [e]),
             ('height_above', '4.21', [e]), ('height_missing', '4.00', []),
             ('height_historical', '4.00', [dict(e, current=False)]),
             ('structure_height', '4.00', [dict(e, quantity='structure_height')]),
             ('height_conflict', '4.00', [e, dict(e, value='4.30', source='SYNTHETIC-other')])]
    out = [dict(id=name, synthetic=True, category='dimensions', result=dimension_decision(v, ev),
                navigation_eligible=False) for name, v, ev in cases]
    for name, decisions in [('node_denies_way_allows', ['TAGGED_ALLOWED', 'TAGGED_DENIED']),
                            ('car_allow_hgv_unknown', ['TAGGED_ALLOWED', 'UNKNOWN']),
                            ('time_unparsed', ['TAGGED_ALLOWED', 'QUARANTINE']),
                            ('turn_incomplete', ['UNKNOWN']), ('missing_rules', [])]:
        out.append(dict(id=name, synthetic=True, category='rule_composition', inputs=decisions,
                        result=combine_decisions(decisions), navigation_eligible=False))
    return out


def synthetic_history_reachability(edges, source, target, turn_rules=()):
    """Toy directed atomic-way graph ONLY; bounded memory for via-way rules.

    Not a real road router: fixtures must represent every way by one directed
    atomic edge and have known endpoints. Real multi-segment OSM ways need a
    separately audited entry/exit and traversal-state implementation.
    """
    rules = []
    for rule in turn_rules:
        if rule.get('parse_status') != 'SUPPORTED' or rule.get('conditional'):
            return dict(synthetic=True, result='UNKNOWN', navigation_eligible=False,
                        reason='unsupported_or_context_dependent_turn')
        if rule.get('applies_to_hgv') is False:
            continue
        if rule.get('applies_to_hgv') is not True:
            return dict(synthetic=True, result='UNKNOWN', navigation_eligible=False,
                        reason='unknown_vehicle_applicability')
        chain = tuple(rule.get('chain_way_ids', []))
        if len(chain) < 2 or rule.get('semantics') not in ('NO_SEQUENCE', 'ONLY_SEQUENCE'):
            return dict(synthetic=True, result='UNKNOWN', navigation_eligible=False,
                        reason='invalid_turn_chain')
        rules.append((chain, rule['semantics']))
    adjacency = {}
    for a, b, way in edges:
        adjacency.setdefault(a, []).append((b, way))
    memory = max((len(c)-1 for c,_ in rules), default=0)
    queue = deque([(source, ())]); visited = {(source, ())}
    reached = False
    while queue:
        node, history = queue.popleft()
        if node == target:
            reached = True
        for following, way in adjacency.get(node, []):
            candidate = history + (way,)
            denied = False
            for chain, semantic in rules:
                if semantic == 'NO_SEQUENCE':
                    denied |= candidate[-len(chain):] == chain
                else:
                    # Every matching suffix prefix has an obligation to continue.
                    for k in range(1, len(chain)):
                        if len(history) >= k and history[-k:] == chain[:k] and way != chain[k]:
                            denied = True
            if denied:
                continue
            state = (following, candidate[-memory:] if memory else ())
            if state not in visited:
                visited.add(state); queue.append(state)
    return dict(synthetic=True, result='REACHABLE_IN_SYNTHETIC_MODEL' if reached else 'UNREACHABLE_IN_SYNTHETIC_MODEL',
                states=len(visited), navigation_eligible=False)


def temporal_turn_scenarios():
    """Explicitly SYNTHETIC temporal boundary and directed via-way fixtures."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from scripts.stage5.temporal import parse_conditional, evaluate_conditional
    from scripts.stage5.turns import analyze_turn
    zone = ZoneInfo('Asia/Jerusalem')
    cases = [('start_inclusive', '2026-10-12T07:00:00', 'no @ (Mo-Fr 07:00-09:00)'),
             ('end_exclusive', '2026-10-12T09:00:00', 'no @ (Mo-Fr 07:00-09:00)'),
             ('overnight_previous_day', '2026-10-13T01:00:00', 'no @ (Mo 22:00-02:00)'),
             ('overnight_end_exclusive', '2026-10-13T02:00:00', 'no @ (Mo 22:00-02:00)'),
             ('holiday_unsupported', '2026-10-12T07:00:00', 'no @ (PH 07:00-09:00)'),
             ('dst_repeated', '2026-10-25T01:30:00', 'no @ (00:00-04:00)'),
             ('dst_missing', '2026-03-27T02:30:00', 'no @ (00:00-04:00)')]
    out = []
    for name, instant, raw in cases:
        parsed = parse_conditional(raw, 'SYNTHETIC-fixture-only')
        result = evaluate_conditional(parsed, dt.datetime.fromisoformat(instant).replace(tzinfo=zone))
        out.append(dict(id=name, category='temporal', synthetic=True, raw=raw,
                        instant=instant, timezone='Asia/Jerusalem', parsed=parsed,
                        result=result, navigation_eligible=False))
    ways = {10: {'nodes':[1,2], 'tags':{'oneway':'yes'}},
            20: {'nodes':[2,3], 'tags':{'oneway':'yes'}},
            30: {'nodes':[3,4], 'tags':{'oneway':'yes'}}}
    members = [dict(type='way', id=w, role=r) for w,r in [(10,'from'),(20,'via'),(30,'to')]]
    for name, tags, chain in [('no_via_sequence', {'restriction':'no_straight_on'}, members),
                              ('only_via_sequence', {'restriction':'only_straight_on'}, members),
                              ('except_hgv', {'restriction':'no_straight_on','except':'hgv'}, members),
                              ('incomplete_chain', {'restriction':'no_straight_on'}, members[:2])]:
        result = analyze_turn(tags, chain, ways, source='SYNTHETIC-fixture-only')
        out.append(dict(id=name, category='turn', synthetic=True, result=result,
                        navigation_eligible=False))
    opposite = {**ways, 20: {'nodes':[2,3], 'tags':{'oneway':'-1'}}}
    out.append(dict(id='contradictory_via_direction', category='turn', synthetic=True,
                    result=analyze_turn({'restriction':'no_straight_on'}, members, opposite,
                                        source='SYNTHETIC-fixture-only'), navigation_eligible=False))
    for hour in (7,9):
        parsed=parse_conditional('no @ (Mo-Fr 07:00-09:00)', 'SYNTHETIC-fixture-only')
        parsed.update(object_type='way',object_id=20,tag_key='hgv:conditional')
        _, rules, counts=conditional_overlay([parsed],dt.datetime(2026,10,12,hour,tzinfo=zone))
        rows=[(10,1,2,'forward'),(20,2,3,'forward')]
        filtered=list(_edge_filter(rows,{1:0,2:1,3:2},{},_rule_map(rules),True))
        out.append(dict(id='time_path_'+str(hour),category='synthetic_time_reachability',synthetic=True,
                        result=graph_metrics([1,2,3],filtered,[0]),rule_evaluations=counts,navigation_eligible=False))
    barrier_edges=list(_edge_filter([(10,1,2,'forward'),(20,2,3,'forward')],{1:0,2:1,3:2},
                                   _rule_map([dict(id=2,decision='TAGGED_DENIED')]),{},True))
    out.append(dict(id='barrier_path',category='synthetic_barrier_reachability',synthetic=True,
                    result=graph_metrics([1,2,3],barrier_edges,[0]),navigation_eligible=False))
    graph = [(1,2,10),(2,3,20),(3,4,30),(3,5,40)]
    for name, rule, target in [('no_sequence_blocks', {'restriction':'no_straight_on'}, 4),
                               ('only_sequence_blocks_other_exit', {'restriction':'only_straight_on'}, 5),
                               ('hgv_exception_preserves_path', {'restriction':'no_straight_on','except':'hgv'}, 4)]:
        parsed = analyze_turn(rule, members, ways, source='SYNTHETIC-fixture-only')
        out.append(dict(id=name, category='synthetic_history_reachability', synthetic=True,
                        baseline=synthetic_history_reachability(graph,1,target),
                        result=synthetic_history_reachability(graph,1,target,[parsed]), navigation_eligible=False))
    return out


class _Components:
    def __init__(self, n):
        self.parent = array('I', range(n))
        self.size = array('I', [1]) * n
        self.count = n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def add(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]
        self.count -= 1

    def summary(self):
        return dict(components=self.count, largest_component=max(self.size, default=0))


def graph_metrics(node_ids, edges, origins):
    """edges=(a,b,direction), node IDs already dense. UNKNOWN contributes no arc.

    Weak topology includes UNKNOWN-direction segments and is reported separately
    from the known-direction graph. Node set stays fixed across experiments.
    """
    n = len(node_ids)
    topo = _Components(n)
    directed_weak = _Components(n)
    tails, heads = array('I'), array('I')
    directions = Counter()
    for a, b, direction in edges:
        topo.add(a, b)
        directions[direction] += 1
        if direction in ('forward', 'both'):
            tails.append(a); heads.append(b); directed_weak.add(a, b)
        if direction in ('reverse', 'both'):
            tails.append(b); heads.append(a); directed_weak.add(a, b)
    offsets = array('I', [0]) * (n + 1)
    for a in tails:
        offsets[a + 1] += 1
    for i in range(n):
        offsets[i + 1] += offsets[i]
    cursor = array('I', offsets)
    adjacency = array('I', [0]) * len(heads)
    for a, b in zip(tails, heads):
        adjacency[cursor[a]] = b
        cursor[a] += 1
    reach = []
    for origin in origins:
        seen = bytearray(n)
        seen[origin] = 1
        queue = deque([origin]); count = 1
        while queue:
            a = queue.popleft()
            for j in range(offsets[a], offsets[a+1]):
                b = adjacency[j]
                if not seen[b]:
                    seen[b] = 1; count += 1; queue.append(b)
        reach.append(dict(origin_node_id=node_ids[origin], reachable_nodes=count,
                          reachable_other_nodes=count - 1))
    return dict(vertices=n, segments=sum(directions.values()), directions=dict(sorted(directions.items())),
                weak_topology=topo.summary(), known_direction_weak=directed_weak.summary(),
                known_direction_arcs=len(tails), directed_reachability=reach,
                reachability_scope='fixed deterministic origins; not all-pairs or SCC')


def _rule_map(rules):
    result = {}
    for r in rules:
        identity = int(r['id'])
        direction = r.get('direction', 'both')
        if direction not in ('both', 'forward', 'backward'):
            raise ValueError('unsupported rule direction')
        decision = r['decision']
        if decision not in ('TAGGED_DENIED', 'UNKNOWN', 'TAGGED_ALLOWED'):
            raise ValueError('unsupported research decision')
        # Preserve concurrent sources; no last-write-wins conflict resolution.
        result.setdefault(identity, []).append((direction, decision))
    return result


def _edge_filter(rows, node_index, node_rules, way_rules, remove_unknown):
    for way, a, b, direction in rows:
        records = node_rules.get(a, []) + node_rules.get(b, []) + way_rules.get(way, [])
        blocked = {'TAGGED_DENIED', 'UNKNOWN'} if remove_unknown else {'TAGGED_DENIED'}
        forward = any(d in ('both', 'forward') and v in blocked for d, v in records)
        backward = any(d in ('both', 'backward') and v in blocked for d, v in records)
        # An unresolved direction cannot be oriented by a scoped restriction.
        if direction == 'unknown':
            if forward or backward:
                continue
        elif direction == 'both':
            if forward and backward:
                continue
            if forward:
                direction = 'reverse'
            elif backward:
                direction = 'forward'
        elif (direction == 'forward' and forward) or (direction == 'reverse' and backward):
            continue
        yield node_index[a], node_index[b], direction


def conditional_overlay(records, instant):
    """Deny-only research overlay, never infer authorization from inactive rules.

    Only unscoped HGV/inherited access keys are modeled. Multiple scopes/sources
    remain separate hypothetical constraints, not an override resolution.
    """
    from scripts.stage5.temporal import evaluate_conditional
    nodes, ways, counts = [], [], Counter()
    supported = {'access:conditional','vehicle:conditional','motor_vehicle:conditional','hgv:conditional'}
    for r in records:
        kind = r.get('object_type')
        if kind not in ('node','way') or r.get('tag_key') not in supported:
            counts['not_modeled_tag_or_object'] += 1
            continue
        value = r.get('value')
        evaluation = evaluate_conditional(r, instant)
        decision = 'UNKNOWN'
        if evaluation['active'] is False:
            counts['inactive_no_overlay'] += 1
            continue
        if evaluation['active'] is True and value == 'no':
            decision = 'TAGGED_DENIED'
        counts[decision] += 1
        (nodes if kind == 'node' else ways).append(dict(id=r['object_id'], decision=decision, direction='both'))
    return nodes, ways, dict(sorted(counts.items()))


def analyze_connectivity(source_graph, output_path, *, node_rules=(), way_rules=(), temporal_records=()):
    """Full national original graph classification, no writes and no geometric joins."""
    source = Path(source_graph).resolve()
    output = Path(output_path)
    if output.resolve() == source or (output.exists() and output.samefile(source)):
        raise ValueError('Output must not overwrite original graph')
    before_hash = _hash(source)
    nr, wr = _rule_map(node_rules), _rule_map(way_rules)
    db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    selected = set(); statuses = {}; way_counts = Counter(); segment_counts = Counter()
    for identity, tags in db.execute('SELECT id,tags FROM ways ORDER BY id'):
        status = classify(json.loads(tags))['status']
        way_counts[status] += 1; statuses[identity] = status
        if status == 'INCLUDED':
            selected.add(identity)
    node_ids = set(); degree = Counter()
    for way, a, b in db.execute('SELECT way_id,a,b FROM segments ORDER BY id'):
        if way in selected:
            node_ids.add(a); node_ids.add(b); degree[a] += 1; degree[b] += 1
        segment_counts[statuses[way]] += 1
    node_ids = sorted(node_ids)
    index = {identity: i for i, identity in enumerate(node_ids)}
    # Same three most incident nodes in every scenario, ties use OSM node ID.
    origin_ids = sorted(degree, key=lambda x: (-degree[x], x))[:3]
    origins = [index[x] for x in origin_ids]
    del degree
    def rows():
        return (r for r in db.execute('SELECT way_id,a,b,direction FROM segments ORDER BY id') if r[0] in selected)
    baseline = graph_metrics(node_ids, ((index[a], index[b], d) for _, a, b, d in rows()), origins)
    denied = graph_metrics(node_ids, _edge_filter(rows(), index, nr, wr, False), origins)
    uncertainty = graph_metrics(node_ids, _edge_filter(rows(), index, nr, wr, True), origins)
    temporal_results = []
    temporal_records = list(temporal_records)
    if temporal_records:
        import datetime as dt
        from zoneinfo import ZoneInfo
        for hour in (7,9):
            instant=dt.datetime(2026,10,12,hour,0,tzinfo=ZoneInfo('Asia/Jerusalem'))
            extra_nodes, extra_ways, counts = conditional_overlay(temporal_records,instant)
            tn={k:list(v) for k,v in nr.items()}; tw={k:list(v) for k,v in wr.items()}
            for key, values in _rule_map(extra_nodes).items(): tn.setdefault(key,[]).extend(values)
            for key, values in _rule_map(extra_ways).items(): tw.setdefault(key,[]).extend(values)
            temporal_results.append(dict(instant=instant.isoformat(), timezone='Asia/Jerusalem',
                scenario_context_synthetic=True, source_records_synthetic=False,
                rule_evaluations=counts,
                denial_only=graph_metrics(node_ids,_edge_filter(rows(),index,tn,tw,False),origins),
                denial_and_unknown=graph_metrics(node_ids,_edge_filter(rows(),index,tn,tw,True),origins)))
    db.close()
    if _hash(source) != before_hash:
        raise ValueError('source graph changed')
    result = dict(policy='stage5-connectivity-research-v1', source_sha256=before_hash,
                  source_preserved=True, synthetic=False, navigation_eligible=False,
                  verified_restrictions=0, temporal_national_effect='DENIAL_SENSITIVITY_ONLY' if temporal_records else 'NOT RUN: no temporal records supplied',
                  temporal_sensitivities=temporal_results,
                  via_way_national_effect='NOT IMPLEMENTED: requires history-state graph',
                  classification_way_counts=dict(sorted(way_counts.items())),
                  segment_counts=dict(sorted(segment_counts.items())), rule_node_count=len(nr), rule_way_count=len(wr),
                  rule_nodes_in_automotive=sum(n in index for n in nr),
                  rule_ways_in_automotive=sum(w in selected for w in wr),
                  baseline=baseline, tagged_denial_sensitivity=denied,
                  denial_and_unknown_sensitivity=uncertainty,
                  limitations=['Tag decisions are unverified research hypotheses.',
                               'No geometric snapping or added edges.',
                               'Missing directions contribute no directed arcs.',
                               'Access UNKNOWN is not permission even in baseline.',
                               'Conditional overlays model only unscoped access/vehicle/motor_vehicle/hgv no values at two declared instants; inactive never grants permission.',
                               'Via-way national effects require a history-state graph; only synthetic atomic-way history scenarios execute here.',
                               'Weak components alone do not establish truck reachability.',
                               'Origin BFS is not complete all-pairs reachability.'])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source_graph'); p.add_argument('output')
    p.add_argument('--rules', help='JSON object with normalized node_rules and way_rules arrays')
    args = p.parse_args()
    rule_input = json.loads(Path(args.rules).read_text()) if args.rules else {}
    print(json.dumps(analyze_connectivity(args.source_graph, args.output, **rule_input), indent=2))
