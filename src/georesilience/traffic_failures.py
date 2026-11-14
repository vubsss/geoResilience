"""Reassign original OD demand after physical closures; never discard lost trips."""
import csv
import json
import math
from collections import OrderedDict
from pathlib import Path
from threading import RLock

import networkx as nx

from .traffic import assign_traffic
from .time_models import PreparedTimeModel


class ReassignedTrafficTimeModel:
    def __init__(self, graph, links, traffic, free, config, *, on_state=None):
        if traffic.summary['status'] != 'converged' or traffic.demand is None:
            raise ValueError('failure reassignment requires converged assignment and original OD demand')
        self.graph, self.links, self.traffic = graph, links, traffic
        self.free, self.config, self.on_state = free, config, on_state
        self.cache, self.events, self.lock = OrderedDict(), {}, RLock()

    def prepare(self, graph, config):
        return PreparedTimeModel(self.traffic.edge_seconds,
            {'status': 'computed', 'time_model': 'traffic_assignment_reassigned_per_failure',
             'time_units': 'seconds', 'assumptions': 'original OD retained; unreachable demand unserved; static equilibrium per failure'},
            self.costs)

    def costs(self, context):
        if context.sample_index is None:
            return self.traffic.edge_seconds
        closed = tuple(sorted(context.closed_link_ids))
        with self.lock:
            if closed not in self.cache:
                damaged = self.graph.copy()
                damaged.remove_edges_from(edge for row in self.links if row['link_id'] in closed for edge in row['_edges'])
                remaining = {(u, v, k) for u, v, k in damaged.edges(keys=True) if u != v}
                reachable = {u: nx.descendants(damaged, u) for u in {u for u, v in self.traffic.demand}}
                served = {pair: q for pair, q in self.traffic.demand.items() if pair[1] in reachable[pair[0]]}
                lost = math.fsum(q for pair, q in self.traffic.demand.items() if pair not in served)
                state = {'status': 'converged', 'iterations': 0, 'relative_gap': 0.}
                times = dict(self.free)
                if not closed:
                    times.update(self.traffic.edge_seconds)
                elif served:
                    for limit in dict.fromkeys((self.config.max_iterations, max(2000, self.config.max_iterations))):
                        assigned, state = assign_traffic(damaged,
                            {e: self.free[e] for e in remaining}, {e: self.traffic.capacities[e] for e in remaining}, served,
                            vdf=self.config.vdf, alpha=self.config.alpha, beta=self.config.beta,
                            relative_gap=self.config.relative_gap, max_iterations=limit)
                        if state['status'] == 'converged':
                            break
                    if state['status'] != 'converged':
                        raise RuntimeError('failure-state traffic assignment did not converge; output not published')
                    times.update({e: assigned[e]['congested_time_s'] for e in remaining})
                extra = self.on_state(times, closed) if self.on_state else {}
                self.cache[closed] = (times, dict(status=state['status'], iterations=state['iterations'],
                    relative_gap=state['relative_gap'], original_demand_pcu_h=sum(self.traffic.demand.values()),
                    unserved_demand_pcu_h=lost, **extra))
                # Bound retained edge maps. Scalar event summaries are cheap and remain complete.
                if len(self.cache) > 8:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(closed)
            times, record = self.cache[closed]
            key = (context.sample_index, closed)
            self.events[key] = dict(sample=context.sample_index, closed_link_ids=json.dumps(closed),
                closed_count=len(closed), **record)
            return times

    def summary(self):
        records = list(self.events.values())
        means = {key: math.fsum(r[key] for r in records)/len(records) for key in records[0]
                 if key not in ('sample', 'iterations') and all(isinstance(r[key], (int, float)) and r[key] is not None for r in records)} if records else {}
        return {'evaluated_states': len(records), 'means': means,
            'all_converged': all(r['status'] == 'converged' for r in records),
            'demand_policy': 'original OD; unreachable trips unserved, not reassigned to other destinations'}

    def write(self, path):
        records = sorted(self.events.values(), key=lambda r: (r['sample'], r['closed_link_ids']))
        if records:
            with Path(path).open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
