#!/usr/bin/env bash
# Smoothly start / sleep the komodobots cloud box.
#
# The public URLs point at the Cloudflare *tunnel id* (account-bound), NOT the box IP,
# so after `start` everything (QW servers, cloud hub, dashboard, ttyd shell) comes back
# on its own via systemd — no IP or DNS changes needed. `stop` saves cost; the EBS root
# volume (demos, records, repos, configs) persists across stop/start, so no value is lost.
# Never `stop` mid-match (RAM-only live state would be lost; recorded demos on disk are safe).
#
# Usage: manage.sh {start|stop|status}
set -euo pipefail
AWS="${AWS:-$HOME/.aws-cli-venv/bin/aws}"
PROFILE="${KOMODO_AWS_PROFILE:-komodo}"
REGION="${KOMODO_AWS_REGION:-eu-north-1}"
IID="${KOMODO_INSTANCE_ID:-i-0a47bfde4edd12455}"

q(){ "$AWS" ec2 "$@" --profile "$PROFILE" --region "$REGION"; }
state(){ q describe-instances --instance-ids "$IID" \
  --query 'Reservations[].Instances[].State.Name' --output text 2>/dev/null; }

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
  *)
    echo "usage: manage.sh {start|stop|status}" >&2; exit 2
    ;;
esac
