"""Bounded segment routing with traversal-history rules, for research only.

No output is a navigation permission. Producer input and source provenance must be
retained by the caller; stage5 source objects are never modified.
"""
from __future__ import annotations
import datetime as dt
import heapq
import math
import sys
import time
from collections import Counter, defaultdict
from scripts.stage5.temporal import evaluate_conditional

DEFAULT_LIMITS = {'max_states': 100000, 'max_memory_bytes': 128 * 1024 * 1024,
                  'max_runtime_seconds': 30.0, 'max_input_edges': 500000,
                  'max_expansions': 500000, 'max_rules': 50000,
                  'max_rule_length': 64}
def _identifier(value):
    return isinstance(value,(str,int)) and not isinstance(value,bool)


EXCEPT_VALUES = {'hgv','motor_vehicle','vehicle','motorcar','bus','bicycle','taxi','psv','emergency','motorcycle'}


def _size(value):
    """Conservative retained-object accounting; shared subobjects overcounted."""
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(_size(k)+_size(v) for k,v in value.items())
    if isinstance(value, (tuple,list,set,frozenset)):
        return sys.getsizeof(value) + sum(_size(v) for v in value)
    return sys.getsizeof(value)


def normalize_rules(rules):
    """Copy rules and retain original evidence; no status upgrade or source edit."""
    normalized = []
    for i, raw in enumerate(rules):
        r = dict(raw)
        r['id'] = raw.get('id', raw.get('object_id', i))
        r['sequence'] = tuple(raw.get('sequence', raw.get('chain_way_ids', ())))
        r['connection_nodes'] = tuple(raw.get('connection_nodes', raw.get('connection_node_ids', ())))
        r['kind'] = raw.get('kind', {'NO_SEQUENCE':'no','ONLY_SEQUENCE':'only'}.get(raw.get('semantics')))
        exc = raw.get('except', ())
        r['except'] = tuple(exc.split(';') if isinstance(exc, str) else exc)
        r['parse_status'] = raw.get('parse_status', 'UNKNOWN')
        r['normalization_reasons'] = []
        if (len(r['sequence']) < 2 or len(r['connection_nodes']) != len(r['sequence'])-1
                or r['kind'] not in ('no','only')):
            r['parse_status'] = 'UNKNOWN'
            r['normalization_reasons'].append('incomplete_rule_topology')
        if len(r['sequence']) > 2 and any(a == b for a,b in zip(r['sequence'],r['sequence'][1:])):
            r['parse_status'] = 'UNKNOWN'
            r['normalization_reasons'].append('consecutive_repeated_way_chain_unsupported')
        if not _identifier(r['id']) or any(not _identifier(x) for x in r['sequence'] + r['connection_nodes']):
            r['sequence'] = ()
            r['connection_nodes'] = ()
            r['id'] = str(r['id'])
            r['parse_status'] = 'UNKNOWN'
            r['normalization_reasons'].append('invalid_rule_identifiers')
        if any(not isinstance(x,str) or x not in EXCEPT_VALUES for x in r['except']):
            r['parse_status'] = 'UNKNOWN'
            r['normalization_reasons'].append('unsupported_exception')
            r['except'] = ()
        # A stage5 ordinary restriction remains effective outside its conditional
        # expression. A differing conditional value is UNKNOWN in stage5 already.
        tags = raw.get('raw', {}).get('tags', {}) if isinstance(raw.get('raw'), dict) else {}
        key = raw.get('selected_key')
        if key and key in tags:
            r['conditional'] = None
            r['unconditional_base_present'] = True
        r['navigation_eligible'] = False
        normalized.append(r)
    return normalized


def _suffix_prefix(history, rule, length):
    if length <= 0 or len(history) < length:
        return False
    sample = history[-length:]
    return (tuple(x[0] for x in sample) == rule['sequence'][:length]
            and tuple(x[1] for x in sample[1:]) == rule['connection_nodes'][:length-1])


def advance_history(history, previous_edge, edge, maximum):
    """Collapse same-way segments, including backtracking, without losing entry.

    Immediate reverse arcs are recognized separately by transition_decision for
    U-turns; they must not erase an active via-way traversal obligation.
    """
    if history and history[-1][0] == edge['way_id']:
        return history
    return (history + ((edge['way_id'], edge['from']),))[-maximum:]


def transition_decision(history, previous_edge, next_edge, rules, instant, vehicle='hgv'):
    """Evaluate one manoeuvre before travelling next_edge; rules normalized first.

    history is a tuple of (way_id, run_entry_node) tuples. Start history is empty.
    Unsupported rules affect UNKNOWN only where their listed ways are touched;
    missing scope affects every transition. Unknown never becomes an exemption.
    """
    blocked, unknown, applied, reasons = False, False, [], []
    if vehicle != 'hgv':
        unknown = True; reasons.append('unsupported_vehicle_context')
    node = next_edge['from']
    reversal = (previous_edge is not None and previous_edge['from'] == next_edge['to']
                and previous_edge['to'] == node)
    way_change = not history or history[-1][0] != next_edge['way_id'] or reversal
    for rule in rules:
        seq = rule['sequence']
        if rule['parse_status'] != 'SUPPORTED':
            if not seq or next_edge['way_id'] in seq or (history and history[-1][0] in seq):
                unknown = True; applied.append(rule['id']); reasons.append('unsupported_rule:'+str(rule['id']))
            continue
        if set(rule['except']) & {'hgv','motor_vehicle','vehicle'}:
            continue
        relevant = False
        if rule['kind'] == 'no':
            length = len(seq)-1
            relevant = (way_change and _suffix_prefix(history, rule, length)
                        and node == rule['connection_nodes'][-1]
                        and next_edge['way_id'] == seq[-1])
        else:
            # Evaluate every overlapping active prefix. Several constraints can
            # apply simultaneously; no single prefix is silently discarded.
            for length in range(1, len(seq)):
                if not _suffix_prefix(history, rule, length):
                    continue
                if length == 1 and node != rule['connection_nodes'][0]:
                    continue
                continuation = not way_change
                correct_next = (way_change and next_edge['way_id'] == seq[length]
                                and node == rule['connection_nodes'][length-1])
                if length == 1:
                    # At the specified junction, continuing past the turn also
                    # violates ONLY. Elsewhere on the from-way it has no effect.
                    violation = not correct_next
                else:
                    violation = not (continuation or correct_next)
                    # Once at the next specified junction, skipping it is a
                    # divergence, including continuing on the same via-way.
                    if node == rule['connection_nodes'][length-1] and not correct_next:
                        violation = True
                if violation:
                    relevant = True
        if not relevant:
            continue
        applied.append(rule['id'])
        condition = rule.get('conditional')
        if condition is not None:
            try: active = evaluate_conditional(condition, instant)['active']
            except (TypeError,ValueError,KeyError,AttributeError,OverflowError): active = None
        else:
            active = True
        if active is None:
            unknown = True; reasons.append('unknown_rule_time:'+str(rule['id']))
        elif active:
            blocked = True; reasons.append('prohibited_manoeuvre:'+str(rule['id']))
    return {'blocked': blocked, 'unknown': unknown,
            'rule_ids': sorted(set(applied), key=str), 'reasons': sorted(set(reasons)),
            'navigation_eligible': False}


def research_route(edges, start, goal, rules, departure, limits=None, vehicle='hgv'):
    """Dijkstra search over segment nodes + bounded suffix + conditional clock.

    Results are research claims only. An UNKNOWN path is reported as
    ADMISSIBILITY_UNDETERMINED, never RESEARCH_PATH_FOUND. Resource exhaustion is
    INCOMPLETE, including when an uncertain candidate has been found. There is no
    waiting action. Durations are supplied research assumptions, never inferred.
    """
    began = time.monotonic()
    budget = dict(DEFAULT_LIMITS)
    if limits:
        if any(k not in budget for k in limits):
            return {'status':'INCOMPLETE','reasons':['invalid_limit_key'],'navigation_eligible':False}
        budget.update(limits)
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v <= 0 for v in budget.values()):
        return {'status':'INCOMPLETE','reasons':['invalid_resource_limit'],'navigation_eligible':False}
    counts = {'states':0, 'expansions':0, 'input_edges':0, 'rules':0, 'accounted_memory_bytes':0}
    diagnostics = Counter()
    parents = {}
    candidate = None
    def finish(status, reasons, state_id=None):
        edge_ids, path_reasons, path_rules = [], set(), set()
        if state_id is not None:
            cursor = state_id
            while cursor is not None:
                parent, edge_id, why, used = parents[cursor]
                if edge_id is not None: edge_ids.append(edge_id)
                path_reasons.update(why); path_rules.update(used)
                cursor = parent
            edge_ids.reverse()
        return {'status':status, 'reasons':sorted(set(reasons)|path_reasons),
                'edge_ids':edge_ids,'applied_rule_ids':sorted(path_rules,key=str),
                'counts':dict(counts), 'rejection_counts':dict(diagnostics),
                'limits':budget,'navigation_eligible':False,
                'arrival': arrivals.get(state_id).isoformat() if state_id is not None and arrivals.get(state_id) is not None else None}
    arrivals = {}
    def failure():
        if time.monotonic()-began > budget['max_runtime_seconds']: return 'runtime_limit'
        if counts['accounted_memory_bytes'] > budget['max_memory_bytes']: return 'memory_limit'
        return None
    adjacency = defaultdict(list)
    edge_ids_seen = set()
    # Bounded ingestion must precede national search. No truncated graph/rule
    # set is searched and passed off as the requested full input.
    for e in edges:
        if counts['input_edges'] >= budget['max_input_edges']:
            return finish('INCOMPLETE',['input_edge_limit'])
        counts['input_edges'] += 1
        if not isinstance(e,dict) or any(k not in e for k in ('id','from','to','way_id')):
            return finish('INCOMPLETE',['invalid_edge_structure'])
        if any(not _identifier(e[k]) for k in ('id','from','to','way_id')):
            return finish('INCOMPLETE',['invalid_edge_identifiers'])
        if e['id'] in edge_ids_seen:
            return finish('INCOMPLETE',['duplicate_edge_id'])
        edge_ids_seen.add(e['id'])
        edge = dict(e)
        added = _size(edge) + 256
        if counts['accounted_memory_bytes'] + added > budget['max_memory_bytes']:
            return finish('INCOMPLETE',['memory_limit'])
        counts['accounted_memory_bytes'] += added
        problem = failure()
        if problem: return finish('INCOMPLETE',[problem])
        adjacency[edge['from']].append(edge)
    if not _identifier(start) or not _identifier(goal):
        return finish('INCOMPLETE',['invalid_endpoint_identifiers'])
    normalized = []
    for rule in rules:
        if counts['rules'] >= budget['max_rules']:
            return finish('INCOMPLETE',['rule_count_limit'])
        counts['rules'] += 1
        if not isinstance(rule,dict):
            return finish('INCOMPLETE',['invalid_rule_structure'])
        raw_rule = dict(rule)
        raw_rule.setdefault('id', raw_rule.get('object_id', counts['rules']-1))
        try: r = normalize_rules([raw_rule])[0]
        except (TypeError,ValueError):
            return finish('INCOMPLETE',['invalid_rule_structure'])
        if len(r['sequence']) > budget['max_rule_length']:
            return finish('INCOMPLETE',['rule_length_limit'])
        added = _size(r) + 128
        if counts['accounted_memory_bytes'] + added > budget['max_memory_bytes']:
            return finish('INCOMPLETE',['memory_limit'])
        counts['accounted_memory_bytes'] += added
        problem = failure()
        if problem: return finish('INCOMPLETE',[problem])
        normalized.append(r)
    maximum = max((len(r['sequence']) for r in normalized), default=2)
    timed = any(r.get('conditional') is not None for r in normalized)
    aware = isinstance(departure,dt.datetime) and departure.tzinfo is not None and departure.utcoffset() is not None
    initial_time = departure.astimezone(dt.timezone.utc) if aware else None
    # Preserve stage5 DST safeguards before normalization to UTC: an imaginary
    # local datetime is not a real known departure instant.
    if aware:
        from scripts.stage5.temporal import ZONE
        if departure.tzinfo == ZONE and departure.astimezone(dt.timezone.utc).astimezone(ZONE).replace(tzinfo=None) != departure.replace(tzinfo=None):
            initial_time = None
    initial_unknown = vehicle != 'hgv' or initial_time is None
    initial_reasons = (['unknown_departure_time'] if initial_time is None else []) + (['unsupported_vehicle_context'] if vehicle != 'hgv' else [])
    serial = 0
    # State previous arc is part of the key: distinguish U-turn from sameway
    # continuation and retain incoming entrance orientation at identical nodes.
    initial = (start, (), None, 0 if initial_time is not None and timed else None, initial_unknown)
    best = {initial:0.0}
    heap = [(initial_unknown,0.0,serial,initial,None)]
    parents[0] = (None,None,initial_reasons,())
    arrivals[0] = initial_time
    counts['states'] = 1
    added = _size(initial) + 1024
    if counts['accounted_memory_bytes'] + added > budget['max_memory_bytes']:
        return finish('INCOMPLETE',['memory_limit'])
    counts['accounted_memory_bytes'] += added
    while heap:
        problem = failure()
        if problem: return finish('INCOMPLETE',[problem],candidate)
        uncertain,cost,sid,state,previous = heapq.heappop(heap)
        if best.get(state) != cost: continue
        node,history,prev_key,clock,_ = state
        instant = arrivals[sid]
        if node == goal:
            if not uncertain: return finish('RESEARCH_PATH_FOUND',[],sid)
            candidate = sid
            # Heap orders known paths before uncertain paths. At this point no
            # unexplored wholly known path exists in the bounded state space.
            return finish('ADMISSIBILITY_UNDETERMINED',['unknown_route_admissibility'],sid)
        for edge in adjacency.get(node, ()):
            if counts['expansions'] >= budget['max_expansions']:
                return finish('INCOMPLETE',['expansion_limit'],candidate)
            counts['expansions'] += 1
            problem = failure()
            if problem: return finish('INCOMPLETE',[problem],candidate)
            if edge.get('admissibility') == 'DENIED':
                diagnostics['denied_edge_admissibility'] += 1; continue
            if edge.get('direction_status') == 'BLOCKED':
                diagnostics['blocked_edge_direction'] += 1; continue
            decision = transition_decision(history,previous,edge,normalized,instant,vehicle)
            if decision['blocked']:
                diagnostics.update(decision['reasons']); continue
            why = list(decision['reasons'])
            unknown = uncertain or decision['unknown']
            if edge.get('direction_status') != 'KNOWN':
                unknown = True; why.append('unknown_edge_direction:'+str(edge['id']))
            if edge.get('admissibility') != 'KNOWN':
                unknown = True; why.append('unknown_edge_admissibility:'+str(edge['id']))
                why.extend(str(x) for x in (edge.get('reasons') or ()))
            duration = edge.get('duration_seconds')
            known_duration = (isinstance(duration,(int,float)) and not isinstance(duration,bool)
                              and math.isfinite(duration) and duration > 0)
            if not known_duration:
                unknown = True; why.append('unknown_edge_duration:'+str(edge['id']))
                arrival = None; duration = 0.0
            else:
                try: arrival = instant + dt.timedelta(seconds=duration) if instant is not None else None
                except (OverflowError,ValueError):
                    arrival = None; unknown = True; why.append('arrival_time_overflow')
            new_history = advance_history(history,previous,edge,maximum)
            elapsed = (arrival-initial_time).total_seconds() if timed and arrival is not None and initial_time is not None else None
            new_cost = cost+duration
            if not math.isfinite(new_cost):
                new_cost = cost; unknown = True; why.append('duration_cost_overflow')
            new_state = (edge['to'],new_history,(edge['from'],edge['to'],edge['way_id']),elapsed,unknown)
            if new_cost >= best.get(new_state,float('inf')): continue
            if counts['states'] >= budget['max_states']:
                return finish('INCOMPLETE',['state_limit'],candidate)
            extra = _size(new_state) + _size(why) + _size(decision['rule_ids']) + 1536
            if counts['accounted_memory_bytes'] + extra > budget['max_memory_bytes']:
                return finish('INCOMPLETE',['memory_limit'],candidate)
            counts['accounted_memory_bytes'] += extra
            counts['states'] += 1
            serial += 1
            parents[serial] = (sid,edge['id'],why,decision['rule_ids'])
            arrivals[serial] = arrival
            best[new_state] = new_cost
            heapq.heappush(heap,(unknown,new_cost,serial,new_state,edge))
    return finish('NO_ROUTE',['no_path_under_supplied_research_model'])
