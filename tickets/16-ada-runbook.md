# 16 — Ada runbook

**What to build:** a user with an IIIT Ada account can run a full city analysis, including exhaustive `criticality.all: true` runs, by following one document and submitting the provided SLURM scripts. The jobs fit Ada's policies and resume after interruption.

**Blocked by:** 14

**Status:** ready-for-agent

## Facts about Ada (from `ADA.pdf`; do not re-derive)
- Nodes: 40 vCPUs, 128 GB RAM.
- Memory: `MaxMemPerCPU` is 3000 MB on the `long` partition, so about 120 GB per 40-CPU job.
- Account `research`, QoS `medium`: 40 CPUs per user, 4 jobs, 4-day wall time.
- Partitions:
  - `short`: 6 h max; for testing only.
  - `long`: unlimited, subject to QoS.
- Each node has Gigabit Ethernet, `/scratch` (2 TB) and `/ssd_scratch` (960 GB). Both are purged after 7–10 days.
- `/home` has a 25 GB quota and is backed up.
- OS: Ubuntu 18.04. Custom Python environments go in `/home`.
- The GPUs are **not used**: RAPIDS/cuGraph doesn't support Pascal GPUs or this OS.
- `srun` interactive sessions are capped at 6 h. Long jobs must use `sbatch`.

## Behaviour

### Environment
- A conda environment spec (`environment-ada.yml`) with every dependency pinned:
  - Python 3.11;
  - a networkit build that works on glibc 2.27 (verify; if pip wheels need a newer glibc, use conda-forge).
- Setup steps in the runbook: install Miniforge into `/home`, create the env, then run `pytest -m "not network and not slow"` on a compute node as the smoke test.

### Job templates (shipped as files in the repository)
- `ada/run_city.sbatch`: one job runs `georesilience run --config $CONFIG`.
  - Settings: `-A research --qos=medium -p long -c 40 --mem-per-cpu=2900M --time=4-00:00:00`, output to a log file.
  - Before the run, `export PYTHONUNBUFFERED=1`; the tool already reads `SLURM_CPUS_PER_TASK`.
  - Working directory on `/scratch/$USER/…`. Results are copied to `/home` (or `/share1`) at the end, and on failure via `trap`.
- `ada/run_city_array.sbatch` for `criticality.all: true`: a **SLURM array** that shards the candidate links (or nodes, for information centrality) across ≤ 4 concurrent tasks, as allowed by the QoS.
  - Adds `--shard i/n` to the CLI (this ticket implements it). A sharded run computes only stages 05/11 for its slice and writes `shard_i.parquet`.
  - `georesilience merge-shards DIR` merges the shards into the final outputs.
  - Requires 03/04 baseline outputs from a prior non-sharded run, passed with `--baseline DIR`.

### Resumability
- Stages 05, 06, 09 and 11 write checkpoints (completed link IDs or steps or sample batches, plus partial accumulators) to `output.dir/checkpoints/` every N minutes (default 15).
- On restart with the same config, completed work is skipped.
- `run_config.yaml` holds a hash of the resolved config. Resuming with a different config is refused.

### Runbook document (README section "Running on Ada")
- Account and VPN prerequisites; the login command.
- Environment setup.
- Choosing a mode:
  - `short` for a test on a 1 km² bbox;
  - a single `long` job for a default city run;
  - an array for exhaustive runs.
- Expected runtimes for a 60k-node graph. Use the design's measured basis (about 6 core-min per full APSP on a laptop, about 2× slower per core on Ada) and **update the numbers with the first real Hyderabad run**.
- Monitoring with `squeue`, `tail -f`; resuming; copying results out (`rsync`).
- The scratch purge warning: copy results within 7 days.

## Acceptance criteria
- [ ] `--shard i/n` plus `merge-shards` on a fixture produce outputs identical to an unsharded run.
- [ ] Checkpoint/resume: a test kills a run mid-stage (simulated by an exception after k units). Re-running gives results identical to an uninterrupted run. Changing a config value refuses to resume.
- [ ] The sbatch files pass `bash -n`, and their resource lines match the policies listed above.
- [ ] The runbook section exists, covering every bullet above.
