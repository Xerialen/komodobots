#!/usr/bin/env bash
# Smoothly start / sleep the komodobots cloud box.
#
# The public URLs point at the Cloudflare *tunnel id* (account-bound), NOT the box IP,
# so after `start` everything (QW servers, cloud hub, dashboard, ttyd shell) comes back
# on its own via systemd — no IP or DNS changes needed. `stop` saves cost; the EBS root
# volume (demos, records, repos, configs) persists across stop/start, so no value is lost.
# Never `stop` mid-match (RAM-only live state would be lost; recorded demos on disk are safe).
#
# Data durability: the EBS root volume persists across stop/start, but a single
# volume is a single point of failure. `snapshot` takes a point-in-time backup of
# the whole disk (demos, records, repos, configs) to S3-backed EBS snapshots, from
# which a new volume/box can be restored even if the volume is lost. Cheap and
# incremental. Run it before risky changes and periodically; `snapshots` lists them.
#
# Usage: manage.sh {start|stop|status|snapshot|snapshots}
set -euo pipefail
AWS="${AWS:-$HOME/.aws-cli-venv/bin/aws}"
PROFILE="${KOMODO_AWS_PROFILE:-komodo}"
REGION="${KOMODO_AWS_REGION:-eu-north-1}"
IID="${KOMODO_INSTANCE_ID:-i-0a47bfde4edd12455}"

q(){ "$AWS" ec2 "$@" --profile "$PROFILE" --region "$REGION"; }
state(){ q describe-instances --instance-ids "$IID" \
  --query 'Reservations[].Instances[].State.Name' --output text 2>/dev/null; }
vol(){ q describe-volumes --filters "Name=attachment.instance-id,Values=$IID" \
  --query 'Volumes[].VolumeId' --output text 2>/dev/null; }

case "${1:-status}" in
  start)
    q start-instances --instance-ids "$IID" >/dev/null
    echo "starting $IID — URLs return automatically once boot completes (~40-60s):"
    echo "  owner shell  : https://komodo.xerious.org     (Gmail)"
    echo "  hub+dashboard: https://komodolab.xerious.org   (Gmail)"
    ;;
  stop)
    q stop-instances --instance-ids "$IID" >/dev/null
    echo "stopping $IID — disk persists (demos/records/repos safe); ~\$3/mo while stopped."
    ;;
  status)
    echo "$IID: $(state)"
    ;;
  snapshot)
    V="$(vol)"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    [ -n "$V" ] || { echo "could not resolve root volume for $IID" >&2; exit 1; }
    q create-snapshot --volume-id "$V" \
      --description "komodo lab snapshot $STAMP" \
      --tag-specifications "ResourceType=snapshot,Tags=[{Key=Name,Value=komodo-lab-$STAMP},{Key=project,Value=komodobots},{Key=origin,Value=manage.sh}]" \
      --query '{id:SnapshotId,state:State,vol:VolumeId}' --output table
    echo "point-in-time backup of the whole disk started; list with: $0 snapshots"
    ;;
  snapshots)
    q describe-snapshots --owner-ids self --filters "Name=tag:project,Values=komodobots" \
      --query 'reverse(sort_by(Snapshots,&StartTime))[].{id:SnapshotId,state:State,started:StartTime,GiB:VolumeSize,desc:Description}' \
      --output table
    ;;
  *)
    echo "usage: manage.sh {start|stop|status|snapshot|snapshots}" >&2; exit 2
    ;;
esac
