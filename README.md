
# OpenStack Snapshot CLI

A simple CLI to snapshot and restore **instances** and **volumes** on OpenStack using the **OpenStack SDK**.

## Prerequisites

- Python 3.10+ (Ubuntu 24.04 default)
- OpenStack services up and reachable (Keystone, Glance, Nova, Cinder)
- Source your credentials:
  ```bash
  source ~/admin-openrc
  ```

## Install deps and test

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Source your OpenStack credentials
source ~/admin-openrc

# Quick test: list snapshots
python -m os_snap.cli list-snapshots