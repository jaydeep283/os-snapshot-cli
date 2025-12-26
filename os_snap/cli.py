
#!/usr/bin/env python3
"""
A simple CLI for snapshot/restore of OpenStack instances and volumes
using the OpenStack SDK.
"""

import argparse
import logging
import os
import sys
import time

try:
    import openstack
except ImportError:
    print("ERROR: openstacksdk not found. Install it:\n  pip install -r requirements.txt")
    sys.exit(1)

LOG = logging.getLogger("os_snap")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def make_conn():
    """Create connection from environment variables."""
    missing = [v for v in ("OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME")
               if not os.environ.get(v)]
    if missing:
        LOG.error("Missing auth env vars: %s. Did you 'source ~/admin-openrc'?", ", ".join(missing))
        sys.exit(2)

    return openstack.connection.Connection(
        auth_url=os.environ["OS_AUTH_URL"],
        project_name=os.environ["OS_PROJECT_NAME"],
        username=os.environ["OS_USERNAME"],
        password=os.environ["OS_PASSWORD"],
        region_name=os.environ.get("OS_REGION_NAME", "RegionOne"),
        user_domain_name=os.environ.get("OS_USER_DOMAIN_NAME", "Default"),
        project_domain_name=os.environ.get("OS_PROJECT_DOMAIN_NAME", "Default"),
    )


def wait_for_image(conn, image_id, timeout=600):
    start = time.time()
    while True:
        img = conn.image.get_image(image_id)
        status = getattr(img, "status", "").lower()
        if status == "active":
            return img
        if time.time() - start > timeout:
            raise TimeoutError(f"Image {image_id} did not become active in {timeout}s (status={status})")
        time.sleep(3)


def wait_for_server(conn, server_id, timeout=600):
    start = time.time()
    while True:
        srv = conn.compute.get_server(server_id)
        status = getattr(srv, "status", "").upper()
        if status == "ACTIVE":
            return srv
        if time.time() - start > timeout:
            raise TimeoutError(f"Server {server_id} did not become ACTIVE in {timeout}s (status={status})")
        time.sleep(5)


def wait_for_volume(conn, volume_id, timeout=600):
    start = time.time()
    while True:
        vol = conn.block_storage.get_volume(volume_id)
        status = getattr(vol, "status", "").lower()
        if status in ("available", "in-use"):
            return vol
        if time.time() - start > timeout:
            raise TimeoutError(f"Volume {volume_id} did not become available in {timeout}s (status={status})")
        time.sleep(3)


def cmd_server_snapshot(conn, args):
    server = conn.compute.find_server(args.server, ignore_missing=False)
    LOG.info("Creating snapshot image from server '%s' -> '%s'...", server.name, args.name)
    image = conn.compute.create_server_image(server, args.name)
    LOG.info("Snapshot requested. Image ID: %s. Waiting for ACTIVE...", image.id)
    image = wait_for_image(conn, image.id)
    LOG.info("Snapshot ready: %s (%s)", image.name, image.id)


def cmd_server_restore(conn, args):
    image = conn.image.find_image(args.image, ignore_missing=False)
    flavor = conn.compute.find_flavor(args.flavor, ignore_missing=False)

    network = conn.network.find_network(args.network)
    if not network:
        try:
            network = conn.network.get_network(args.network)
        except Exception:
            network = None

    if not network:
        LOG.error("Network '%s' not found. Available networks:", args.network)
        for net in conn.network.networks():
            LOG.error("  - %s (%s) external=%s shared=%s",
                      getattr(net, "name", "?"), net.id,
                      getattr(net, "is_router_external", False),
                      getattr(net, "is_shared", False))
        sys.exit(5)

    LOG.info("Booting new server '%s' from image '%s'...", args.name, image.name)
    srv = conn.compute.create_server(
        name=args.name,
        image_id=image.id,
        flavor_id=flavor.id,
        networks=[{"uuid": network.id}],
        key_name=args.key_name if args.key_name else None,
        security_groups=[{"name": sg} for sg in (args.security_groups or [])]
    )
    srv = wait_for_server(conn, srv.id)
    LOG.info("Server restored: %s (%s) status=%s", srv.name, srv.id, srv.status)


def cmd_volume_snapshot(conn, args):
    volume = conn.block_storage.get_volume(args.volume)
    if not volume:
        LOG.error("Volume %s not found", args.volume)
        sys.exit(3)

    LOG.info("Creating snapshot '%s' from volume '%s'...", args.name, volume.id)
    snap = conn.block_storage.create_snapshot(
        name=args.name,
        volume_id=volume.id,
        force=True
    )

    start = time.time()
    while True:
        snap = conn.block_storage.get_snapshot(snap.id)
        status = getattr(snap, "status", "").lower()
        if status == "available":
            break
        if time.time() - start > 600:
            raise TimeoutError(f"Snapshot {snap.id} did not become available in 600s (status={status})")
        time.sleep(3)

    LOG.info("Snapshot ready: %s (%s) status=%s", snap.name, snap.id, snap.status)


def cmd_volume_restore(conn, args):
    snap = conn.block_storage.get_snapshot(args.snapshot)
    if not snap:
        LOG.error("Snapshot %s not found", args.snapshot)
        sys.exit(4)

    LOG.info("Creating volume '%s' from snapshot '%s'...", args.name, snap.id)
    vol = conn.block_storage.create_volume(
        name=args.name,
        snapshot_id=snap.id,
        size=args.size if args.size else None
    )
    vol = wait_for_volume(conn, vol.id)
    LOG.info("Volume ready: %s (%s) status=%s", vol.name, vol.id, vol.status)


def cmd_list_snapshots(conn, args):
    LOG.info("Instance snapshots (Glance):")
    found_any = False
    for img in conn.image.images():
        props = getattr(img, "properties", {}) or {}
        itype = props.get("image_type")
        itype_top = getattr(img, "image_type", None)
        tags = getattr(img, "tags", []) or []

        is_snapshot = (
            (str(itype).lower() == "snapshot") or
            (str(itype_top).lower() == "snapshot") or
            ("snapshot" in [t.lower() for t in tags]) or
            (str(props.get("image_location", "")).lower() == "snapshot")
        )

        if is_snapshot:
            found_any = True
            print(
                f"- {img.name}  {img.id}  status={getattr(img, 'status', '?')}  "
                f"visibility={getattr(img, 'visibility', '?')}  "
                f"owner={getattr(img, 'owner', '?')}"
            )

    if not found_any:
        LOG.info("No instance snapshots matched.")

    LOG.info("Volume snapshots (Cinder):")
    v_found = False
    for snap in conn.block_storage.snapshots():
        v_found = True
        print(f"- {snap.name}  {snap.id}  status={snap.status}  volume_id={snap.volume_id}")
    if not v_found:
        LOG.info("No volume snapshots found.")



def build_parser():
    p = argparse.ArgumentParser(description="Snapshot/restore CLI for OpenStack instances and volumes")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("server-snapshot", help="Create a snapshot image from a server")
    s1.add_argument("--server", required=True, help="Server name or ID")
    s1.add_argument("--name", required=True, help="Name for the snapshot image")

    s2 = sub.add_parser("server-restore", help="Create a new server from a snapshot image")
    s2.add_argument("--image", required=True, help="Snapshot image name or ID")
    s2.add_argument("--name", required=True, help="New server name")
    s2.add_argument("--flavor", required=True, help="Flavor name or ID (e.g., m1.nano)")
    s2.add_argument("--network", required=True, help="Network name or ID (e.g., provider)")
    s2.add_argument("--key-name", help="Keypair name (optional)")
    s2.add_argument("--security-groups", nargs="*", help="Security group names (optional)")

    v1 = sub.add_parser("volume-snapshot", help="Create a snapshot of a volume")
    v1.add_argument("--volume", required=True, help="Volume ID")
    v1.add_argument("--name", required=True, help="Snapshot name")

    v2 = sub.add_parser("volume-restore", help="Create a volume from a snapshot")
    v2.add_argument("--snapshot", required=True, help="Snapshot ID")
    v2.add_argument("--name", required=True, help="New volume name")
    v2.add_argument("--size", type=int, help="Size in GiB (>= snapshot size; optional)")

    sub.add_parser("list-snapshots", help="List instance and volume snapshots")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    conn = make_conn()

    try:
        if args.cmd == "server-snapshot":
            cmd_server_snapshot(conn, args)
        elif args.cmd == "server-restore":
            cmd_server_restore(conn, args)
        elif args.cmd == "volume-snapshot":
            cmd_volume_snapshot(conn, args)
        elif args.cmd == "volume-restore":
            cmd_volume_restore(conn, args)
        elif args.cmd == "list-snapshots":
            cmd_list_snapshots(conn, args)
        else:
            parser.print_help()
            sys.exit(1)
    except Exception as e:
        LOG.error("Operation failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
