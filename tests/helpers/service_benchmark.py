"""Reproducible offline 2SFCA resource acceptance workload.

Run: python -m tests.helpers.service_benchmark
RSS/USS are sampled over the parent and all recursive worker processes after
warming loky workers. These include interpreter, graph, outputs and allocator
retention; they are not a hard measurement of just the routing workspace.
"""

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter

import networkx as nx
import numpy as np
import psutil
from pyproj import Transformer

from georesilience.config import ServicesConfig, TravelTimeConfig
from georesilience.links import _link_rows
from georesilience.services import prepare_services
from georesilience.sfca import _CatchmentReducer, compute_sfca
from georesilience.shortest_paths import ShortestPathEngine
from georesilience.time_routing import prepare_static_time


def process_memory():
    root = psutil.Process()
    rss, uss = 0, 0
    for process in [root, *root.children(recursive=True)]:
        try:
            info = process.memory_full_info()
            rss += info.rss
            uss += info.uss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {'tree_rss_bytes': rss, 'tree_uss_bytes': uss}


def workload(directory, n=4000, per_type=120):
    graph = nx.MultiDiGraph(crs='EPSG:3857')
    graph.add_nodes_from((i, {'x': float(i*100), 'y': 0.}) for i in range(n))
    for i in range(n):
        j = (i+1) % n
        graph.add_edge(i,j,length=100.,travel_time_s=10.,osmid=i)
        graph.add_edge(j,i,length=100.,travel_time_s=10.,osmid=i)
    path = Path(directory)/'facilities.csv'
    projection = Transformer.from_crs(3857,4326,always_xy=True)
    with path.open('w',newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['facility_id','service_type','longitude','latitude','capacity','capacity_unit','capacity_source'])
        for category in ('school','hospital'):
            for i in range(per_type):
                node = i*n//per_type + (1 if category=='hospital' else 0)
                writer.writerow([f'{category}-{i:04d}',category,*projection.transform(node*100,0),
                    10+i,'seats' if category=='school' else 'beds','synthetic resource workload'])
    config = ServicesConfig(facilities_csv=path,mode='sfca',
        school={'catchment_minutes':2},hospital={'catchment_minutes':3})
    prepared = prepare_services(graph,config)
    routing = prepare_static_time(graph,_link_rows(graph),TravelTimeConfig(time_model='edge_attribute'))
    return graph,1.+np.arange(n)%11,config,prepared,routing


def main():
    with TemporaryDirectory(prefix='cn-benchmark-') as directory:
        graph,population,config,prepared,routing = workload(directory)
        n = len(graph)
        # Force enough one-row tasks to warm both workers and import reducers.
        list(routing.topology.reduce(np.arange(8),_CatchmentReducer(population,()),
            n_jobs=2,budget_bytes=n*64*2,transpose=True,cutoff_seconds=60))
        baseline = process_memory()
        peak = dict(baseline)
        stop = Event()
        def sample():
            while not stop.wait(.01):
                for key,value in process_memory().items():
                    peak[key] = max(peak[key],value)
        monitor = Thread(target=sample,daemon=True)
        monitor.start()
        calls = []
        original = ShortestPathEngine.reduce
        def observed(engine,sources,reducer,**options):
            rows = min(len(sources),engine.chunk_rows)
            calls.append({'source_count':len(sources),'chunk_rows':rows,
                'chunks':int(np.ceil(len(sources)/engine.chunk_rows)),
                'workers':engine.n_jobs,'distance_block_bytes':rows*n*8})
            assert rows < n  # every query is bounded, never an N-by-N dense query
            yield from original(engine,sources,reducer,**options)
        ShortestPathEngine.reduce = observed
        budget = 8*1024**2
        try:
            start = perf_counter()
            parallel = compute_sfca(prepared,population,config,routing,n_jobs=2,budget_bytes=budget)
            elapsed = perf_counter()-start
        finally:
            ShortestPathEngine.reduce = original
            stop.set()
            monitor.join()
        for key,value in process_memory().items():
            peak[key] = max(peak[key],value)
        serial = compute_sfca(prepared,population,config,routing,n_jobs=1,budget_bytes=budget)
        residuals = {}
        for category in ('school','hospital'):
            a,b = parallel.categories[category],serial.categories[category]
            np.testing.assert_allclose(a.node_access,b.node_access,rtol=1e-12,atol=1e-12)
            residuals[category] = float(population@a.node_access-a.summary['positive_demand_capacity'])
            assert abs(residuals[category]) < 1e-8
        assert len(calls)==4 and all(call['chunks']>1 for call in calls)
        print(json.dumps({'nodes':n,'directed_arcs':graph.number_of_edges(),
            'facilities':len(prepared.facilities),'workers':2,'budget_bytes':budget,
            'runtime_seconds':elapsed,'memory_sampling_interval_seconds':.01,
            'memory_method':'sum parent and recursive worker RSS/USS after loky warmup; baseline/peak include graph/output/interpreter/allocator storage',
            'baseline_memory':baseline,'peak_memory':peak,
            'peak_above_baseline':{k:max(0,peak[k]-baseline[k]) for k in peak},
            'routing_passes':calls,'conservation_residuals':residuals,
            'serial_parallel_equal':True},indent=2))


if __name__=='__main__':
    main()
