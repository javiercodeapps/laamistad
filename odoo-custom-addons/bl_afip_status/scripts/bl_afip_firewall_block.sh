#!/usr/bin/env bash
# Copyright 2026 Ernesto Bernis - BlackLabs

set -u

ACTION="${1:-}"
if [[ "$ACTION" != "block" && "$ACTION" != "unblock" ]]; then
    echo "Uso: $0 {block|unblock}" >&2
    exit 2
fi

HOSTS=(
    "servicios1.afip.gov.ar"
    "wswhomo.afip.gov.ar"
    "wsaa.afip.gov.ar"
    "wsaahomo.afip.gov.ar"
)

if ! command -v getent >/dev/null 2>&1; then
    echo "No se encontro getent" >&2
    exit 1
fi
if ! command -v iptables >/dev/null 2>&1; then
    echo "No se encontro iptables" >&2
    exit 1
fi
if ! command -v ip6tables >/dev/null 2>&1; then
    echo "No se encontro ip6tables" >&2
    exit 1
fi

declare -A IPV4_MAP=()
declare -A IPV6_MAP=()

resolve_host_ips() {
    local host="$1"
    local found=0
    local ip _rest

    while read -r ip _rest; do
        [[ -z "$ip" ]] && continue
        if [[ "$ip" == *:* ]]; then
            IPV6_MAP["$ip"]=1
        else
            IPV4_MAP["$ip"]=1
        fi
        found=1
    done < <(getent ahosts "$host" 2>/dev/null || true)

    if [[ "$found" -eq 0 ]]; then
        echo "No se pudieron resolver IPs para $host" >&2
    fi
}

add_rule() {
    local table_cmd="$1"
    local ip="$2"
    if ! "$table_cmd" -C OUTPUT -p tcp -d "$ip" --dport 443 -j REJECT >/dev/null 2>&1; then
        "$table_cmd" -I OUTPUT -p tcp -d "$ip" --dport 443 -j REJECT
    fi
}

remove_rule() {
    local table_cmd="$1"
    local ip="$2"
    while "$table_cmd" -C OUTPUT -p tcp -d "$ip" --dport 443 -j REJECT >/dev/null 2>&1; do
        "$table_cmd" -D OUTPUT -p tcp -d "$ip" --dport 443 -j REJECT
    done
}

for host in "${HOSTS[@]}"; do
    resolve_host_ips "$host"
done

if [[ "${#IPV4_MAP[@]}" -eq 0 && "${#IPV6_MAP[@]}" -eq 0 ]]; then
    echo "No se resolvio ninguna IP de ARCA/AFIP" >&2
    exit 1
fi

for ip in "${!IPV4_MAP[@]}"; do
    if [[ "$ACTION" == "block" ]]; then
        add_rule iptables "$ip"
    else
        remove_rule iptables "$ip"
    fi
done

for ip in "${!IPV6_MAP[@]}"; do
    if [[ "$ACTION" == "block" ]]; then
        add_rule ip6tables "$ip"
    else
        remove_rule ip6tables "$ip"
    fi
done

echo "bl_afip_firewall_block: accion $ACTION aplicada"
