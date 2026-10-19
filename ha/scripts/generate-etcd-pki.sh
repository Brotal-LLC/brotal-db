#!/usr/bin/env bash
set -euo pipefail
umask 077

output=${1:-./generated/etcd-pki}
days=${ETCD_CERT_DAYS:-825}
mkdir -p "$output"
chmod 0700 "$output"

members=(
  'etcd-hm:fluffy:100.64.0.2'
  'etcd-of:pi1:100.64.0.1'
  'etcd-witness:sv1-sg:100.64.0.3'
)
clients=(
  'postgres-armadillo:100.64.0.5'
  'postgres-rogue:100.64.0.4'
  'fluffy:100.64.0.2'
)

ca_key="$output/ca.key"
ca_crt="$output/ca.crt"
if [[ -e $ca_key || -e $ca_crt ]]; then
  printf 'refusing to overwrite existing CA under %s\n' "$output" >&2
  exit 1
fi
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$ca_key"
openssl req -x509 -new -sha256 -key "$ca_key" -days "$days" \
  -subj '/CN=Brotal PostgreSQL etcd CA' -out "$ca_crt"
chmod 0400 "$ca_key"
chmod 0444 "$ca_crt"

issue_certificate() {
  local name=$1 dns=$2 ip=$3 profile=$4
  local dir="$output/$name"
  local eku
  mkdir -p "$dir"
  chmod 0700 "$dir"
  if [[ $profile == member ]]; then
    eku='serverAuth,clientAuth'
  else
    eku='clientAuth'
  fi
  cat >"$dir/extensions.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=$eku
subjectAltName=DNS:$dns,IP:$ip
EOF
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$dir/tls.key"
  openssl req -new -sha256 -key "$dir/tls.key" -subj "/CN=$name" -out "$dir/tls.csr"
  openssl x509 -req -sha256 -in "$dir/tls.csr" -CA "$ca_crt" -CAkey "$ca_key" \
    -CAcreateserial -days "$days" -extfile "$dir/extensions.cnf" -out "$dir/tls.crt"
  cp "$ca_crt" "$dir/ca.crt"
  chmod 0400 "$dir/tls.key"
  chmod 0444 "$dir/tls.crt" "$dir/ca.crt"
  rm -f "$dir/tls.csr" "$dir/extensions.cnf"
  openssl verify -CAfile "$ca_crt" "$dir/tls.crt" >/dev/null
  openssl x509 -in "$dir/tls.crt" -noout -checkend 2592000 >/dev/null
}

for spec in "${members[@]}"; do
  IFS=: read -r name dns ip <<<"$spec"
  issue_certificate "$name" "$dns" "$ip" member
done
for spec in "${clients[@]}"; do
  IFS=: read -r name ip <<<"$spec"
  issue_certificate "$name" "$name" "$ip" client
done

printf 'generated and verified etcd CA, 3 member certificates, and 3 client certificates under %s\n' "$output"
