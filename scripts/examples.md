
# Examples

## Snapshot then restore an instance
```bash
source ~/admin-openrc
python -m os_snap.cli server-snapshot --server testvm --name testvm-snap-1
python -m os_snap.cli server-restore --image testvm-snap-1 \
  --name testvm-restored --flavor m1.nano --network provider --key-name default
```

## Snapshot then restore a volume
```bash
source ~/admin-openrc
python -m os_snap.cli volume-snapshot --volume <VOL_ID> --name vol-snap-1
python -m os_snap.cli volume-restore --snapshot <SNAP_ID> --name vol-from-snap
