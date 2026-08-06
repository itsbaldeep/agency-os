#!/bin/bash
# Approval executor — pick up approved actions and execute them mechanically
set -e

export PGPASSWORD=$(grep POSTGRES_PASSWORD /home/agency/agency-os/.env | cut -d= -f2)
PGCONN="host=100.64.0.1 port=5432 dbname=agencyos user=agency"
CADDY_APPS_DIR="/home/agency/agency-os/caddy-apps"

approvals=$(psql "$PGCONN" -t -A -F'|' -c "
    SELECT id, type, payload
    FROM approvals
    WHERE status='approved'
    ORDER BY requested_at
    LIMIT 10;
" 2>/dev/null)

while IFS='|' read -r id type payload; do
    [ -z "$id" ] && continue
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) executing approval $id type=$type"

    case "$type" in
        dns)
            records=$(echo "$payload" | python3 -c "
import sys, json
p = json.load(sys.stdin)
if 'subdomain' in p:
    print(p['subdomain'])
elif 'records' in p:
    for r in p['records']:
        print(r['name'])
" 2>/dev/null)

            while IFS= read -r subdomain; do
                [ -z "$subdomain" ] && continue
                psql "$PGCONN" -c "UPDATE dns_records SET state='live' WHERE subdomain='$subdomain';" 2>/dev/null
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) DNS live: $subdomain"
            done <<< "$records"
            psql "$PGCONN" -c "UPDATE approvals SET status='executed', executed_at=now() WHERE id=$id;" 2>/dev/null
            ;;

        deploy)
            entries=$(echo "$payload" | python3 -c "
import sys, json
p = json.load(sys.stdin)
# Support both flat {subdomain:..., port:N} and nested {services:[{dns:...,port:...}]}
if 'subdomain' in p and 'port' in p:
    print(f\"{p['subdomain']}|{p['port']}\")
elif 'services' in p:
    for s in p['services']:
        dns = s.get('dns') or s.get('subdomain') or s.get('name')
        port = s.get('port', '')
        print(f\"{dns}|{port}\")
" 2>/dev/null)

            while IFS='|' read -r subdomain port; do
                [ -z "$subdomain" ] && continue
                cat > "${CADDY_APPS_DIR}/${subdomain}.caddy" <<CADDY
${subdomain} {
    reverse_proxy 127.0.0.1:${port}
}
CADDY
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) caddy route: $subdomain -> :$port"
            done <<< "$entries"

            sudo systemctl reload caddy || echo "caddy reload failed (may be first deploy)"
            psql "$PGCONN" -c "UPDATE approvals SET status='executed', executed_at=now() WHERE id=$id;" 2>/dev/null
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) deploy executed for approval $id"
            ;;

        apex-deploy)
            domain=$(echo "$payload" | python3 -c "
import sys, json
p = json.load(sys.stdin)
print(p.get('domain', ''))
" 2>/dev/null)
            port=$(echo "$payload" | python3 -c "
import sys, json
p = json.load(sys.stdin)
print(p.get('port', ''))
" 2>/dev/null)
            www_redirect=$(echo "$payload" | python3 -c "
import sys, json
p = json.load(sys.stdin)
print('true' if p.get('www_redirect', False) else 'false')
" 2>/dev/null)

            if [ -n "$domain" ] && [ -n "$port" ]; then
                cat > "${CADDY_APPS_DIR}/${domain}.caddy" <<CADDY
${domain} {
    reverse_proxy 127.0.0.1:${port}
}

www.${domain} {
    redir https://${domain}{uri} permanent
}
CADDY
                echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) caddy apex route: $domain -> :$port (www redirect created)"
                # Also flip DNS records for both apex and www
                psql "$PGCONN" -c "UPDATE dns_records SET state='live' WHERE subdomain='${domain}';" 2>/dev/null
                psql "$PGCONN" -c "UPDATE dns_records SET state='live' WHERE subdomain='www.${domain}';" 2>/dev/null
                sudo systemctl reload caddy || echo "caddy reload failed"
            fi
            psql "$PGCONN" -c "UPDATE approvals SET status='executed', executed_at=now() WHERE id=$id;" 2>/dev/null
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) apex-deploy executed for approval $id"
            ;;

        *)
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) approval $id type=$type requires agent, skipping"
            ;;
    esac

done <<< "$approvals"
