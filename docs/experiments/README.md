# Experiment protocol

1. Before any AI run, diagnose the scenario manually and record your own time (baseline).
2. Offline run: `python evaluation/offline_lab.py` (real policy and gates, fake cluster).
3. Cluster run: inject with `make inject SCENARIO=<id>`, let the pipeline work, then
   `curl .../incidents/<id>/report` into evidence/<run>/reports/ and `make evaluate`.
4. Record failures and blocked actions, not only successful demos (spec non-goal list).
5. Every new attack idea goes into security/attack-scenarios/playbook.yaml as a regression test.
